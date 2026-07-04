"""
aifw.nl2sql.semantic — Semantic Bridge between natural language and DB schema.

Closes the gap between user language (German, domain-specific, colloquial)
and technical DB schema (English column names, FK IDs, enum values).

Three layers:
  1. GlossaryMapping — synonym/term → column/filter mappings
  2. DomainDetector  — classify query into schema domains
  3. TemporalParser  — "diese Woche", "letzten Monat" → SQL fragments

Design for extraction (ADR-TBD):
  This module has ZERO Django imports at module level.
  Django-dependent features (DB-backed glossary) are lazy-loaded.
  Can be extracted to standalone `nl2sql` package without breaking changes.

Usage::
    bridge = SemanticBridge.from_schema_source("odoo_mfg")
    hints = bridge.analyze("Welche Maschinen sind kaputt?")
    # hints.domain = "casting"
    # hints.semantic_context = "kaputt → state='breakdown'"
    # hints.temporal = None
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Data Classes (Django-free) ──────────────────────────────────────────────


@dataclass
class GlossaryEntry:
    """Single term → schema mapping."""

    term: str  # "kaputt", "Ausschuss", "Lieferant"
    target_column: str  # "state", "total_scrap_pct", "supplier_rank"
    target_table: str  # "casting_machine", "casting_order", "res_partner"
    sql_hint: str  # "state = 'breakdown'", "> 0"
    category: str = "synonym"  # synonym | filter | aggregate | temporal
    language: str = "de"


@dataclass
class TemporalHint:
    """Parsed temporal expression → SQL fragment."""

    original: str  # "diese Woche"
    sql_fragment: str  # "BETWEEN CURRENT_DATE - INTERVAL '7 days' AND CURRENT_DATE"
    column_hint: str = ""  # "date_planned" (suggested column)


@dataclass
class SemanticHints:
    """Result of semantic analysis — injected into LLM prompt."""

    domain: str | None = None
    domain_confidence: float = 0.0
    glossary_matches: list[GlossaryEntry] = field(default_factory=list)
    temporal: TemporalHint | None = None
    semantic_context: str = ""  # Pre-formatted text block for prompt injection

    def to_prompt_block(self) -> str:
        """Format as text block for LLM system prompt injection."""
        if not self.semantic_context:
            return ""
        return f"\nSEMANTISCHE HINWEISE zur aktuellen Frage:\n{self.semantic_context}\n"


# ── Glossary (code-based, extendable to DB) ─────────────────────────────────

# Default German manufacturing glossary.
# Key: lowercased trigger term. Value: GlossaryEntry.
# This can be extended per SchemaSource via DB-backed entries.
_DEFAULT_GLOSSARY: list[GlossaryEntry] = [
    # ── Casting domain ──
    GlossaryEntry("kaputt", "state", "casting_machine", "state = 'breakdown'", "filter"),
    GlossaryEntry("störung", "state", "casting_machine", "state = 'breakdown'", "filter"),
    GlossaryEntry("defekt", "state", "casting_machine", "state = 'breakdown'", "filter"),
    GlossaryEntry("wartung", "state", "casting_machine", "state = 'maintenance'", "filter"),
    GlossaryEntry(
        "ausschuss", "total_scrap_pct", "casting_order", "total_scrap_pct (Prozent)", "synonym"
    ),
    GlossaryEntry("scrap", "total_scrap_pct", "casting_order", "total_scrap_pct", "synonym"),
    GlossaryEntry(
        "ausschussquote", "total_scrap_pct", "casting_order", "total_scrap_pct (Prozent)", "synonym"
    ),
    GlossaryEntry("gutteile", "good_qty", "casting_order_line", "good_qty (Stück)", "synonym"),
    GlossaryEntry(
        "legierung",
        "alloy_id",
        "casting_order_line",
        "FK → casting_alloy: JOIN casting_alloy ca ON ca.id = col.alloy_id",
        "synonym",
    ),
    GlossaryEntry("form", "mold_id", "casting_order_line", "FK → casting_mold", "synonym"),
    GlossaryEntry(
        "gießverfahren", "casting_process", "casting_order_line", "casting_process", "synonym"
    ),
    GlossaryEntry("halle", "hall", "casting_machine", "hall (Standort/Halle)", "synonym"),
    GlossaryEntry("storniert", "state", "casting_order", "state = 'cancelled'", "filter"),
    GlossaryEntry("abgeschlossen", "state", "casting_order", "state = 'done'", "filter"),
    GlossaryEntry("in produktion", "state", "casting_order", "state = 'in_production'", "filter"),
    GlossaryEntry("bestätigt", "state", "casting_order", "state = 'confirmed'", "filter"),
    GlossaryEntry("entwurf", "state", "casting_order", "state = 'draft'", "filter"),
    GlossaryEntry(
        "qualitätsprüfung",
        "result",
        "casting_quality_check",
        "result (pass/fail/conditional)",
        "synonym",
    ),
    GlossaryEntry(
        "prüfung", "result", "casting_quality_check", "result (pass/fail/conditional)", "synonym"
    ),
    # ── Partner / Country ──
    GlossaryEntry("kunde", "customer_rank", "res_partner", "customer_rank > 0", "filter"),
    GlossaryEntry("kunden", "customer_rank", "res_partner", "customer_rank > 0", "filter"),
    GlossaryEntry("lieferant", "supplier_rank", "res_partner", "supplier_rank > 0", "filter"),
    GlossaryEntry("lieferanten", "supplier_rank", "res_partner", "supplier_rank > 0", "filter"),
    GlossaryEntry(
        "land",
        "country_id",
        "res_partner",
        "FK → res_country: JOIN res_country rc ON rc.id = rp.country_id → rc.name",
        "synonym",
    ),
    GlossaryEntry(
        "länder",
        "country_id",
        "res_partner",
        "FK → res_country: JOIN res_country rc ON rc.id = rp.country_id → rc.name",
        "synonym",
    ),
    # ── SCM domain ──
    GlossaryEntry("bestellung", "id", "scm_purchase_order", "scm_purchase_order", "synonym"),
    GlossaryEntry("einkauf", "id", "scm_purchase_order", "scm_purchase_order", "synonym"),
    GlossaryEntry(
        "fertigungsauftrag", "id", "scm_production_order", "scm_production_order", "synonym"
    ),
    GlossaryEntry(
        "produktionsauftrag", "id", "scm_production_order", "scm_production_order", "synonym"
    ),
    GlossaryEntry(
        "ausbeute", "yield_pct", "scm_production_order", "yield_pct (Prozent)", "synonym"
    ),
    GlossaryEntry(
        "überfällig",
        "date_planned",
        "casting_order",
        "date_planned < CURRENT_DATE AND state NOT IN ('done','cancelled')",
        "filter",
    ),
    GlossaryEntry("fällig", "date_planned", "casting_order", "date_planned", "synonym"),
    # ── Stock / Inventory domain ──
    GlossaryEntry(
        "teil",
        "product_id",
        "stock_quant",
        "stock_quant JOIN product_product pp ON pp.id = sq.product_id JOIN product_template pt ON pt.id = pp.product_tmpl_id",
        "synonym",
    ),
    GlossaryEntry(
        "teile",
        "product_id",
        "stock_quant",
        "stock_quant JOIN product_product pp ON pp.id = sq.product_id JOIN product_template pt ON pt.id = pp.product_tmpl_id",
        "synonym",
    ),
    GlossaryEntry(
        "artikel",
        "product_id",
        "stock_quant",
        "stock_quant JOIN product_product → product_template",
        "synonym",
    ),
    GlossaryEntry(
        "produkt", "name", "product_template", "product_template.name->>'en_US' (JSONB)", "synonym"
    ),
    GlossaryEntry(
        "produkte", "name", "product_template", "product_template.name->>'en_US' (JSONB)", "synonym"
    ),
    GlossaryEntry(
        "nullbestand",
        "quantity",
        "stock_quant",
        "quantity <= 0 (auf internen Lagerorten: stock_location.usage = 'internal')",
        "filter",
    ),
    GlossaryEntry(
        "bestand",
        "quantity",
        "stock_quant",
        "SUM(quantity) GROUP BY product_id (nur stock_location.usage = 'internal')",
        "synonym",
    ),
    GlossaryEntry(
        "lagerbestand",
        "quantity",
        "stock_quant",
        "SUM(quantity) über stock_quant WHERE stock_location.usage = 'internal'",
        "synonym",
    ),
    GlossaryEntry(
        "kritisch",
        "product_min_qty",
        "stock_warehouse_orderpoint",
        "Bestand < product_min_qty (stock_warehouse_orderpoint)",
        "filter",
    ),
    GlossaryEntry(
        "mindestbestand",
        "product_min_qty",
        "stock_warehouse_orderpoint",
        "product_min_qty in stock_warehouse_orderpoint",
        "synonym",
    ),
    GlossaryEntry(
        "lagerort",
        "location_id",
        "stock_quant",
        "FK → stock_location: JOIN stock_location sl ON sl.id = sq.location_id → sl.complete_name",
        "synonym",
    ),
    GlossaryEntry("artikelnummer", "default_code", "product_template", "default_code", "synonym"),
    GlossaryEntry("barcode", "barcode", "product_product", "barcode", "synonym"),
]


# ── Temporal patterns ────────────────────────────────────────────────────────

_TEMPORAL_PATTERNS: list[tuple[str, str, str]] = [
    # (regex_pattern, sql_fragment, column_hint)
    (
        r"diese[rnm]?\s+woche",
        "BETWEEN CURRENT_DATE - INTERVAL '7 days' AND CURRENT_DATE",
        "date_planned",
    ),
    (
        r"letzte[rnm]?\s+woche",
        "BETWEEN CURRENT_DATE - INTERVAL '14 days' AND CURRENT_DATE - INTERVAL '7 days'",
        "date_planned",
    ),
    (
        r"diese[rnm]?\s+monat",
        "BETWEEN date_trunc('month', CURRENT_DATE) AND CURRENT_DATE",
        "date_planned",
    ),
    (
        r"letzte[rnm]?\s+monat",
        "BETWEEN date_trunc('month', CURRENT_DATE) - INTERVAL '1 month' AND date_trunc('month', CURRENT_DATE) - INTERVAL '1 day'",
        "date_planned",
    ),
    (r"heute", "= CURRENT_DATE", "date_planned"),
    (r"gestern", "= CURRENT_DATE - INTERVAL '1 day'", "date_planned"),
    (
        r"letzten?\s+(\d+)\s+tage?n?",
        "BETWEEN CURRENT_DATE - INTERVAL '{0} days' AND CURRENT_DATE",
        "date_planned",
    ),
    (
        r"letzten?\s+(\d+)\s+monat(?:e|en)?",
        "BETWEEN CURRENT_DATE - INTERVAL '{0} months' AND CURRENT_DATE",
        "date_planned",
    ),
    (r"dieses\s+jahr", "BETWEEN date_trunc('year', CURRENT_DATE) AND CURRENT_DATE", "create_date"),
    (
        r"letztes\s+jahr",
        "BETWEEN date_trunc('year', CURRENT_DATE) - INTERVAL '1 year' AND date_trunc('year', CURRENT_DATE) - INTERVAL '1 day'",
        "create_date",
    ),
]


# ── Domain detection keywords ────────────────────────────────────────────────

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "casting": [
        "maschine",
        "maschinen",
        "gieß",
        "guss",
        "gießerei",
        "form",
        "legierung",
        "auftrag",
        "aufträge",
        "ausschuss",
        "qualität",
        "prüfung",
        "halle",
        "störung",
        "kaputt",
        "wartung",
        "casting",
        "mold",
    ],
    "scm": [
        "bestellung",
        "einkauf",
        "lieferant",
        "lieferung",
        "fertigung",
        "produktion",
        "bom",
        "stückliste",
        "purchase",
    ],
    "stock": [
        "teil",
        "teile",
        "artikel",
        "produkt",
        "produkte",
        "lager",
        "bestand",
        "nullbestand",
        "lagerbestand",
        "lagerort",
        "kritisch",
        "mindestbestand",
        "barcode",
        "artikelnummer",
        "vorrat",
        "inventory",
        "stock",
        "warehouse",
    ],
    "base": [
        "kunde",
        "kunden",
        "partner",
        "land",
        "länder",
        "firma",
        "unternehmen",
        "kontakt",
        "email",
        "telefon",
    ],
}


# ── SemanticBridge ───────────────────────────────────────────────────────────


class SemanticBridge:
    """Bridges natural language to DB schema semantics.

    Stateless and Django-free at construction time.
    Can be extended with DB-backed glossary entries via load_db_glossary().
    """

    def __init__(
        self,
        glossary: list[GlossaryEntry] | None = None,
        temporal_patterns: list[tuple[str, str, str]] | None = None,
        domain_keywords: dict[str, list[str]] | None = None,
    ) -> None:
        self._glossary = glossary or list(_DEFAULT_GLOSSARY)
        self._temporal = temporal_patterns or list(_TEMPORAL_PATTERNS)
        self._domains = domain_keywords or dict(_DOMAIN_KEYWORDS)
        # Build lookup index: lowered term → [GlossaryEntry, ...]
        self._term_index: dict[str, list[GlossaryEntry]] = {}
        for entry in self._glossary:
            key = entry.term.lower()
            self._term_index.setdefault(key, []).append(entry)

    @classmethod
    def from_schema_source(cls, source_code: str = "odoo_mfg") -> "SemanticBridge":
        """Factory: create bridge with default glossary + optional DB extensions."""
        bridge = cls()
        bridge.load_db_glossary(source_code)
        return bridge

    def load_db_glossary(self, source_code: str) -> int:
        """Load additional glossary entries from DB (if available). Returns count added."""
        try:
            from aifw.nl2sql.models import SchemaSource

            source = SchemaSource.objects.filter(code=source_code, is_active=True).first()
            if source and hasattr(source, "glossary_entries"):
                # Future: DB-backed SemanticGlossary model
                pass
        except Exception:
            pass
        return 0

    def analyze(self, question: str) -> SemanticHints:
        """Analyze a natural language question and return semantic hints."""
        q_lower = question.lower()
        hints = SemanticHints()

        # 1. Glossary matching
        hints.glossary_matches = self._match_glossary(q_lower)

        # 2. Domain detection
        domain, confidence = self._detect_domain(q_lower)
        hints.domain = domain
        hints.domain_confidence = confidence

        # 3. Temporal parsing
        hints.temporal = self._parse_temporal(q_lower)

        # 4. Build prompt block
        hints.semantic_context = self._build_context(hints)

        return hints

    def _match_glossary(self, q_lower: str) -> list[GlossaryEntry]:
        """Find glossary entries whose terms appear in the question."""
        matches: list[GlossaryEntry] = []
        seen_terms: set[str] = set()
        # Sort by term length (longest first) to avoid partial matches
        for term in sorted(self._term_index.keys(), key=len, reverse=True):
            if term in q_lower and term not in seen_terms:
                matches.extend(self._term_index[term])
                seen_terms.add(term)
        return matches

    def _detect_domain(self, q_lower: str) -> tuple[str | None, float]:
        """Score each domain by keyword hits. Returns (domain, confidence)."""
        scores: dict[str, int] = {}
        for domain, keywords in self._domains.items():
            score = sum(1 for kw in keywords if kw in q_lower)
            if score > 0:
                scores[domain] = score
        if not scores:
            return None, 0.0
        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        total = sum(scores.values())
        confidence = scores[best] / total if total > 0 else 0.0
        return best, confidence

    def _parse_temporal(self, q_lower: str) -> TemporalHint | None:
        """Match temporal expressions and return SQL hint."""
        for pattern, sql_tpl, col_hint in self._temporal:
            m = re.search(pattern, q_lower)
            if m:
                # Handle {0} placeholders from captured groups
                sql_fragment = sql_tpl
                if m.groups():
                    sql_fragment = sql_tpl.format(*m.groups())
                return TemporalHint(
                    original=m.group(0),
                    sql_fragment=sql_fragment,
                    column_hint=col_hint,
                )
        return None

    def _build_context(self, hints: SemanticHints) -> str:
        """Format hints as text block for LLM prompt."""
        parts: list[str] = []

        if hints.domain:
            parts.append(
                f"- Erkannte Domäne: {hints.domain} (Konfidenz: {hints.domain_confidence:.0%})"
            )

        if hints.glossary_matches:
            for g in hints.glossary_matches:
                parts.append(f'- "{g.term}" → {g.target_table}.{g.target_column}: {g.sql_hint}')

        if hints.temporal:
            parts.append(
                f'- Zeitbezug "{hints.temporal.original}" → '
                f"{hints.temporal.column_hint} {hints.temporal.sql_fragment}"
            )

        return "\n".join(parts)

    def add_entry(self, entry: GlossaryEntry) -> None:
        """Add a glossary entry at runtime (e.g. from auto-learning)."""
        self._glossary.append(entry)
        key = entry.term.lower()
        self._term_index.setdefault(key, []).append(entry)
