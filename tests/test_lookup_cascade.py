"""Tests for _lookup_cascade() — ADR-097 Acceptance Criteria F-01..F-13.

All tests use pytest-django with @pytest.mark.django_db.
No real LLM calls — DB only.
"""
import pytest

from aifw.exceptions import ConfigurationError


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def provider(db):
    from aifw.models import LLMProvider
    return LLMProvider.objects.create(
        name="openai",
        api_key_env_var="OPENAI_API_KEY",
    )


@pytest.fixture()
def model(provider):
    from aifw.models import LLMModel
    return LLMModel.objects.create(
        name="gpt-4o",
        provider=provider,
        is_active=True,
    )


def _action(code, model, quality_level=None, priority=None, is_active=True):
    """Helper: create an AIActionType row."""
    from aifw.models import AIActionType
    return AIActionType.objects.create(
        code=code,
        name=f"{code} ql={quality_level} prio={priority}",
        default_model=model,
        quality_level=quality_level,
        priority=priority,
        is_active=is_active,
        max_tokens=500,
        temperature=0.7,
    )


# ── F-01: Exact match (ql + prio) ─────────────────────────────────────────────

@pytest.mark.django_db
def test_should_return_exact_match_when_both_ql_and_priority_match(model):
    """F-01: Exact (ql=5, prio=quality) row returned when both params set."""
    from aifw.service import _lookup_cascade

    _action("write", model, quality_level=None, priority=None)   # catch-all
    _action("write", model, quality_level=5, priority=None)       # ql-only
    exact = _action("write", model, quality_level=5, priority="quality")

    result = _lookup_cascade("write", quality_level=5, priority="quality")
    assert result.pk == exact.pk


# ── F-02: ql-only fallback ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_should_fall_back_to_ql_only_when_no_exact_match(model):
    """F-02: ql-only row used when prio has no exact match."""
    from aifw.service import _lookup_cascade

    _action("write", model, quality_level=None, priority=None)   # catch-all
    ql_only = _action("write", model, quality_level=5, priority=None)

    result = _lookup_cascade("write", quality_level=5, priority="quality")
    assert result.pk == ql_only.pk


# ── F-03: prio-only fallback ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_should_fall_back_to_prio_only_when_no_ql_match(model):
    """F-03: prio-only row used when quality_level has no match."""
    from aifw.service import _lookup_cascade

    _action("write", model, quality_level=None, priority=None)   # catch-all
    prio_only = _action("write", model, quality_level=None, priority="fast")

    result = _lookup_cascade("write", quality_level=5, priority="fast")
    assert result.pk == prio_only.pk


# ── F-04: catch-all fallback ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_should_fall_back_to_catch_all_when_no_specific_match(model):
    """F-04: catch-all (ql=NULL, prio=NULL) used as last resort."""
    from aifw.service import _lookup_cascade

    catchall = _action("write", model, quality_level=None, priority=None)

    result = _lookup_cascade("write", quality_level=8, priority="balanced")
    assert result.pk == catchall.pk


# ── F-05: raises ConfigurationError when no row at all ───────────────────────

@pytest.mark.django_db
def test_should_raise_configuration_error_when_no_row_exists(model):
    """F-05: ConfigurationError raised if no row for code at any step."""
    from aifw.service import _lookup_cascade

    with pytest.raises(ConfigurationError, match="no_such_action"):
        _lookup_cascade("no_such_action", quality_level=None, priority=None)


# ── F-06: inactive rows are ignored ──────────────────────────────────────────

@pytest.mark.django_db
def test_should_ignore_inactive_rows(model):
    """F-06: is_active=False rows must not be returned."""
    from aifw.service import _lookup_cascade

    _action("write", model, quality_level=None, priority=None, is_active=False)

    with pytest.raises(ConfigurationError):
        _lookup_cascade("write", quality_level=None, priority=None)


# ── F-07: step-1 skipped when quality_level is None ──────────────────────────

@pytest.mark.django_db
def test_should_skip_step1_when_quality_level_is_none(model):
    """F-07: step 1 (exact) skipped when quality_level=None."""
    from aifw.service import _lookup_cascade

    catchall = _action("write", model, quality_level=None, priority=None)
    prio_only = _action("write", model, quality_level=None, priority="quality")

    # Without ql, step1 is impossible — step3 (prio-only) should match
    result = _lookup_cascade("write", quality_level=None, priority="quality")
    assert result.pk == prio_only.pk


# ── F-08: step-1 skipped when priority is None ───────────────────────────────

@pytest.mark.django_db
def test_should_skip_step1_when_priority_is_none(model):
    """F-08: step 1 (exact) skipped when priority=None."""
    from aifw.service import _lookup_cascade

    _action("write", model, quality_level=None, priority=None)  # catch-all
    ql_only = _action("write", model, quality_level=3, priority=None)

    result = _lookup_cascade("write", quality_level=3, priority=None)
    assert result.pk == ql_only.pk


# ── F-09: step-3 skipped when priority is None ───────────────────────────────

@pytest.mark.django_db
def test_should_skip_step3_when_priority_is_none(model):
    """F-09: prio-only step skipped when priority=None, falls to catch-all."""
    from aifw.service import _lookup_cascade

    catchall = _action("write", model, quality_level=None, priority=None)
    _action("write", model, quality_level=None, priority="fast")  # must not match

    result = _lookup_cascade("write", quality_level=None, priority=None)
    assert result.pk == catchall.pk


# ── F-10: catch-all requires no-ql AND no-prio ───────────────────────────────

@pytest.mark.django_db
def test_should_not_use_row_with_ql_set_as_catch_all(model):
    """F-10: A row with quality_level set must not match as catch-all."""
    from aifw.service import _lookup_cascade

    _action("write", model, quality_level=5, priority=None)  # not a catch-all

    with pytest.raises(ConfigurationError):
        _lookup_cascade("write", quality_level=None, priority=None)


# ── F-11: multiple codes are isolated ────────────────────────────────────────

@pytest.mark.django_db
def test_should_isolate_rows_by_code(model):
    """F-11: Rows for code='other' must not match code='write'."""
    from aifw.service import _lookup_cascade

    _action("other", model, quality_level=None, priority=None)  # different code

    with pytest.raises(ConfigurationError, match="write"):
        _lookup_cascade("write", quality_level=None, priority=None)


# ── F-12: exact match preferred over ql-only ─────────────────────────────────

@pytest.mark.django_db
def test_should_prefer_exact_over_ql_only(model):
    """F-12: exact (ql+prio) wins over ql-only."""
    from aifw.service import _lookup_cascade

    ql_only = _action("write", model, quality_level=5, priority=None)
    exact = _action("write", model, quality_level=5, priority="balanced")
    _action("write", model, quality_level=None, priority=None)

    result = _lookup_cascade("write", quality_level=5, priority="balanced")
    assert result.pk == exact.pk
    assert result.pk != ql_only.pk


# ── F-13: ql-only preferred over prio-only ───────────────────────────────────

@pytest.mark.django_db
def test_should_prefer_ql_only_over_prio_only(model):
    """F-13: ql-only (step 2) wins over prio-only (step 3)."""
    from aifw.service import _lookup_cascade

    prio_only = _action("write", model, quality_level=None, priority="fast")
    ql_only = _action("write", model, quality_level=5, priority=None)
    _action("write", model, quality_level=None, priority=None)

    result = _lookup_cascade("write", quality_level=5, priority="fast")
    assert result.pk == ql_only.pk
    assert result.pk != prio_only.pk
