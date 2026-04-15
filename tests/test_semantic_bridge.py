"""
Tests for aifw.nl2sql.semantic — SemanticBridge.

Django-free: tests only the semantic logic, no DB required.
"""
from __future__ import annotations

import pytest

from aifw.nl2sql.semantic import (
    GlossaryEntry,
    SemanticBridge,
    SemanticHints,
    TemporalHint,
)


@pytest.fixture
def bridge() -> SemanticBridge:
    """Default SemanticBridge with built-in glossary."""
    return SemanticBridge()


# ── Glossary Matching ────────────────────────────────────────────────────────

class TestGlossaryMatching:

    def test_kaputt_maps_to_breakdown(self, bridge: SemanticBridge):
        hints = bridge.analyze("Welche Maschinen sind kaputt?")
        terms = [g.term for g in hints.glossary_matches]
        assert "kaputt" in terms
        match = next(g for g in hints.glossary_matches if g.term == "kaputt")
        assert match.target_table == "casting_machine"
        assert "breakdown" in match.sql_hint

    def test_stoerung_maps_to_breakdown(self, bridge: SemanticBridge):
        hints = bridge.analyze("Maschinen in Störung anzeigen")
        terms = [g.term for g in hints.glossary_matches]
        assert "störung" in terms

    def test_lieferant_maps_to_supplier_rank(self, bridge: SemanticBridge):
        hints = bridge.analyze("Alle Lieferanten aus Deutschland")
        terms = [g.term for g in hints.glossary_matches]
        assert any("lieferant" in t for t in terms)

    def test_land_maps_to_country_fk(self, bridge: SemanticBridge):
        hints = bridge.analyze("Aus welchen Ländern haben wir Aufträge?")
        terms = [g.term for g in hints.glossary_matches]
        assert "länder" in terms
        match = next(g for g in hints.glossary_matches if g.term == "länder")
        assert "res_country" in match.sql_hint

    def test_ausschuss_maps_to_scrap(self, bridge: SemanticBridge):
        hints = bridge.analyze("Wie hoch ist die Ausschussquote?")
        terms = [g.term for g in hints.glossary_matches]
        assert any("ausschuss" in t for t in terms)

    def test_no_match_returns_empty(self, bridge: SemanticBridge):
        hints = bridge.analyze("Hallo wie geht es dir?")
        assert len(hints.glossary_matches) == 0

    def test_multiple_matches(self, bridge: SemanticBridge):
        hints = bridge.analyze("Lieferanten aus welchen Ländern haben kaputte Maschinen?")
        assert len(hints.glossary_matches) >= 3


# ── Domain Detection ─────────────────────────────────────────────────────────

class TestDomainDetection:

    def test_casting_domain(self, bridge: SemanticBridge):
        hints = bridge.analyze("Welche Maschinen sind in Störung?")
        assert hints.domain == "casting"
        assert hints.domain_confidence > 0.5

    def test_scm_domain(self, bridge: SemanticBridge):
        hints = bridge.analyze("Offene Bestellungen beim Lieferanten")
        assert hints.domain == "scm"

    def test_base_domain(self, bridge: SemanticBridge):
        hints = bridge.analyze("Alle Kunden aus Deutschland anzeigen")
        assert hints.domain == "base"

    def test_no_domain_for_generic(self, bridge: SemanticBridge):
        hints = bridge.analyze("Wie ist das Wetter?")
        assert hints.domain is None
        assert hints.domain_confidence == 0.0


# ── Temporal Parsing ─────────────────────────────────────────────────────────

class TestTemporalParsing:

    def test_diese_woche(self, bridge: SemanticBridge):
        hints = bridge.analyze("Aufträge diese Woche")
        assert hints.temporal is not None
        assert "7 days" in hints.temporal.sql_fragment
        assert hints.temporal.column_hint == "date_planned"

    def test_letzten_monat(self, bridge: SemanticBridge):
        hints = bridge.analyze("Bestellungen letzten Monat")
        assert hints.temporal is not None
        assert "1 month" in hints.temporal.sql_fragment

    def test_heute(self, bridge: SemanticBridge):
        hints = bridge.analyze("Was ist heute fällig?")
        assert hints.temporal is not None
        assert "CURRENT_DATE" in hints.temporal.sql_fragment

    def test_letzten_30_tage(self, bridge: SemanticBridge):
        hints = bridge.analyze("Störungen der letzten 30 Tage")
        assert hints.temporal is not None
        assert "30 days" in hints.temporal.sql_fragment

    def test_no_temporal(self, bridge: SemanticBridge):
        hints = bridge.analyze("Alle aktiven Maschinen")
        assert hints.temporal is None


# ── Prompt Block ─────────────────────────────────────────────────────────────

class TestPromptBlock:

    def test_prompt_block_contains_domain(self, bridge: SemanticBridge):
        hints = bridge.analyze("Maschinen in Störung")
        block = hints.to_prompt_block()
        assert "casting" in block
        assert "SEMANTISCHE HINWEISE" in block

    def test_prompt_block_contains_glossary(self, bridge: SemanticBridge):
        hints = bridge.analyze("Ausschussquote der Aufträge")
        block = hints.to_prompt_block()
        assert "total_scrap_pct" in block

    def test_empty_block_for_generic(self, bridge: SemanticBridge):
        hints = bridge.analyze("Hallo Welt")
        block = hints.to_prompt_block()
        assert block == ""


# ── Add Entry (runtime extensibility) ────────────────────────────────────────

class TestAddEntry:

    def test_add_entry_at_runtime(self, bridge: SemanticBridge):
        bridge.add_entry(GlossaryEntry(
            term="rohmaterial",
            target_column="base_material_id",
            target_table="casting_alloy",
            sql_hint="FK → base_material",
            category="synonym",
        ))
        hints = bridge.analyze("Welches Rohmaterial wird verwendet?")
        terms = [g.term for g in hints.glossary_matches]
        assert "rohmaterial" in terms
