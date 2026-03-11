"""
aifw — Django AI Services Framework

DB-driven LLM provider, model & usage management for Django projects.

New in 0.6.0:
    get_action_config()          — quality-level + priority routing lookup
    get_quality_level_for_tier() — DB-driven tier → quality_level mapping
    sync_completion() / completion() extended with quality_level, priority params
    ConfigurationError, OrchestrationError exceptions
    QualityLevel constants, ActionConfig TypedDict
    invalidate_action_cache() / invalidate_tier_cache()
"""

__version__ = "0.9.0"

from aifw.constants import QualityLevel
from aifw.exceptions import AIFWError, ConfigurationError, OrchestrationError
from aifw.schema import LLMResult, RenderedPromptProtocol, ToolCall
from aifw.service import (
    check_action_code,
    completion,
    completion_stream,
    completion_with_fallback,
    get_action_config,
    get_quality_level_for_tier,
    invalidate_action_cache,
    invalidate_config_cache,
    invalidate_tier_cache,
    sync_completion,
    sync_completion_stream,
    sync_completion_with_fallback,
)
from aifw.types import ActionConfig

__all__ = [
    # Version
    "__version__",
    # Constants
    "QualityLevel",
    # Types
    "ActionConfig",
    "LLMResult",
    "RenderedPromptProtocol",
    "ToolCall",
    # Exceptions
    "AIFWError",
    "ConfigurationError",
    "OrchestrationError",
    # Service — new 0.6.0
    "get_action_config",
    "get_quality_level_for_tier",
    "invalidate_action_cache",
    "invalidate_tier_cache",
    # Service — existing
    "check_action_code",
    "completion",
    "completion_stream",
    "completion_with_fallback",
    "invalidate_config_cache",
    "sync_completion",
    "sync_completion_stream",
    "sync_completion_with_fallback",
]
