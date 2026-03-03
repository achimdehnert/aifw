"""
aifw.nl2sql — NL2SQL engine for DB-driven schema-based SQL generation.

Public API:
    NL2SQLEngine  — main entry point
    NL2SQLResult  — result container
    SchemaSource  — Django model (re-exported for convenience)
"""

from aifw.nl2sql.engine import NL2SQLEngine
from aifw.nl2sql.models import SchemaSource
from aifw.nl2sql.results import (
    ChartConfig,
    FormattedResult,
    GenerationInfo,
    NL2SQLResult,
)

__all__ = [
    "NL2SQLEngine",
    "SchemaSource",
    "NL2SQLResult",
    "GenerationInfo",
    "FormattedResult",
    "ChartConfig",
]
