"""
aifw.nl2sql.results — Result dataclasses for NL2SQLEngine.ask().

These are consumed by aifw_service/views.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationInfo:
    """Metadata about the LLM generation step."""

    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


@dataclass
class ChartConfig:
    """Auto-detected chart configuration for the result set."""

    chart_type: str = "table"
    x_column: str = ""
    y_columns: list[str] = field(default_factory=list)
    title: str = ""
    reasoning: str = ""


@dataclass
class FormattedResult:
    """Query execution result in a serialization-ready format."""

    columns: list[dict[str, Any]] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    truncated: bool = False
    summary: str = ""
    chart: ChartConfig = field(default_factory=ChartConfig)


@dataclass
class NL2SQLResult:
    """Full result from NL2SQLEngine.ask().

    On success: success=True, sql set, formatted populated.
    On failure: success=False, error/error_type set.
    """

    success: bool
    sql: str = ""
    error: str = ""
    error_type: str = ""
    warnings: list[str] = field(default_factory=list)
    generation: GenerationInfo | None = None
    formatted: FormattedResult = field(default_factory=FormattedResult)
