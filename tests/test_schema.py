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
