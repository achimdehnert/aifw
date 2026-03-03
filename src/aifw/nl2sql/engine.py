"""
aifw.nl2sql.engine — NL2SQLEngine: NL → SQL → execute → format.

Pipeline:
  1. Load SchemaSource from DB
  2. Build LLM prompt (schema XML + conversation history + question)
  3. Call sync_completion("nl2sql") via aifw service layer
  4. Extract + validate SQL from LLM response
  5. Execute SQL against target DB alias
  6. Format result + auto-detect chart type
  7. Return NL2SQLResult
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
- Nur SELECT oder WITH ... SELECT — kein INSERT/UPDATE/DELETE/DDL
- Keine Subqueries auf gesperrte Tabellen: {blocked_tables}
- Maximal {max_rows} Zeilen (LIMIT verwenden)
- Keine Kommentare im SQL
- Gib NUR das SQL zurück — kein Markdown, keine Erklärung, kein ```sql Block
- Falls die Frage nicht mit SQL beantwortet werden kann: antworte mit EXACTLY: CANNOT_ANSWER

Schema:
{schema_xml}
"""


def _extract_sql(raw: str) -> str | None:
    """Extract clean SQL from LLM response. Returns None if unparseable."""
    text = raw.strip()

    if text.upper().startswith("CANNOT_ANSWER"):
        return None

    sql_match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        text = sql_match.group(1).strip()

    text = re.sub(r"--.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = text.strip().rstrip(";")

    if not text:
        return None

    upper = text.upper()
    if not re.match(r"^\s*(SELECT|WITH)\b", upper):
        return None

    return text


def _validate_sql(sql: str, blocked: set[str]) -> str | None:
    """Validate SQL safety. Returns error string or None if OK."""
    upper = sql.upper()

    for kw in FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            return f"Verbotenes SQL-Schlüsselwort: {kw}"

    for table in blocked:
        if re.search(rf"\b{re.escape(table)}\b", sql, re.IGNORECASE):
            return f"Zugriff auf gesperrte Tabelle nicht erlaubt: {table}"

    statements = [s.strip() for s in re.split(r";", sql) if s.strip()]
    if len(statements) > 1:
        return "Nur eine SQL-Abfrage gleichzeitig erlaubt"

    return None


def _detect_chart(columns: list[dict], rows: list[list]) -> ChartConfig:
    """Heuristic chart-type detection from result shape."""
    if not columns or not rows:
        return ChartConfig(chart_type="table")

    col_count = len(columns)
    row_count = len(rows)

    numeric_cols = []
    text_cols = []
    date_cols = []

    for col in columns:
        ctype = str(col.get("type_code", col.get("type", "text"))).lower()
        cname = col.get("name", "").lower()

        if ctype in ("int2", "int4", "int8", "integer", "bigint", "smallint",
                     "float4", "float8", "numeric", "decimal", "real",
                     "double precision", "money"):
            numeric_cols.append(col["name"])
        elif ctype in ("date", "timestamp", "timestamptz", "datetime") or \
                any(k in cname for k in ("date", "datum", "monat", "month",
                                          "year", "jahr", "zeit", "time")):
            date_cols.append(col["name"])
        else:
            text_cols.append(col["name"])

    if row_count == 1 and col_count == 1:
        return ChartConfig(chart_type="kpi", reasoning="Einzelwert")

    if row_count == 1 and len(numeric_cols) >= 2:
        return ChartConfig(chart_type="kpi", reasoning="Mehrere KPIs")

    x_col = (date_cols + text_cols or [columns[0]["name"]])[0]
    y_cols = numeric_cols[:3] if numeric_cols else []

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
            reasoning="Kategorieverteilung mit <=8 Werten",
        )

    if text_cols and numeric_cols and row_count > 1:
        return ChartConfig(
            chart_type="bar",
            x_column=x_col,
            y_columns=y_cols,
            reasoning="Kategorie + numerische Werte",
        )

    return ChartConfig(chart_type="table", x_column=x_col, y_columns=y_cols)


