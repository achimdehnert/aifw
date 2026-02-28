"""Tests for aifw.service — mocked LiteLLM, no real API calls."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aifw.schema import LLMResult
from aifw.service import _build_model_string, _get_api_key, _parse_tool_calls, sync_completion


def test_build_model_string_openai():
    assert _build_model_string("openai", "gpt-4o") == "gpt-4o"


def test_build_model_string_anthropic():
    assert _build_model_string("anthropic", "claude-3-5-sonnet") == "anthropic/claude-3-5-sonnet"


def test_build_model_string_case_insensitive():
    assert _build_model_string("OpenAI", "gpt-4o") == "gpt-4o"
    assert _build_model_string("Anthropic", "claude-3") == "anthropic/claude-3"


def test_get_api_key_from_env(monkeypatch):
    provider = MagicMock()
    provider.api_key_env_var = "MY_API_KEY"
    monkeypatch.setenv("MY_API_KEY", "sk-test-123")
    assert _get_api_key(provider) == "sk-test-123"


def test_get_api_key_fallback(monkeypatch):
    provider = MagicMock()
    provider.api_key_env_var = ""
    provider.name = "anthropic"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert _get_api_key(provider) == "sk-ant-test"


def test_parse_tool_calls_empty():
    message = MagicMock()
    message.tool_calls = None
    assert _parse_tool_calls(message) == []


def test_parse_tool_calls_with_json_args():
    import json
    tc = MagicMock()
    tc.id = "call_abc"
    tc.function.name = "search"
    tc.function.arguments = json.dumps({"query": "Python"})
    message = MagicMock()
    message.tool_calls = [tc]
    result = _parse_tool_calls(message)
    assert len(result) == 1
    assert result[0].name == "search"
    assert result[0].arguments["query"] == "Python"


def test_parse_tool_calls_with_invalid_json():
    tc = MagicMock()
    tc.id = "call_abc"
    tc.function.name = "search"
    tc.function.arguments = "not-json"
    message = MagicMock()
    message.tool_calls = [tc]
    result = _parse_tool_calls(message)
    assert result[0].arguments == {"raw": "not-json"}


@pytest.mark.asyncio
async def test_completion_no_model_configured():
    from aifw.service import completion

    with patch("aifw.service.get_model_config", new=AsyncMock(return_value={
        "model_string": "",
        "api_key": "",
        "api_base": None,
        "max_tokens": 2000,
        "temperature": 0.7,
        "action_id": None,
        "model_id": None,
        "provider_name": "",
        "model_name": "",
    })):
        result = await completion("unknown_action", [{"role": "user", "content": "hi"}])
        assert result.success is False
        assert "unknown_action" in result.error


@pytest.mark.asyncio
async def test_completion_success():
    from aifw.service import completion

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Hello world"
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].finish_reason = "stop"
    mock_response.model = "anthropic/claude-3-5-sonnet-20241022"
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5

    with patch("aifw.service.get_model_config", new=AsyncMock(return_value={
        "model_string": "anthropic/claude-3-5-sonnet-20241022",
        "api_key": "sk-test",
        "api_base": None,
        "max_tokens": 2000,
        "temperature": 0.7,
        "action_id": 1,
        "model_id": 1,
        "provider_name": "anthropic",
        "model_name": "claude-3-5-sonnet-20241022",
    })), patch("aifw.service._log_usage", new=AsyncMock()), \
         patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await completion("story_writing", [{"role": "user", "content": "Write a story"}])
        assert result.success is True
        assert result.content == "Hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
