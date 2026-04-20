"""Cost estimation for LLM calls.

Tries litellm.cost_per_token() first (precise, model-aware),
falls back to built-in rate table. Always returns Decimal, never raises.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import litellm

if TYPE_CHECKING:
    from aifw.schema import LLMResult

# Fallback rates: $/1M tokens (input, output)
_FALLBACK_RATES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-sonnet-4-5-20250514": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "mixtral-8x7b-32768": (0.24, 0.24),
}


def estimate_cost(
    result: LLMResult | None = None,
    *,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> Decimal:
    """Estimate LLM call cost from an LLMResult or explicit parameters.

    Uses litellm.cost_per_token() when available, falls back to a
    built-in rate table. Always returns Decimal (never raises).

    Usage::

        from aifw import estimate_cost

        # From LLMResult
        result = sync_completion("story_writing", messages)
        cost = estimate_cost(result)

        # From explicit parameters
        cost = estimate_cost(model="gpt-4o", input_tokens=500, output_tokens=1200)
    """
    if result is not None:
        model = model or result.model
        input_tokens = input_tokens or result.input_tokens
        output_tokens = output_tokens or result.output_tokens

    if not model or (input_tokens == 0 and output_tokens == 0):
        return Decimal("0")

    # 1. Try litellm (precise, up-to-date rates)
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        )
        return Decimal(str(round(prompt_cost + completion_cost, 8)))
    except Exception:
        pass

    # 2. Fallback: built-in rate table
    try:
        model_key = model.split("/")[-1]
        pin, pout = _FALLBACK_RATES.get(model_key, (0.15, 0.60))
        cost = input_tokens * pin / 1_000_000 + output_tokens * pout / 1_000_000
        return Decimal(str(round(cost, 8)))
    except Exception:
        return Decimal("0")