def _execute_query(
    sql: str,
    db_alias: str,
    max_rows: int,
    timeout_seconds: int,
) -> tuple[list[dict], list[list], float, bool]:
    """Execute SQL and return (columns, rows, elapsed_ms, truncated).

    columns: list of {name, type_code}
    rows: list of lists (values)
    """
    from django.db import connections

    conn = connections[db_alias]
    start = time.perf_counter()

    with conn.cursor() as cursor:
        if timeout_seconds > 0:
            cursor.execute(f"SET LOCAL statement_timeout = {timeout_seconds * 1000}")

        fetch_limit = max_rows + 1
        limited_sql = _inject_limit(sql, fetch_limit)
        cursor.execute(limited_sql)

        raw_rows = cursor.fetchall()
        description = cursor.description or []

    elapsed_ms = (time.perf_counter() - start) * 1000

    truncated = len(raw_rows) > max_rows
    if truncated:
        raw_rows = raw_rows[:max_rows]

    columns = [
        {"name": desc[0], "type_code": str(desc[1])}
        for desc in description
    ]
    rows = [list(row) for row in raw_rows]

    return columns, rows, elapsed_ms, truncated


def _inject_limit(sql: str, limit: int) -> str:
    """Append LIMIT to SQL if not already present."""
    upper = sql.upper()
    if re.search(r"\bLIMIT\s+\d+", upper):
        return sql
    return f"{sql} LIMIT {limit}"


class NL2SQLEngine:
    """Convert a natural language question to SQL and execute it.

    Usage::
        engine = NL2SQLEngine(source_code="odoo_mfg")
        result = engine.ask("Welche Maschinen sind in Störung?")
        if result.success:
            print(result.formatted.rows)
        else:
            print(result.error)
    """

    def __init__(self, source_code: str = "odoo_mfg") -> None:
        self.source_code = source_code
        self._source: Any = None

    def _load_source(self):
        if self._source is not None:
            return self._source
        from aifw.nl2sql.models import SchemaSource
        source = SchemaSource.objects.filter(
            code=self.source_code, is_active=True
        ).first()
        if source is None:
            raise ValueError(
                f"SchemaSource '{self.source_code}' nicht gefunden oder inaktiv. "
                f"Bitte 'python manage.py init_odoo_schema' ausführen."
            )
        self._source = source
        return source

    def ask(
        self,
        question: str,
        conversation_history: list[dict] | None = None,
    ) -> NL2SQLResult:
        """Translate question to SQL, execute, and return formatted result."""
        try:
            return self._run(question, conversation_history or [])
        except ValueError:
            raise
        except Exception as exc:
            logger.exception("NL2SQLEngine.ask() unerwarteter Fehler")
            return NL2SQLResult(
                success=False,
                error=str(exc),
                error_type="InternalError",
            )

    def _run(
        self,
        question: str,
        conversation_history: list[dict],
    ) -> NL2SQLResult:
        source = self._load_source()
        blocked = source.get_blocked_tables_set() | ALWAYS_BLOCKED

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            blocked_tables=", ".join(sorted(blocked)),
            max_rows=source.max_rows,
            schema_xml=source.schema_xml,
        )

        messages = [{"role": "system", "content": system_prompt}]
        for h in conversation_history:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})

        from aifw.service import sync_completion

        llm_result = sync_completion(
            action_code="nl2sql",
            messages=messages,
            temperature=0.05,
        )

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

        warnings: list[str] = []
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
            return NL2SQLResult(
                success=False,
                sql=raw_sql,
                error=f"SQL-Ausführungsfehler: {err_str}",
                error_type="NL2SQLExecutionError",
                generation=generation,
            )

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

        return NL2SQLResult(
            success=True,
            sql=raw_sql,
            warnings=warnings,
            generation=generation,
            formatted=formatted,
        )
