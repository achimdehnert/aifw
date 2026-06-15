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

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from aifw.constants import PrivacyMode, QualityLevel
from aifw.cost import cost_from_rates, estimate_cost
from aifw.exceptions import AIFWError, ConfigurationError, OrchestrationError
from aifw.privacy import PrivacyHook, apply_privacy, get_privacy_hook
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
    "PrivacyMode",
    # Privacy (issue #8)
    "PrivacyHook",
    "apply_privacy",
    "get_privacy_hook",
    # Cost estimation
    "cost_from_rates",
    "estimate_cost",
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

# Single source of truth: the version lives in pyproject.toml and is read back
# from the installed package metadata. Hardcoding it here caused metadata/code
# drift (0.10.1/0.10.2 bumped pyproject but not this constant), which tripped the
# `iil-aifw metadata != code` CI guard in every consumer. Never hardcode again.
try:
    __version__ = _pkg_version("iil-aifw")
except PackageNotFoundError:  # editable/source checkout without installed dist
    __version__ = "0.0.0+unknown"
