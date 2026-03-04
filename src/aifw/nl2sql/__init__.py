"""
aifw.nl2sql — NL2SQL engine for DB-driven schema-based SQL generation.

Public API:
    NL2SQLEngine  — main entry point
    NL2SQLResult  — result container
    SchemaSource  — Django model (re-exported for convenience)
    NL2SQLExample — verified Q→SQL pairs for few-shot prompting
    NL2SQLFeedback — error log + corrections for continuous learning
"""

default_app_config = "aifw.nl2sql.apps.NL2SQLConfig"

from aifw.nl2sql.engine import NL2SQLEngine
from aifw.nl2sql.models import NL2SQLExample, NL2SQLFeedback, SchemaSource
from aifw.nl2sql.results import (
    ChartConfig,
    FormattedResult,
    GenerationInfo,
    NL2SQLResult,
)

__all__ = [
    "NL2SQLEngine",
    "SchemaSource",
    "NL2SQLExample",
    "NL2SQLFeedback",
    "NL2SQLResult",
    "GenerationInfo",
    "FormattedResult",
    "ChartConfig",
]
