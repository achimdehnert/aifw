"""Tests for aifw.schema dataclasses."""

import pytest

from aifw.schema import LLMResult, ToolCall


def test_llm_result_defaults():
    result = LLMResult(success=True, content="Hello")
    assert result.success is True
    assert result.content == "Hello"
    assert result.total_tokens == 0
    assert result.has_tool_calls is False


def test_llm_result_total_tokens():
    result = LLMResult(success=True, input_tokens=100, output_tokens=50)
    assert result.total_tokens == 150


def test_llm_result_failure():
    result = LLMResult(success=False, error="API error")
    assert result.success is False
    assert result.error == "API error"


def test_tool_call_frozen():
    tc = ToolCall(id="call_1", name="search", arguments={"query": "test"})
    assert tc.name == "search"
    assert tc.arguments["query"] == "test"
    with pytest.raises(Exception):
        tc.name = "other"  # frozen dataclass


def test_llm_result_with_tool_calls():
    tc = ToolCall(id="call_1", name="get_weather", arguments={"city": "Berlin"})
    result = LLMResult(success=True, tool_calls=[tc])
    assert result.has_tool_calls is True
    assert result.tool_calls[0].name == "get_weather"


# ── LLMResult.as_json() ───────────────────────────────────────────────────

def test_should_parse_plain_json_from_content():
    """as_json() extracts dict from plain JSON content."""
    result = LLMResult(success=True, content='{"premise": "A hero rises", "themes": ["hope"]}')
    data = result.as_json()
    assert data == {"premise": "A hero rises", "themes": ["hope"]}


def test_should_parse_fenced_json_from_content():
    """as_json() handles ```json ... ``` fenced blocks."""
    content = '```json\n{"score": 9, "reason": "excellent"}\n```'
    result = LLMResult(success=True, content=content)
    data = result.as_json()
    assert data == {"score": 9, "reason": "excellent"}


def test_should_parse_fenced_block_without_language_tag():
    """as_json() handles ``` ... ``` blocks without json tag."""
    content = '```\n{"key": "value"}\n```'
    result = LLMResult(success=True, content=content)
    data = result.as_json()
    assert data == {"key": "value"}


def test_should_return_none_for_non_json_content():
    """as_json() returns None when content is not JSON."""
    result = LLMResult(success=True, content="This is plain text with no JSON.")
    assert result.as_json() is None


def test_should_return_none_for_empty_content():
    """as_json() returns None for empty content."""
    result = LLMResult(success=True, content="")
    assert result.as_json() is None


def test_should_return_none_for_invalid_json():
    """as_json() returns None for malformed JSON."""
    result = LLMResult(success=True, content="{key: value}")
    assert result.as_json() is None


def test_should_parse_nested_json():
    """as_json() handles nested structures."""
    content = '{"chapters": [{"title": "Ch1", "words": 2500}]}'
    result = LLMResult(success=True, content=content)
    data = result.as_json()
    assert data["chapters"][0]["title"] == "Ch1"


# ── LLMResult.field() ─────────────────────────────────────────────────────

def test_should_extract_bold_markdown_field():
    """field() extracts **Field:** value pattern."""
    content = "**Premise:** A young blacksmith discovers magic.\n**Genre:** Fantasy"
    result = LLMResult(success=True, content=content)
    assert result.field("Premise") == "A young blacksmith discovers magic."
    assert result.field("Genre") == "Fantasy"


def test_should_extract_plain_colon_field():
    """field() extracts plain Field: value pattern."""
    content = "Title: The Lost City\nAuthor: Jane Doe"
    result = LLMResult(success=True, content=content)
    assert result.field("Title") == "The Lost City"
    assert result.field("Author") == "Jane Doe"


def test_should_return_default_when_field_missing():
    """field() returns default when field not found."""
    result = LLMResult(success=True, content="No relevant fields here.")
    assert result.field("Premise") is None
    assert result.field("Premise", default="") == ""
    assert result.field("Premise", default="unknown") == "unknown"


def test_should_be_case_insensitive():
    """field() matches regardless of case."""
    content = "PREMISE: A dark knight rises."
    result = LLMResult(success=True, content=content)
    assert result.field("premise") == "A dark knight rises."
    assert result.field("Premise") == "A dark knight rises."


def test_should_return_default_for_empty_content():
    """field() returns default for empty content."""
    result = LLMResult(success=True, content="")
    assert result.field("Title", default="-") == "-"
