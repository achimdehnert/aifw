"""
aifw — Django AI Services Framework

DB-driven LLM provider, model & usage management for Django projects.
"""

__version__ = "0.4.0"

from aifw.schema import LLMResult, RenderedPromptProtocol, ToolCall
from aifw.service import (
    completion,
    completion_stream,
    completion_with_fallback,
    invalidate_config_cache,
    sync_completion,
    sync_completion_stream,
)

__all__ = [
    "LLMResult",
    "RenderedPromptProtocol",
    "ToolCall",
    "completion",
    "completion_stream",
    "completion_with_fallback",
    "invalidate_config_cache",
    "sync_completion",
    "sync_completion_stream",
    "__version__",
]
