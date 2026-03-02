"""Tests for aifw.service — mocked LiteLLM, no real API calls."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aifw.schema import LLMResult, RenderedPromptProtocol
from aifw.service import _build_model_string, _get_api_key, _parse_tool_calls


def test_build_model_string_openai():
    assert _build_model_string("openai", "gpt-4o") == "gpt-4o"


def test_build_model_string_anthropic():
    assert (
        _build_model_string("anthropic", "claude-3-5-sonnet")
        == "anthropic/claude-3-5-sonnet"
    )


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
        result = await completion(
            "unknown_action", [{"role": "user", "content": "hi"}]
        )
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

def test_should_stream_chunks_via_queue():
    """sync_completion_stream yields chunks as they arrive (true streaming)."""
    from aifw.service import sync_completion_stream

    async def _fake_acompletion(**kwargs):
        class FakeChunk:
            def __init__(self, text):
                self.choices = [MagicMock(delta=MagicMock(content=text))]

        async def _iter():
            for word in ["Hello", " ", "world"]:
                yield FakeChunk(word)

        return _iter()

    config = {
        "model_string": "openai/gpt-4o",
        "api_key": "sk-test",
        "api_base": None,
        "max_tokens": 100,
        "temperature": 0.7,
    }

    with patch("aifw.service.get_model_config", new=AsyncMock(return_value=config)), \
         patch("litellm.acompletion", side_effect=_fake_acompletion):
        chunks = list(
            sync_completion_stream(
                "story_writing", [{"role": "user", "content": "hi"}]
            )
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
                sync_completion_stream(
                    "story_writing", [{"role": "user", "content": "hi"}]
                )
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

    config = {
        "model_string": "anthropic/claude-3-5-sonnet-20241022",
        "api_key": "sk-test",
        "api_base": None,
        "max_tokens": 2000,
        "temperature": 0.7,
        "action_id": 1,
        "model_id": 1,
        "provider_name": "anthropic",
        "model_name": "claude-3-5-sonnet-20241022",
    }
    with patch("aifw.service.get_model_config", new=AsyncMock(return_value=config)), \
         patch("aifw.service._log_usage", new=AsyncMock()), \
         patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await completion(
            "story_writing", [{"role": "user", "content": "Write a story"}]
        )
        assert result.success is True
        assert result.content == "Hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5


# ---------------------------------------------------------------------------
# 0.5.0 — tenant_id / object_id / metadata propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_pass_tenant_id_to_log_usage():
    """completion() forwards tenant_id to _log_usage."""
    import uuid
    from aifw.service import completion

    tenant = uuid.uuid4()
    log_usage_calls = []

    async def _capture_log_usage(
        config, result, user=None, tenant_id=None, object_id="", metadata=None
    ):
        log_usage_calls.append({
            "tenant_id": tenant_id,
            "object_id": object_id,
            "metadata": metadata,
        })

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].finish_reason = "stop"
    mock_response.model = "gpt-4o"
    mock_response.usage.prompt_tokens = 5
    mock_response.usage.completion_tokens = 3

    config = {
        "model_string": "gpt-4o",
        "api_key": "sk-test",
        "api_base": None,
        "max_tokens": 100,
        "temperature": 0.7,
        "action_id": 1,
        "model_id": 1,
        "provider_name": "openai",
        "model_name": "gpt-4o",
    }
    with patch("aifw.service.get_model_config", new=AsyncMock(return_value=config)), \
         patch("aifw.service._log_usage", side_effect=_capture_log_usage), \
         patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        await completion(
            "story_writing",
            [{"role": "user", "content": "hi"}],
            tenant_id=tenant,
            object_id="story-42",
            metadata={"source": "test"},
        )

    assert len(log_usage_calls) == 1
    assert log_usage_calls[0]["tenant_id"] == tenant
    assert log_usage_calls[0]["object_id"] == "story-42"
    assert log_usage_calls[0]["metadata"] == {"source": "test"}


@pytest.mark.asyncio
async def test_should_accept_string_tenant_id():
    """completion() accepts tenant_id as string."""
    from aifw.service import completion

    log_usage_calls = []

    async def _capture_log_usage(
        config, result, user=None, tenant_id=None, object_id="", metadata=None
    ):
        log_usage_calls.append({"tenant_id": tenant_id})

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].finish_reason = "stop"
    mock_response.model = "gpt-4o"
    mock_response.usage.prompt_tokens = 5
    mock_response.usage.completion_tokens = 3

    config = {
        "model_string": "gpt-4o",
        "api_key": "sk-test",
        "api_base": None,
        "max_tokens": 100,
        "temperature": 0.7,
        "action_id": 1,
        "model_id": 1,
        "provider_name": "openai",
        "model_name": "gpt-4o",
    }
    with patch("aifw.service.get_model_config", new=AsyncMock(return_value=config)), \
         patch("aifw.service._log_usage", side_effect=_capture_log_usage), \
         patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        await completion(
            "story_writing",
            [{"role": "user", "content": "hi"}],
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
        )

    assert len(log_usage_calls) == 1
    assert log_usage_calls[0]["tenant_id"] == "550e8400-e29b-41d4-a716-446655440000"


# ---------------------------------------------------------------------------
# 0.5.0 — sync_completion_with_fallback
# ---------------------------------------------------------------------------

def test_should_return_result_from_sync_completion_with_fallback():
    """sync_completion_with_fallback() returns LLMResult on success."""
    from aifw.service import sync_completion_with_fallback

    mock_result = LLMResult(success=True, content="Fallback works", model="gpt-4o")

    with patch(
        "aifw.service.completion_with_fallback",
        new=AsyncMock(return_value=mock_result),
    ):
        result = sync_completion_with_fallback(
            "story_writing",
            [{"role": "user", "content": "hi"}],
        )

    assert result.success is True
    assert result.content == "Fallback works"


def test_should_propagate_tenant_id_through_sync_fallback():
    """sync_completion_with_fallback() passes tenant_id to completion_with_fallback."""
    import uuid
    from aifw.service import sync_completion_with_fallback

    captured = {}

    async def _fake_fallback(action_code, messages, **kwargs):
        captured.update(kwargs)
        return LLMResult(success=True, content="ok")

    tenant = uuid.uuid4()
    with patch("aifw.service.completion_with_fallback", side_effect=_fake_fallback):
        sync_completion_with_fallback(
            "story_writing",
            [{"role": "user", "content": "hi"}],
            tenant_id=tenant,
            object_id="obj-1",
        )

    assert captured.get("tenant_id") == tenant
    assert captured.get("object_id") == "obj-1"


# ---------------------------------------------------------------------------
# 0.5.0 — check_action_code
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_should_return_true_for_existing_action_code():
    """check_action_code() returns True when AIActionType exists."""
    from aifw.models import AIActionType
    from aifw.service import check_action_code

    AIActionType.objects.create(
        code="test_action",
        name="Test Action",
        is_active=True,
        max_tokens=500,
        temperature=0.7,
    )

    assert check_action_code("test_action") is True


@pytest.mark.django_db
def test_should_return_false_for_missing_action_code():
    """check_action_code() returns False when action code not in DB."""
    from aifw.service import check_action_code

    assert check_action_code("nonexistent_action_xyz") is False
