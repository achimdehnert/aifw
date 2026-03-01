"""Tests for aifw.service — mocked LiteLLM, no real API calls."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aifw.schema import LLMResult, RenderedPromptProtocol
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


# ---------------------------------------------------------------------------
# RenderedPromptProtocol tests
# ---------------------------------------------------------------------------

def test_should_recognise_rendered_prompt_protocol():
    """Any object with system+user attributes satisfies RenderedPromptProtocol."""
    class FakeRendered:
        system = "You are a writer."
        user = "Write a chapter."

    assert isinstance(FakeRendered(), RenderedPromptProtocol)


def test_should_reject_plain_dict_as_rendered_prompt():
    """A plain dict does NOT satisfy RenderedPromptProtocol."""
    assert not isinstance({"system": "x", "user": "y"}, RenderedPromptProtocol)


def test_should_reject_list_as_rendered_prompt():
    """A messages list does NOT satisfy RenderedPromptProtocol."""
    messages = [{"role": "user", "content": "hi"}]
    assert not isinstance(messages, RenderedPromptProtocol)


# ---------------------------------------------------------------------------
# Retry — only transient errors
# ---------------------------------------------------------------------------

def test_should_expose_transient_errors_tuple():
    """_TRANSIENT_ERRORS must not include generic Exception."""
    from aifw.service import _TRANSIENT_ERRORS
    assert Exception not in _TRANSIENT_ERRORS


# ---------------------------------------------------------------------------
# sync_completion_stream — queue-based true streaming
# ---------------------------------------------------------------------------

def _make_async_iter(items):
    """Return an async iterable from a list of items."""
    class _AsyncIter:
        def __init__(self):
            self._items = iter(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._items)
            except StopIteration:
                raise StopAsyncIteration

    return _AsyncIter()


def test_should_stream_chunks_via_queue():
    """sync_completion_stream yields chunks as they arrive (true streaming)."""
    from aifw.service import sync_completion_stream

    chunks_data = []
    for word in ["Hello", " ", "world"]:
        chunk = MagicMock()
        chunk.choices[0].delta.content = word
        chunks_data.append(chunk)

    config = {
        "model_string": "openai/gpt-4o",
        "api_key": "sk-test",
        "api_base": None,
        "max_tokens": 100,
        "temperature": 0.7,
    }

    async def _fake_acompletion(**kwargs):
        return _make_async_iter(chunks_data)

    with patch("aifw.service.get_model_config", new=AsyncMock(return_value=config)), \
         patch("litellm.acompletion", side_effect=_fake_acompletion):
        chunks = list(
            sync_completion_stream("story_writing", [{"role": "user", "content": "hi"}])
        )

    assert chunks == ["Hello", " ", "world"]


def test_should_propagate_exception_from_stream():
    """sync_completion_stream raises if the producer throws."""
    from aifw.service import sync_completion_stream

    async def _failing_acompletion(**kwargs):
        raise RuntimeError("LLM exploded")

    config = {
        "model_string": "openai/gpt-4o",
        "api_key": "sk-test",
        "api_base": None,
        "max_tokens": 100,
        "temperature": 0.7,
    }

    with patch("aifw.service.get_model_config", new=AsyncMock(return_value=config)), \
         patch("litellm.acompletion", side_effect=_failing_acompletion):
        with pytest.raises(RuntimeError, match="LLM exploded"):
            list(
                sync_completion_stream("story_writing", [{"role": "user", "content": "hi"}])
            )


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
        result = await completion(
            "story_writing", [{"role": "user", "content": "Write a story"}]
        )
        assert result.success is True
        assert result.content == "Hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
