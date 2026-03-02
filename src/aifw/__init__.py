"""
aifw — Django AI Services Framework

DB-driven LLM provider, model & usage management for Django projects.
"""

__version__ = "0.5.0"

from aifw.schema import LLMResult, RenderedPromptProtocol, ToolCall
from aifw.service import (
    check_action_code,
    completion,
    completion_stream,
    completion_with_fallback,
    invalidate_config_cache,
    sync_completion,
    sync_completion_stream,
    sync_completion_with_fallback,
)

__all__ = [
    "LLMResult",
    "RenderedPromptProtocol",
    "ToolCall",
    "check_action_code",
    "completion",
    "completion_stream",
    "completion_with_fallback",
    "invalidate_config_cache",
    "sync_completion",
    "sync_completion_stream",
    "sync_completion_with_fallback",
    "__version__",
]
