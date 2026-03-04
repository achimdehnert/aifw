"""Tests for AIActionType._budget_exceeded() TTL cache (Issue #5)."""

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.django_db
def test_should_return_false_when_no_budget_set(db):
    """_budget_exceeded() returns False immediately when budget_per_day is None."""
    from aifw.models import AIActionType

    action = AIActionType(code="test_no_budget", name="Test", budget_per_day=None)
    assert action._budget_exceeded() is False


@pytest.mark.django_db
def test_should_query_db_on_first_call(db):
    """_budget_exceeded() performs DB query on cache miss."""
    from aifw.models import AIActionType, _budget_cache

    _budget_cache.clear()

    action = AIActionType(code="budget_test_fresh", name="Test", budget_per_day=Decimal("1.00"))

    with patch("aifw.models.AIUsageLog.objects") as mock_mgr:
        mock_mgr.filter.return_value.aggregate.return_value = {"total": 0}
        result = action._budget_exceeded()

    assert result is False
    mock_mgr.filter.assert_called_once()


@pytest.mark.django_db
def test_should_use_cache_on_second_call(db):
    """_budget_exceeded() does NOT query DB again within TTL window."""
    from aifw.models import AIActionType, _budget_cache

    _budget_cache.clear()

    action = AIActionType(code="budget_cached", name="Test", budget_per_day=Decimal("1.00"))

    call_count = 0

    def _mock_aggregate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"total": 0}

    with patch("aifw.models.AIUsageLog.objects") as mock_mgr:
        mock_mgr.filter.return_value.aggregate.side_effect = _mock_aggregate
        action._budget_exceeded()  # first call — DB hit
        action._budget_exceeded()  # second call — cache hit
        action._budget_exceeded()  # third call — cache hit

    assert call_count == 1  # only 1 DB query despite 3 calls


@pytest.mark.django_db
def test_should_requery_after_ttl_expires(db):
    """_budget_exceeded() re-queries DB after TTL expires."""
    from aifw.models import AIActionType, _budget_cache

    _budget_cache.clear()

    action = AIActionType(code="budget_ttl", name="Test", budget_per_day=Decimal("1.00"))

    call_count = 0

    def _mock_aggregate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"total": 0}

    with patch("aifw.models.AIUsageLog.objects") as mock_mgr:
        mock_mgr.filter.return_value.aggregate.side_effect = _mock_aggregate
        with patch("aifw.models._BUDGET_TTL", 0):  # TTL=0 means always expired
            action._budget_exceeded()  # DB hit
            action._budget_exceeded()  # TTL expired — DB hit again

    assert call_count == 2


@pytest.mark.django_db
def test_should_return_true_when_budget_exceeded(db):
    """_budget_exceeded() returns True when today's spend >= budget."""
    from aifw.models import AIActionType, _budget_cache

    _budget_cache.clear()

    action = AIActionType(code="budget_over", name="Test", budget_per_day=Decimal("5.00"))

    with patch("aifw.models.AIUsageLog.objects") as mock_mgr:
        mock_mgr.filter.return_value.aggregate.return_value = {"total": Decimal("5.50")}
        result = action._budget_exceeded()

    assert result is True


@pytest.mark.django_db
def test_should_invalidate_budget_cache_for_specific_code(db):
    """_invalidate_budget_cache(code) removes only that code from cache."""
    from aifw.models import _budget_cache, _invalidate_budget_cache

    _budget_cache["action_a"] = (False, time.monotonic())
    _budget_cache["action_b"] = (True, time.monotonic())

    _invalidate_budget_cache("action_a")

    assert "action_a" not in _budget_cache
    assert "action_b" in _budget_cache


@pytest.mark.django_db
def test_should_invalidate_all_budget_cache_entries(db):
    """_invalidate_budget_cache() with no args clears entire cache."""
    from aifw.models import _budget_cache, _invalidate_budget_cache

    _budget_cache["action_x"] = (False, time.monotonic())
    _budget_cache["action_y"] = (True, time.monotonic())

    _invalidate_budget_cache()

    assert len(_budget_cache) == 0
