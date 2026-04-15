"""
aifw.nl2sql — NL2SQL engine for DB-driven schema-based SQL generation.

Public API:
    NL2SQLEngine   — main entry point (requires Django)
    NL2SQLResult   — result container (Django-free)
    SemanticBridge — glossary + domain detection (Django-free)
    SchemaSource   — Django model (import directly: from aifw.nl2sql.models import SchemaSource)
    NL2SQLExample  — verified Q→SQL pairs for few-shot prompting
    NL2SQLFeedback — error log + corrections for continuous learning

Note: Django models are NOT re-exported here to avoid AppRegistryNotReady errors
when aifw.nl2sql is loaded as a Django app during apps.populate().
Import models directly: from aifw.nl2sql.models import SchemaSource, ...

Extraction-ready (future standalone 'nl2sql' package):
    Django-free modules: semantic.py, results.py, clarification.py
    Django-dependent:    models.py, engine.py (DB access)
"""

default_app_config = "aifw.nl2sql.apps.NL2SQLConfig"

from aifw.nl2sql.results import (  # noqa: E402
    ChartConfig,
    FormattedResult,
    GenerationInfo,
    NL2SQLResult,
)
from aifw.nl2sql.semantic import (  # noqa: E402
    GlossaryEntry,
    SemanticBridge,
    SemanticHints,
    TemporalHint,
)

__all__ = [
    "NL2SQLEngine",
    "NL2SQLResult",
    "GenerationInfo",
    "FormattedResult",
    "ChartConfig",
    "SemanticBridge",
    "SemanticHints",
    "GlossaryEntry",
    "TemporalHint",
    "SchemaSource",
    "NL2SQLExample",
    "NL2SQLFeedback",
]
