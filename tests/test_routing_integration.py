"""Regression tests: quality-level / priority routing and retry are actually
wired into the completion path (not just the isolated _lookup_cascade).

Guards the 0.10.3 fix where completion()/*_stream() called the legacy
get_model_config(action_code) and silently ignored quality_level + priority.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aifw.service import _LOCAL_CACHE


@pytest.fixture(autouse=True)
def _clear_cache():
    """Process-local config cache must not leak model choices across tests."""
    _LOCAL_CACHE.clear()
    yield
    _LOCAL_CACHE.clear()


@pytest.fixture()
def provider(transactional_db):
    # transactional_db (committed rows) is required: completion() reads config
    # via sync_to_async, i.e. from a worker thread. Under the default atomic
    # test wrapper that read deadlocks on SQLite shared-cache ("table is locked").
    from aifw.models import LLMProvider
    return LLMProvider.objects.create(name="openai", api_key_env_var="OPENAI_API_KEY")


@pytest.fixture()
def models(provider):
    from aifw.models import LLMModel
    economy = LLMModel.objects.create(name="gpt-4o-mini", provider=provider, is_active=True)
    premium = LLMModel.objects.create(name="gpt-4o", provider=provider, is_active=True)
    return economy, premium


def _action(code, model, quality_level=None, priority=None):
    from aifw.models import AIActionType
    return AIActionType.objects.create(
        code=code,
        name=f"{code} ql={quality_level} prio={priority}",
        default_model=model,
        quality_level=quality_level,
        priority=priority,
        is_active=True,
        max_tokens=500,
        temperature=0.7,
    )


def _fake_response(content="ok"):
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock(message=message, finish_reason="stop")
    response = MagicMock(choices=[choice], model="captured")
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return response


# ── #1: routing actually reaches litellm ──────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_should_route_quality_level_to_premium_model(models):
    """completion(quality_level=8) must reach the ql=8 row's model, not catch-all."""
    economy, premium = models
    _action("story", economy, quality_level=None, priority=None)  # catch-all
    _action("story", premium, quality_level=8, priority=None)     # premium

    captured = {}

    async def _capture(**kwargs):
        captured["model"] = kwargs["model"]
        return _fake_response()

    from aifw.service import sync_completion

    with patch("litellm.acompletion", side_effect=_capture), \
         patch("aifw.service._log_usage", new=AsyncMock()):
        result = sync_completion(
            "story", [{"role": "user", "content": "hi"}], quality_level=8
        )

    assert result.success is True
    assert captured["model"] == "gpt-4o"  # premium row, NOT the catch-all gpt-4o-mini


@pytest.mark.django_db(transaction=True)
def test_should_fall_back_to_catch_all_without_quality_level(models):
    """completion() with no quality_level resolves the catch-all row's model."""
    economy, premium = models
    _action("story", economy, quality_level=None, priority=None)  # catch-all
    _action("story", premium, quality_level=8, priority=None)

    captured = {}

    async def _capture(**kwargs):
        captured["model"] = kwargs["model"]
        return _fake_response()

    from aifw.service import sync_completion

    with patch("litellm.acompletion", side_effect=_capture), \
         patch("aifw.service._log_usage", new=AsyncMock()):
        result = sync_completion("story", [{"role": "user", "content": "hi"}])

    assert result.success is True
    assert captured["model"] == "gpt-4o-mini"  # catch-all row


@pytest.mark.django_db(transaction=True)
def test_should_route_priority_to_matching_row(models):
    """completion(priority='quality') reaches the prio-specific row."""
    economy, premium = models
    _action("draft", economy, quality_level=None, priority=None)        # catch-all
    _action("draft", premium, quality_level=None, priority="quality")   # prio-only

    captured = {}

    async def _capture(**kwargs):
        captured["model"] = kwargs["model"]
        return _fake_response()

    from aifw.service import sync_completion

    with patch("litellm.acompletion", side_effect=_capture), \
         patch("aifw.service._log_usage", new=AsyncMock()):
        sync_completion("draft", [{"role": "user", "content": "hi"}], priority="quality")

    assert captured["model"] == "gpt-4o"


# ── #1b: invalidation flushes the completion-config cache ─────────────────────

def test_should_invalidate_completion_config_cache_for_code():
    """invalidate_action_cache(code) must flush 'aifw:cfg:' completion keys,
    not only the 'aifw:action:' ActionConfig keys."""
    from aifw.service import (
        _completion_cache_key,
        _LOCAL_CACHE,
        _local_set,
        invalidate_action_cache,
    )

    key = _completion_cache_key("story", 8, "quality")
    _local_set(key, {"model_string": "gpt-4o"})
    assert key in _LOCAL_CACHE

    invalidate_action_cache("story")
    assert key not in _LOCAL_CACHE


# ── #2: retry is applied to the completion call ───────────────────────────────

@pytest.mark.asyncio
async def test_should_retry_transient_error_then_succeed():
    """_acompletion_with_retry retries transient errors instead of failing once."""
    from aifw.service import _RETRY_ENABLED, _TRANSIENT_ERRORS, _acompletion_with_retry

    if not _RETRY_ENABLED:
        pytest.skip("tenacity not installed — retry layer disabled")

    exc_cls = _TRANSIENT_ERRORS[0]
    try:
        transient = exc_cls(message="rate limited", llm_provider="openai", model="gpt-4o")
    except TypeError:
        transient = exc_cls("rate limited")

    calls = {"n": 0}

    async def _flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise transient
        return _fake_response()

    # Skip tenacity's exponential backoff sleeps to keep the test fast.
    with patch("tenacity.nap.sleep", lambda *_a, **_k: None), \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch("litellm.acompletion", side_effect=_flaky):
        response = await _acompletion_with_retry(model="gpt-4o", messages=[])

    assert calls["n"] == 3  # 2 transient failures, succeeded on the 3rd attempt
    assert response.model == "captured"


@pytest.mark.asyncio
async def test_should_not_retry_non_transient_error():
    """Non-transient errors propagate immediately (single attempt)."""
    from aifw.service import _RETRY_ENABLED, _acompletion_with_retry

    if not _RETRY_ENABLED:
        pytest.skip("tenacity not installed — retry layer disabled")

    calls = {"n": 0}

    async def _boom(**kwargs):
        calls["n"] += 1
        raise ValueError("non-transient")

    with patch("litellm.acompletion", side_effect=_boom):
        with pytest.raises(ValueError):
            await _acompletion_with_retry(model="gpt-4o", messages=[])

    assert calls["n"] == 1  # not retried
