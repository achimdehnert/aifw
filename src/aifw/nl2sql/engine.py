"""
aifw.nl2sql.engine — NL2SQLEngine: NL → SQL → execute → format.

Pipeline:
  0. (Optional) Clarification-Check: ambige Fragen werden vor SQL-Generierung abgefangen
  1. Load SchemaSource from DB
  2. Load NL2SQLExample few-shot pairs for this source
  3. Build LLM prompt (schema XML + few-shot examples + conversation history + question)
  4. Call sync_completion("nl2sql") via aifw service layer
  5. Extract + validate SQL from LLM response
  6. Execute SQL against target DB alias
  7. On error: auto-create NL2SQLFeedback + optional retry with error context
  8. Format result + auto-detect chart type
  9. Return NL2SQLResult
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from aifw.nl2sql.results import (
    ChartConfig,
    FormattedResult,
    GenerationInfo,
    NL2SQLResult,
)

logger = logging.getLogger(__name__)

ALWAYS_BLOCKED = {
    "auth_user", "auth_password", "auth_token",
    "django_session", "authtoken_token",
    "oauth2_provider_accesstoken", "res_users_keys",
    "ir_config_parameter",
}

FORBIDDEN_SQL_KEYWORDS = frozenset([
    "DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE",
    "COPY", "EXECUTE", "DO", "IMPORT", "LOAD", "VACUUM",
    "CLUSTER", "REINDEX", "COMMENT", "SECURITY", "OWNER",
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
])

SYSTEM_PROMPT_TEMPLATE = """Du bist ein präziser SQL-Generator für PostgreSQL.

Deine Aufgabe: Wandle die Nutzerfrage in eine sichere, korrekte SELECT-Abfrage um.

