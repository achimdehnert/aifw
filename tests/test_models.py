"""Tests for aifw Django models."""

import pytest

from aifw.models import AIActionType, AIUsageLog, LLMModel, LLMProvider


@pytest.fixture
def provider(db):
    return LLMProvider.objects.create(
        name="anthropic",
        display_name="Anthropic",
        api_key_env_var="ANTHROPIC_API_KEY",
    )


@pytest.fixture
def model(provider):
    return LLMModel.objects.create(
        provider=provider,
        name="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        max_tokens=8192,
        input_cost_per_million=3.0,
        output_cost_per_million=15.0,
        is_default=True,
    )


@pytest.fixture
def action_type(model):
    return AIActionType.objects.create(
        code="story_writing",
        name="Story Writing",
        default_model=model,
        max_tokens=2000,
        temperature=0.7,
    )


@pytest.mark.django_db
def test_provider_str(provider):
    assert str(provider) == "Anthropic"


@pytest.mark.django_db
def test_model_str(model):
    assert str(model) == "anthropic:claude-3-5-sonnet-20241022"


@pytest.mark.django_db
def test_action_type_get_model(action_type, model):
    assert action_type.get_model() == model


@pytest.mark.django_db
def test_action_type_fallback_when_default_inactive(action_type, model, provider):
    fallback = LLMModel.objects.create(
        provider=provider,
        name="claude-3-haiku-20240307",
        display_name="Claude 3 Haiku",
        max_tokens=4096,
    )
    action_type.fallback_model = fallback
    action_type.default_model.is_active = False
    action_type.default_model.save()
    action_type.save()
    assert action_type.get_model() == fallback


@pytest.mark.django_db
def test_usage_log_total_tokens(action_type, model):
    log = AIUsageLog.objects.create(
        action_type=action_type,
        model_used=model,
        input_tokens=500,
        output_tokens=200,
        latency_ms=1200,
        success=True,
    )
    assert log.total_tokens == 700


@pytest.mark.django_db
def test_usage_log_estimated_cost(action_type, model):
    log = AIUsageLog.objects.create(
        action_type=action_type,
        model_used=model,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        success=True,
    )
    assert float(log.estimated_cost) == pytest.approx(18.0)
