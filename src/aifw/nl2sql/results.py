"""
aifw.nl2sql.results — Result dataclasses for NL2SQLEngine.ask().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationInfo:
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


@dataclass
class ChartConfig:
    chart_type: str = "table"
    x_column: str = ""
    y_columns: list[str] = field(default_factory=list)
    title: str = ""
    reasoning: str = ""


@dataclass
class FormattedResult:
    columns: list[dict[str, Any]] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    truncated: bool = False
    summary: str = ""
    chart: ChartConfig = field(default_factory=ChartConfig)


@dataclass
class NL2SQLResult:
    success: bool
    sql: str = ""
    error: str = ""
    error_type: str = ""
    warnings: list[str] = field(default_factory=list)
    generation: GenerationInfo | None = None
    formatted: FormattedResult = field(default_factory=FormattedResult)
