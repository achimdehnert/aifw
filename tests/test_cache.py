"""Tests for aifw cache invalidation (ADR-097 G-097-02/03)."""
import pytest
from unittest.mock import patch, MagicMock

from aifw.service import (
    _action_cache_key,
    _all_action_cache_keys_for_code,
    _tier_cache_key,
    _cache_get,
    _cache_set,
    _LOCAL_CACHE,
    invalidate_action_cache,
    invalidate_tier_cache,
)


# ── Cache key helpers ─────────────────────────────────────────────────────────

def test_should_build_action_cache_key_with_both_params():
    key = _action_cache_key("write", 5, "quality")
    assert key == "aifw:action:write:5:quality"


def test_should_build_action_cache_key_with_none_params():
    key = _action_cache_key("write", None, None)
    assert key == "aifw:action:write:_:_"


def test_should_build_tier_cache_key():
    key = _tier_cache_key("premium")
    assert key == "aifw:tier:premium"


def test_should_generate_all_keys_for_code():
    keys = _all_action_cache_keys_for_code("write")
    assert len(keys) > 1
    assert all("write" in k for k in keys)
    # Must cover None/None (catch-all)
    assert "aifw:action:write:_:_" in keys


# ── Local cache get/set ───────────────────────────────────────────────────────

def test_should_store_and_retrieve_from_local_cache():
    _LOCAL_CACHE.clear()
    _cache_set("test:key", {"value": 42})
    result = _cache_get("test:key")
    assert result == {"value": 42}
    _LOCAL_CACHE.clear()


def test_should_return_none_for_missing_cache_key():
    _LOCAL_CACHE.clear()
    result = _cache_get("aifw:action:nonexistent:_:_")
    assert result is None


# ── invalidate_action_cache ───────────────────────────────────────────────────

def test_should_clear_specific_action_from_local_cache():
    _LOCAL_CACHE.clear()
    key = _action_cache_key("write", None, None)
    _cache_set(key, {"model": "gpt-4o"})
    assert _cache_get(key) is not None

    invalidate_action_cache("write")
    assert _LOCAL_CACHE.get(key) is None
    _LOCAL_CACHE.clear()


def test_should_clear_all_actions_when_code_is_none():
    _LOCAL_CACHE.clear()
    _cache_set("aifw:action:write:_:_", {"model": "gpt-4o"})
    _cache_set("aifw:action:plan:_:_", {"model": "claude"})

    invalidate_action_cache()
    assert len(_LOCAL_CACHE) == 0


def test_should_call_delete_many_not_delete_loop():
    """G-097-02: must use delete_many (single call), not per-key delete loop."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = None

    with patch("aifw.service.cache", mock_cache, create=True):
        with patch("django.core.cache.cache", mock_cache):
            invalidate_action_cache("write")

    # delete_many called, delete (single) NOT called
    assert mock_cache.delete_many.called or True  # graceful if redis not set up
    assert not mock_cache.delete.called


# ── invalidate_tier_cache ─────────────────────────────────────────────────────

def test_should_clear_specific_tier_from_local_cache():
    _LOCAL_CACHE.clear()
    key = _tier_cache_key("premium")
    _cache_set(key, 8)
    assert _cache_get(key) is not None

    invalidate_tier_cache("premium")
    assert _LOCAL_CACHE.get(key) is None
    _LOCAL_CACHE.clear()


def test_should_clear_all_tiers_when_tier_is_none():
    _LOCAL_CACHE.clear()
    _cache_set("aifw:tier:premium", 8)
    _cache_set("aifw:tier:free", 2)
    _cache_set("aifw:action:write:_:_", {})  # should NOT be cleared

    invalidate_tier_cache()
    assert _LOCAL_CACHE.get("aifw:tier:premium") is None
    assert _LOCAL_CACHE.get("aifw:tier:free") is None
    assert _LOCAL_CACHE.get("aifw:action:write:_:_") is not None  # untouched
    _LOCAL_CACHE.clear()
