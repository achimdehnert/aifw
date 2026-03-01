"""Shared data classes and protocols for aifw LLM responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RenderedPromptProtocol(Protocol):
    """Structural interface for promptfw.RenderedPrompt (and compatible types).

    Any object with ``system`` and ``user`` string attributes satisfies this
    protocol.  Pass such objects directly to ``completion()`` or
    ``sync_completion()`` instead of manually building a messages list.

    Example (promptfw)::

        from promptfw import PromptRenderer
        rendered = PromptRenderer().render(stack, context)
        result = sync_completion("story_writing", rendered)
    """

    system: str
    user: str


@dataclass(frozen=True)
class ToolCall:
    """Extracted tool call from LLM response."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResult:
    """Unified result from any LLM provider."""

    success: bool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
