"""
aifw/types.py — TypedDict contracts for aifw 0.6.0 public API.

ADR-097 §5.2 — ActionConfig shape.

Consumers (authoringfw, bfagent, etc.) depend on this contract.
Changes to ActionConfig are breaking changes requiring a minor version bump.
"""
from __future__ import annotations

from typing import TypedDict


class ActionConfig(TypedDict):
    """Resolved configuration for one (code, quality_level, priority) lookup.

    Returned by get_action_config(). All fields are always present;
    prompt_template_key may be None if no template is configured for this row.

    Example usage (authoringfw)::

        config = get_action_config("story_writing", quality_level=8, priority="quality")
        template_key = config["prompt_template_key"] or config["action_code"]
        model = config["model"]  # e.g. "gpt-4o"
    """

    action_id: int
    action_code: str
    model_id: int
    model: str            # LiteLLM model string e.g. "gpt-4o", "anthropic/claude-3-5-sonnet"
    provider: str         # Provider name e.g. "openai", "anthropic"
    base_url: str         # Provider base URL (empty string if not set)
    api_key_env_var: str  # Env var name holding the API key
    prompt_template_key: str | None  # promptfw key or None; caller uses action_code as fallback
    max_tokens: int
    temperature: float
