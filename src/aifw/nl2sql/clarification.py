"""
aifw.nl2sql.clarification — Intent-Disambiguation vor SQL-Generierung.

ClarificationDetector analysiert ob eine NL-Frage eindeutig genug ist
um direkt SQL zu generieren, oder ob zuerst eine Rückfrage nötig ist.

Der domains-Parameter macht den Detector schema-agnostisch:
    detector = ClarificationDetector(domains=["Maschinen", "Aufträge", ...])
So bleibt aifw.nl2sql Odoo-unabhängig (ADR-011).

Usage::
    detector = ClarificationDetector(
        domains=["Maschinen", "Gießaufträge", "Qualitätsprüfungen"],
    )
    result = detector.analyze("Wie läuft es?")
    if result.is_ambiguous:
        # Rückfrage an User
        print(result.question)
        print(result.options)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ClarificationOption:
    label: str        # "Maschinen"
    description: str  # "Betriebsstatus, Verfügbarkeit, Störungen"
    hint: str         # Wird an Frage angehängt: "— bezogen auf Maschinen"


@dataclass
class ClarificationResult:
    is_ambiguous: bool
    confidence: float            # 0.0 = eindeutig, 1.0 = maximal ambig
    reason: str
    question: str                # Rückfrage an User
    options: list[ClarificationOption] = field(default_factory=list)

    @classmethod
    def from_json(cls, raw: str) -> "ClarificationResult":
        # Extract JSON block — handles Markdown fences and stray text
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            raw = match.group(0)
        data = json.loads(raw)
        opts = []
        for o in data.get("options", []):
            if isinstance(o, str):
                opts.append(ClarificationOption(label=o, description="", hint=f"\u2014 bezogen auf {o}"))
            elif isinstance(o, dict):
                opts.append(ClarificationOption(
                    label=o.get("label", ""),
                    description=o.get("description", ""),
                    hint=o.get("hint", ""),
                ))
        return cls(
            is_ambiguous=bool(data.get("is_ambiguous", False)),
            confidence=float(data.get("confidence", 0.5)),
            reason=data.get("reason", ""),
            question=data.get("question", ""),
            options=opts,
        )


_CLARITY_SYSTEM_TEMPLATE = """\
Du analysierst ob eine NL2SQL-Frage eindeutig genug ist um direkt SQL zu generieren.

Antworte NUR mit diesem exakten JSON-Format (kein Markdown, kein Text davor/danach):
{{
  "is_ambiguous": true,
  "confidence": 0.85,
  "reason": "Kurze Begründung warum ambig",
  "question": "Präzise Rückfrage an den User",
  "options": [
    {{"label": "Maschinen", "description": "Betriebsstatus, Störungen, Wartung", "hint": "— bezogen auf Maschinen"}},
    {{"label": "Gießaufträge", "description": "Auftragsübersicht, Status, Ausschuss", "hint": "— bezogen auf Gießaufträge"}}
  ]
}}

Verfügbare Domänen: {domains}

WICHTIG für options: IMMER Objekte mit label/description/hint — NIEMALS nur Strings!

EINDEUTIG (is_ambiguous=false, confidence<0.5): konkrete Entität, Zahl, Datum, Name, expliziter Filter
AMBIG (is_ambiguous=true, confidence>=0.65): allgemeine Status-Fragen, fehlende Entität, Pronomen ohne Kontext\
"""


class ClarificationDetector:
    """Erkennt ambige NL2SQL-Anfragen und erzeugt Rückfrage-Optionen.

    Args:
        domains:     Liste der verfügbaren Domänen — schema-spezifisch, nicht hardcodiert.
        threshold:   Confidence-Schwelle ab der nachgefragt wird (Standard: 0.65).
        action_code: AIActionType-Code für den Clarity-Check LLM-Call.

    Fail-open: Bei Parse-Fehler oder LLM-Ausfall wird is_ambiguous=False zurückgegeben
    — lieber SQL versuchen als den User zu blockieren.
    """

    DEFAULT_THRESHOLD = 0.65
    HISTORY_THRESHOLD = 0.80  # Mit Gesprächsverlauf: höhere Schwelle nötig

    def __init__(
        self,
        domains: list[str],
        threshold: float = DEFAULT_THRESHOLD,
        action_code: str = "nl2sql_clarity_check",
    ) -> None:
        self.domains = domains
        self.threshold = threshold
        self.action_code = action_code
        self._system_prompt = _CLARITY_SYSTEM_TEMPLATE.format(
            domains=", ".join(domains) if domains else "keine angegeben",
        )

    def analyze(
        self,
        question: str,
        conversation_history: list[dict] | None = None,
    ) -> ClarificationResult:
        """Prüft ob die Frage zu ambig für direktes SQL ist.

        Args:
            question:             Natürlichsprachliche Nutzer-Frage.
            conversation_history: Liste von {role, content} der Vorgänger-Turns.

        Returns:
            ClarificationResult — is_ambiguous=False bei Fehler (fail-open).
        """
        if not self.domains:
            return ClarificationResult(
                is_ambiguous=False,
                confidence=0.0,
                reason="Keine Domänen konfiguriert — Clarification deaktiviert",
                question="",
            )

        history = conversation_history or []
        effective_threshold = self.HISTORY_THRESHOLD if history else self.threshold

        context_note = ""
        if history:
            for entry in reversed(history):
                if entry.get("role") == "user" and entry.get("content"):
                    context_note = f"\nKontext: Vorherige Frage war: {entry['content'][:100]}"
                    break

        from aifw.service import sync_completion

        try:
            llm_result = sync_completion(
                action_code=self.action_code,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": f"Frage: {question}{context_note}"},
                ],
                temperature=0.0,
            )
        except Exception as exc:
            logger.warning("ClarificationDetector LLM-Aufruf fehlgeschlagen: %s", exc)
            return _fail_open()

        if not llm_result.success:
            logger.warning("ClarificationDetector LLM error: %s", llm_result.error)
            return _fail_open()

        try:
            cr = ClarificationResult.from_json(llm_result.content)
            # Threshold-Entscheidung an einer einzigen Stelle
            cr.is_ambiguous = cr.confidence >= effective_threshold
            return cr
        except Exception as exc:
            logger.warning("ClarificationDetector JSON-Parse-Fehler: %s | raw: %s", exc, llm_result.content[:200])
            return _fail_open()


def _fail_open() -> ClarificationResult:
    """Fail-open: im Fehlerfall lieber falsches SQL als den User blockieren."""
    return ClarificationResult(
        is_ambiguous=False,
        confidence=0.0,
        reason="Clarification-Check übersprungen (Fehler)",
        question="",
    )
