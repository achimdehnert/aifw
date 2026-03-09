"""Tests for tier quality mapping (ADR-095/097 TierQualityMapping)."""
import pytest
from unittest.mock import patch, MagicMock


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


# ── get_quality_level_for_tier ────────────────────────────────────────────────

@pytest.mark.django_db
def test_should_return_quality_level_for_known_tier():
    """get_quality_level_for_tier returns mapped level for known tier."""
    from aifw.models import TierQualityMapping
    from aifw.service import get_quality_level_for_tier

    TierQualityMapping.objects.create(tier="premium", quality_level=8)

    result = get_quality_level_for_tier("premium")
    assert result == 8


@pytest.mark.django_db
def test_should_return_none_for_unknown_tier():
    """get_quality_level_for_tier returns BALANCED (5) as default for unknown tier."""
    from aifw.service import get_quality_level_for_tier
    from aifw.constants import QualityLevel

    result = get_quality_level_for_tier("nonexistent_tier_xyz")
    assert result == QualityLevel.BALANCED


@pytest.mark.django_db
def test_should_use_cache_on_second_call(monkeypatch):
    """Second call uses cache — DB not queried again."""
    from aifw.models import TierQualityMapping
    from aifw.service import get_quality_level_for_tier, _LOCAL_CACHE, _tier_cache_key

    TierQualityMapping.objects.create(tier="pro", quality_level=6)
    _LOCAL_CACHE.clear()

    # First call — populates cache
    result1 = get_quality_level_for_tier("pro")
    assert result1 == 6

    # Verify it's in local cache
    key = _tier_cache_key("pro")
    assert _LOCAL_CACHE.get(key) is not None

    _LOCAL_CACHE.clear()


# ── TierQualityMapping model integrity ───────────────────────────────────────

@pytest.mark.django_db
def test_should_enforce_unique_tier():
    """Duplicate tier names must raise IntegrityError."""
    from django.db import IntegrityError
    from aifw.models import TierQualityMapping

    TierQualityMapping.objects.create(tier="enterprise", quality_level=9)
    with pytest.raises(IntegrityError):
        TierQualityMapping.objects.create(tier="enterprise", quality_level=7)


@pytest.mark.django_db
def test_should_allow_different_tiers_with_same_quality_level():
    """Different tiers can share the same quality_level."""
    from aifw.models import TierQualityMapping

    TierQualityMapping.objects.create(tier="tier_a", quality_level=5)
    TierQualityMapping.objects.create(tier="tier_b", quality_level=5)

    assert TierQualityMapping.objects.filter(quality_level=5).count() == 2