Regeln (absolut):
- Nur SELECT oder WITH … SELECT — kein INSERT/UPDATE/DELETE/DDL
- Keine Subqueries auf gesperrte Tabellen: {blocked_tables}
- Maximal {max_rows} Zeilen (LIMIT verwenden)
- Keine Kommentare im SQL
- Gib NUR das SQL zurück — kein Markdown, keine Erklärung, kein ```sql Block
- Falls die Frage nicht mit SQL beantwortet werden kann: antworte mit EXACTLY: CANNOT_ANSWER

Spaltenaliase (PFLICHT):
- Jede SELECT-Spalte MUSS einen deutschen, sprechenden Alias haben: spalte AS "Deutsch Bezeichnung"
- Technische DB-Namen (state, total_scrap_pct, machine_id, ...) NIEMALS direkt ausgeben
- Aliase müssen zur Nutzerfrage passen: "Welche Maschinen..." → AS "Maschine", AS "Status"
- Beispiel: state AS "Status", total_scrap_pct AS "Ausschuss %", name AS "Auftrag"
- Aggregat-Aliase: COUNT(*) AS "Anzahl", SUM(...) AS "Gesamt", AVG(...) AS "Durchschnitt"

PostgreSQL-Syntax (PFLICHT — KEIN MySQL!):
- INTERVAL immer mit Quotes: INTERVAL '7 days' — NIEMALS INTERVAL 7 DAY
- Datum-Differenz: CURRENT_DATE - INTERVAL '7 days', NICHT DATE_SUB()
- String-Concat: || statt CONCAT()
- Boolean: TRUE/FALSE, nicht 1/0
- ILIKE für case-insensitive, LIKE ist case-sensitive
- LIMIT ohne OFFSET braucht kein Komma

JSONB-Felder (Odoo translated fields):
- name-Spalten in Odoo-Stammdaten (res_country, res_partner, etc.) sind oft JSONB
- Für Text-Vergleiche IMMER casten: name::text ILIKE '%suchbegriff%'
- Für Anzeige: name->>'en_US' AS "Name" ODER name::text AS "Name"
- NIEMALS direkte ILIKE/LIKE auf JSONB ohne Cast

FK-Auflösung (PFLICHT):
- Fremdschlüssel-IDs (z.B. country_id, partner_id, machine_id, alloy_id) NIEMALS als nackte Zahl ausgeben
- Stattdessen IMMER per JOIN die referenzierte Tabelle einbinden und deren name-Feld selektieren
- Beispiel: STATT rp.country_id → JOIN res_country rc ON rc.id = rp.country_id … rc.name AS "Land"
- Beispiel: STATT col.machine_id → JOIN casting_machine cm ON cm.id = col.machine_id … cm.name AS "Maschine"
- Wenn die referenzierte Tabelle nicht im Schema ist, die _id-Spalte komplett weglassen

Schema:
{schema_xml}
"""

FEW_SHOT_HEADER = """
BEWÄHRTE BEISPIELE — diese SQL-Muster sind verifiziert und korrekt.
Verwende sie als Vorlage für ähnliche Fragen:

"""


def _extract_sql(raw: str) -> str | None:
    raw = raw.strip()
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    raw = raw.strip()
    upper = raw.upper().lstrip()
    if upper.startswith("SELECT") or upper.startswith("WITH"):
        return raw
    match = re.search(r"(WITH\s+\w|SELECT\s+)", raw, re.IGNORECASE)
    if match:
        return raw[match.start():].strip()
    return None


def _validate_sql(sql: str, blocked: set[str]) -> str | None:
    upper = sql.upper()
    for kw in FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            return f"Verbotenes Schlüsselwort: {kw}"
    for table in blocked:
        if re.search(rf"\b{re.escape(table)}\b", upper):
            return f"Zugriff auf gesperrte Tabelle: {table}"
    return None


def _classify_error(error_msg: str) -> str:
    msg = error_msg.lower()
    if "does not exist" in msg and "column" in msg:
        return "schema_error"
    if "does not exist" in msg and "table" in msg:
        return "table_error"
    if "syntax error" in msg:
        return "syntax_error"
    if "ambiguous" in msg:
        return "join_error"
    if "timeout" in msg or "statement_timeout" in msg:
        return "timeout"
    return "unknown"


def _detect_chart(columns: list[dict], rows: list[list]) -> ChartConfig:
    if not columns or not rows:
        return ChartConfig(chart_type="table")

    col_count = len(columns)
    row_count = len(rows)
    numeric_cols, text_cols, date_cols = [], [], []

    for col in columns:
        ctype = col.get("type_code", "")
        cname = col.get("name", "").lower()
        if ctype in ("20", "21", "23", "26", "700", "701", "1700"):
            numeric_cols.append(col["name"])
        elif any(k in cname for k in ("date", "datum", "time", "zeit", "monat", "month")):
            date_cols.append(col["name"])
        else:
            text_cols.append(col["name"])

    if row_count == 1 and col_count == 1:
        return ChartConfig(chart_type="kpi", reasoning="Einzelwert")
    if row_count == 1 and len(numeric_cols) >= 2:
        return ChartConfig(chart_type="kpi", reasoning="Mehrere KPIs")
    if date_cols and numeric_cols:
        return ChartConfig(
            chart_type="line",
            x_column=date_cols[0],
            y_columns=numeric_cols[:2],
            reasoning="Zeitreihe erkannt",
        )
    if len(text_cols) == 1 and len(numeric_cols) == 1 and 2 <= row_count <= 8:
        return ChartConfig(
            chart_type="pie",
            x_column=text_cols[0],
            y_columns=numeric_cols,
            reasoning="Kategorieverteilung ≤8 Werte",
        )
    if text_cols and numeric_cols and row_count > 1:
        x = (date_cols + text_cols)[0]
        return ChartConfig(
            chart_type="bar",
            x_column=x,
            y_columns=numeric_cols[:3],
            reasoning="Kategorie + numerische Werte",
        )
    return ChartConfig(chart_type="table")


def _execute_query(
    sql: str,
    db_alias: str,
    max_rows: int,
    timeout_seconds: int,
) -> tuple[list[dict], list[list], float, bool]:
    from django.db import connections

    conn = connections[db_alias]
    start = time.perf_counter()

    with conn.cursor() as cursor:
        if timeout_seconds > 0:
            cursor.execute(f"SET LOCAL statement_timeout = {timeout_seconds * 1000}")
        limited_sql = _inject_limit(sql, max_rows + 1)
        cursor.execute(limited_sql)
        raw_rows = cursor.fetchall()
        description = cursor.description or []

    elapsed_ms = (time.perf_counter() - start) * 1000
    truncated = len(raw_rows) > max_rows
    if truncated:
        raw_rows = raw_rows[:max_rows]

    columns = [{"name": d[0], "type_code": str(d[1])} for d in description]
    rows = [list(r) for r in raw_rows]
    return columns, rows, elapsed_ms, truncated


def _inject_limit(sql: str, limit: int) -> str:
    if re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
        return sql
    sql = sql.rstrip().rstrip(";").rstrip()
    return f"{sql} LIMIT {limit}"


class NL2SQLEngine:
    """Convert natural language to SQL and execute it.

    New in 0.7.0:
    - Few-shot examples from NL2SQLExample injected into system prompt
    - Auto-captures SQL execution errors to NL2SQLFeedback
    - Retry with error context (max 1 retry per question)

    New in 0.8.0:
    - Optional Clarification-Agent: ambige Fragen werden vor SQL-Generierung abgefangen
      Konfigurierbar via clarification_domains=[...] — ohne Domänen deaktiviert

    Usage::
        engine = NL2SQLEngine(
            source_code="odoo_mfg",
            clarification_domains=["Maschinen", "Gießaufträge", "Qualitätsprüfungen"],
        )
        result = engine.ask("Wie läuft es?")
        if result.needs_clarification:
            print(result.clarification_question)
            print(result.clarification_options)
    """

    def __init__(
        self,
        source_code: str = "odoo_mfg",
        clarification_domains: list[str] | None = None,
        enable_semantic: bool = True,
    ) -> None:
        self.source_code = source_code
        self._source: Any = None
        # Einmalig instanziieren — nicht pro _run()-Aufruf
        if clarification_domains:
            from aifw.nl2sql.clarification import ClarificationDetector
            self._clarifier: Any = ClarificationDetector(domains=clarification_domains)
        else:
            self._clarifier = None
        # Semantic Bridge — opt-in, non-breaking
        if enable_semantic:
            from aifw.nl2sql.semantic import SemanticBridge
            self._semantic: Any = SemanticBridge.from_schema_source(source_code)
        else:
            self._semantic = None

    def _load_source(self):
        if self._source is not None:
            return self._source
        from aifw.nl2sql.models import SchemaSource
        source = SchemaSource.objects.filter(code=self.source_code, is_active=True).first()
        if source is None:
            raise ValueError(
                f"SchemaSource '{self.source_code}' nicht gefunden oder inaktiv. "
                "Bitte 'python manage.py init_odoo_schema' ausführen."
            )
        self._source = source
        return source

    def _load_examples(self, source) -> list:
        try:
            from aifw.nl2sql.models import NL2SQLExample
            return list(
                NL2SQLExample.objects.filter(source=source, is_active=True)
                .order_by("difficulty", "id")[:15]
            )
        except Exception:
            return []

    def _build_few_shot_block(self, examples: list) -> str:
        if not examples:
            return ""
        block = FEW_SHOT_HEADER
        for ex in examples:
            block += f"FRAGE: {ex.question}\nSQL:\n{ex.sql}\n\n"
        return block

    def _capture_feedback(self, source, question: str, bad_sql: str, error_msg: str) -> int | None:
        try:
            from aifw.nl2sql.models import NL2SQLFeedback
            fb = NL2SQLFeedback.objects.create(
                source=source,
                question=question,
                bad_sql=bad_sql,
                error_message=error_msg,
                error_type=_classify_error(error_msg),
            )
            return fb.pk
        except Exception as e:
            logger.warning("NL2SQLFeedback konnte nicht gespeichert werden: %s", e)
            return None

    def _auto_promote_correction(
        self, feedback_pk: int | None, source, question: str, corrected_sql: str,
    ) -> None:
        """When retry succeeds, store corrected SQL and auto-promote to example."""
        if feedback_pk is None:
            return
        try:
            from aifw.nl2sql.models import NL2SQLExample, NL2SQLFeedback

            fb = NL2SQLFeedback.objects.get(pk=feedback_pk)
            fb.corrected_sql = corrected_sql
            fb.promoted = True
            fb.save(update_fields=["corrected_sql", "promoted"])

            exists = NL2SQLExample.objects.filter(
                source=source, question=question,
            ).exists()
            if not exists:
                NL2SQLExample.objects.create(
                    source=source,
                    question=question,
                    sql=corrected_sql,
                    domain="auto",
                    difficulty=2,
                    is_active=True,
                    promoted_from=fb,
                )
                logger.info(
                    "NL2SQL auto-promoted: '%s' → Example (from feedback #%d)",
                    question[:60], feedback_pk,
                )
        except Exception as e:
            logger.warning("Auto-promote fehlgeschlagen: %s", e)

    def _load_error_antipatterns(self, source) -> str:
        """Load recent error patterns as anti-examples for the prompt."""
        try:
            from django.db.models import Count
            from aifw.nl2sql.models import NL2SQLFeedback

            patterns = (
                NL2SQLFeedback.objects
                .filter(source=source, promoted=False)
                .values("error_type", "error_message")
                .annotate(count=Count("id"))
                .filter(count__gte=2)
                .order_by("-count")[:5]
            )
            if not patterns:
                return ""

            block = "\nHÄUFIGE FEHLER — vermeide diese Muster:\n"
            for p in patterns:
                msg = p["error_message"][:120]
                block += f"- {p['error_type']} ({p['count']}x): {msg}\n"
            return block
        except Exception:
            return ""

    def ask(
        self,
        question: str,
        conversation_history: list[dict] | None = None,
    ) -> NL2SQLResult:
        try:
            return self._run(question, conversation_history or [], retry_count=0)
        except ValueError:
            raise
        except Exception as exc:
            logger.exception("NL2SQLEngine.ask() unerwarteter Fehler")
            return NL2SQLResult(success=False, error=str(exc), error_type="InternalError")

    def _run(
        self,
        question: str,
        conversation_history: list[dict],
        retry_count: int = 0,
        _first_feedback_pk: int | None = None,
    ) -> NL2SQLResult:
        # Stufe 0: Clarification-Check (nur beim ersten Versuch, nicht bei Retry)
        if self._clarifier is not None and retry_count == 0:
            clarity = self._clarifier.analyze(question, conversation_history=conversation_history)
            if clarity.is_ambiguous:
                logger.info("NL2SQL Clarification benötigt für: %s (confidence=%.2f)", question, clarity.confidence)
                return NL2SQLResult(
                    success=False,
                    needs_clarification=True,
                    clarification_question=clarity.question,
                    clarification_options=[vars(o) for o in clarity.options],
                    error="",
                )

        source = self._load_source()
        blocked = source.get_blocked_tables_set() | ALWAYS_BLOCKED
        examples = self._load_examples(source)
        few_shot = self._build_few_shot_block(examples)

        antipatterns = self._load_error_antipatterns(source)

        # Semantic Bridge: analyze question → inject hints
        semantic_block = ""
        if self._semantic is not None:
            try:
                hints = self._semantic.analyze(question)
                semantic_block = hints.to_prompt_block()
                if hints.domain:
                    logger.debug(
                        "NL2SQL Semantic: domain=%s conf=%.0f%% matches=%d",
                        hints.domain, hints.domain_confidence * 100,
                        len(hints.glossary_matches),
                    )
            except Exception as e:
                logger.warning("SemanticBridge Fehler (non-fatal): %s", e)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            blocked_tables=", ".join(sorted(blocked)),
            max_rows=source.max_rows,
            schema_xml=source.schema_xml,
        ) + few_shot + antipatterns + semantic_block

        messages = [{"role": "system", "content": system_prompt}]
        for h in conversation_history:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})

        from aifw.service import sync_completion

        llm_result = sync_completion(action_code="nl2sql", messages=messages, temperature=0.05)

        generation = GenerationInfo(
            model_used=llm_result.model,
            input_tokens=llm_result.input_tokens,
            output_tokens=llm_result.output_tokens,
            latency_ms=llm_result.latency_ms,
        )

        if not llm_result.success:
            return NL2SQLResult(
                success=False,
                error=f"LLM-Aufruf fehlgeschlagen: {llm_result.error}",
                error_type="LLMError",
                generation=generation,
            )

        raw_sql = _extract_sql(llm_result.content)
        if raw_sql is None:
            if "CANNOT_ANSWER" in llm_result.content.upper():
                return NL2SQLResult(
                    success=False,
                    error="Diese Frage kann nicht mit SQL beantwortet werden.",
                    error_type="NL2SQLGenerationError",
                    generation=generation,
                )
            return NL2SQLResult(
                success=False,
                error=f"LLM hat kein gültiges SQL generiert: {llm_result.content[:200]}",
                error_type="NL2SQLGenerationError",
                generation=generation,
            )

        validation_error = _validate_sql(raw_sql, blocked)
        if validation_error:
            return NL2SQLResult(
                success=False,
                sql=raw_sql,
                error=f"SQL-Sicherheitsprüfung fehlgeschlagen: {validation_error}",
                error_type="NL2SQLValidationError",
                generation=generation,
            )

        try:
            columns, rows, elapsed_ms, truncated = _execute_query(
                sql=raw_sql,
                db_alias=source.db_alias,
                max_rows=source.max_rows,
                timeout_seconds=source.timeout_seconds,
            )
        except Exception as exc:
            err_str = str(exc)
            logger.warning("NL2SQL SQL-Ausführungsfehler: %s | SQL: %s", err_str, raw_sql)

            feedback_pk = self._capture_feedback(source, question, raw_sql, err_str)

            if retry_count < 1:
                logger.info("NL2SQL Retry mit Fehler-Kontext für: %s", question)
                retry_history = conversation_history + [
                    {"role": "assistant", "content": raw_sql},
                    {"role": "user", "content": (
                        f"Das SQL hat einen Fehler: {err_str}\n"
                        "Bitte korrigiere das SQL. "
                        "Wichtig: Verwende PostgreSQL-Syntax (INTERVAL '7 days' nicht INTERVAL 7 DAY). "
                        "Prüfe die Join-Hints im Schema sorgfältig "
                        "und verwende nur Felder die dort explizit aufgelistet sind."
                    )},
                ]
                return self._run(
                    question, retry_history,
                    retry_count=1, _first_feedback_pk=feedback_pk,
                )

            return NL2SQLResult(
                success=False,
                sql=raw_sql,
                error=f"SQL-Ausführungsfehler: {err_str}",
                error_type="NL2SQLExecutionError",
                generation=generation,
            )

        warnings: list[str] = []
        if truncated:
            warnings.append(f"Ergebnis auf {source.max_rows} Zeilen gekürzt.")

        chart = _detect_chart(columns, rows)
        row_count = len(rows)
        summary = f"{row_count} {'Zeile' if row_count == 1 else 'Zeilen'} — {elapsed_ms:.0f} ms"

        formatted = FormattedResult(
            columns=columns,
            rows=rows,
            row_count=row_count,
            execution_time_ms=elapsed_ms,
            truncated=truncated,
            summary=summary,
            chart=chart,
        )

        if retry_count > 0 and _first_feedback_pk is not None:
            self._auto_promote_correction(
                _first_feedback_pk, source, question, raw_sql,
            )

        return NL2SQLResult(
            success=True,
            sql=raw_sql,
            warnings=warnings,
            generation=generation,
            formatted=formatted,
        )
