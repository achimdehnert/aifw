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

    def as_json(self) -> dict[str, Any] | None:
        """Extract JSON object from content. Returns None if not parseable.

        Tries promptfw.parsing.extract_json first, falls back to stdlib json.
        Handles fenced code blocks (```json ... ```) automatically.

        Example::

            result = sync_completion("story_planning", messages)
            data = result.as_json()  # {"premise": "...", "themes": [...]}
        """
        try:
            from promptfw.parsing import extract_json
            return extract_json(self.content)
        except ImportError:
            pass
        import json
        import re
        text = self.content.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    def field(self, name: str, default: Any = None) -> Any:
        """Extract a named Markdown field from content.

        Looks for patterns like ``**Field:** value`` or ``Field: value``
        (case-insensitive). Returns default if not found.

        Tries promptfw.parsing.extract_field first, falls back to regex.

        Example::

            result = sync_completion("story_planning", messages)
            premise = result.field("Premise")
            premise = result.field("Premise", default="")
        """
        try:
            from promptfw.parsing import extract_field
            return extract_field(self.content, name, default=default)
        except ImportError:
            pass
        import re
        pattern = re.compile(
            r"(?:^|\n)\s*\*{0,2}" + re.escape(name) + r"\*{0,2}\s*:[ \t]*(.+)",
            re.IGNORECASE,
        )
        match = pattern.search(self.content)
        if match:
            return match.group(1).strip()
        return default
