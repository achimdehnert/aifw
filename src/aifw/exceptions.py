"""
aifw/exceptions.py — Exception hierarchy for aifw.

ADR-097 §4 — Exception hierarchy.
"""
from __future__ import annotations


class AIFWError(Exception):
    """Base exception for all aifw errors."""


class ConfigurationError(AIFWError):
    """Raised when required DB configuration is missing.

    This is a deployment/configuration defect, NOT a runtime error.
    It should never be caught and silently swallowed — let it propagate
    so the missing seed data is discovered immediately.

    Example::
        raise ConfigurationError(
            "No AIActionType found for code='story_writing' "
            "with any quality_level/priority — run init_aifw_config."
        )
    """


class OrchestrationError(AIFWError):
    """Raised when an LLM orchestration step fails at runtime.

    Wraps transient or unexpected errors during execution.
    Distinguished from ConfigurationError: this is a runtime failure,
    not a missing-config defect.
    """
