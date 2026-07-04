"""Seed command `init_aifw_config` — Groq-first policy, idempotency, cleanup."""

from io import StringIO

import pytest
from django.core.management import call_command

from aifw.models import AIActionType, LLMModel, LLMProvider


def _run_seed() -> str:
    out = StringIO()
    call_command("init_aifw_config", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_should_seed_groq_as_global_default():
    _run_seed()

    groq = LLMProvider.objects.get(name="groq")
    assert groq.api_key_env_var == "GROQ_API_KEY"
    model = LLMModel.objects.get(provider=groq, name="llama-3.3-70b-versatile")
    assert model.is_default is True
    assert model.is_active is True
    # Exactly one global default (Tier 1a, org policy llm-routing).
    assert LLMModel.objects.filter(is_default=True, is_active=True).count() == 1


@pytest.mark.django_db
def test_should_seed_cerebras_free_tier_model():
    _run_seed()

    cerebras = LLMProvider.objects.get(name="cerebras")
    assert LLMModel.objects.filter(provider=cerebras, name="gpt-oss-120b").exists()


@pytest.mark.django_db
def test_should_wire_nl2sql_action_groq_default_with_anthropic_fallback():
    _run_seed()

    action = AIActionType.objects.get(code="nl2sql", quality_level=None, priority=None)
    assert action.default_model.provider.name == "groq"
    assert action.default_model.name == "llama-3.3-70b-versatile"
    assert action.fallback_model.provider.name == "anthropic"
    assert action.fallback_model.name == "claude-haiku-4-5"
    assert action.prompt_template_key == "nl2sql.system"
    assert action.temperature == pytest.approx(0.05)


@pytest.mark.django_db
def test_should_not_seed_dead_model_ids():
    """Retired IDs from earlier seeds must be gone from the seed catalog."""
    _run_seed()

    dead = [
        "claude-3-5-sonnet-20241022",
        "claude-3-haiku-20240307",
        "gpt-4o",
        "gpt-4o-mini",
        "gemini/gemini-1.5-pro",
    ]
    assert not LLMModel.objects.filter(name__in=dead).exists()


@pytest.mark.django_db
def test_should_deactivate_legacy_dead_models_in_existing_installs():
    provider, _ = LLMProvider.objects.get_or_create(
        name="anthropic", defaults={"display_name": "Anthropic"}
    )
    legacy = LLMModel.objects.create(
        provider=provider,
        name="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        is_default=True,
    )

    _run_seed()

    legacy.refresh_from_db()
    assert legacy.is_active is False
    assert legacy.is_default is False


@pytest.mark.django_db
def test_should_be_idempotent_on_second_run():
    _run_seed()
    counts = (
        LLMProvider.objects.count(),
        LLMModel.objects.count(),
        AIActionType.objects.count(),
    )

    out = _run_seed()

    assert (
        LLMProvider.objects.count(),
        LLMModel.objects.count(),
        AIActionType.objects.count(),
    ) == counts
    assert "Created" not in out


@pytest.mark.django_db
def test_should_seed_promptfw_template_when_promptfw_installed():
    pytest.importorskip("promptfw.contrib.django.models")
    from promptfw.contrib.django.models import PromptTemplate

    _run_seed()

    tpl = PromptTemplate.objects.get(action_code="nl2sql.system", version=1)
    assert "{{ blocked_tables }}" in tpl.system_template
    assert "{{ max_rows }}" in tpl.system_template
    assert "{{ schema_xml }}" in tpl.system_template
    assert tpl.user_template == "{{ question }}"
