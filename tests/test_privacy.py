"""
Tests for privacy_mode pre-write transforms (issue #8).

Covers the three built-in modes end-to-end through _log_usage (the real DB write
path), the custom-hook registration mechanism, fail-closed behaviour, and the
k-anonymity aggregation helper.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from aifw.constants import PrivacyMode
from aifw.models import AIActionType, AIUsageLog, LLMModel, LLMProvider
from aifw.privacy import (
    AnonymousHook,
    PrivacyHook,
    PseudonymousHook,
    apply_privacy,
    get_privacy_hook,
)
from aifw.schema import LLMResult

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider(db):
    return LLMProvider.objects.create(
        name="openai", display_name="OpenAI", api_key_env_var="OPENAI_API_KEY"
    )


@pytest.fixture
def model(provider):
    return LLMModel.objects.create(
        provider=provider,
        name="gpt-4o-mini",
        display_name="GPT-4o Mini",
        input_cost_per_million=0.15,
        output_cost_per_million=0.60,
        is_default=True,
    )


@pytest.fixture
def action(model):
    return AIActionType.objects.create(
        code="nl2sql", name="NL2SQL", default_model=model, max_tokens=1000
    )


@pytest.fixture
def config(action, model, provider):
    return {
        "model_string": "gpt-4o-mini",
        "api_key": "sk-test",
        "api_base": None,
        "max_tokens": 1000,
        "temperature": 0.5,
        "action_id": action.id,
        "model_id": model.id,
        "provider_name": provider.name,
        "model_name": model.name,
    }


@pytest.fixture
def result():
    return LLMResult(
        success=True,
        content="ok",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=50,
        latency_ms=200,
    )


@pytest.fixture
def user(db):
    return User.objects.create(username="alice")


# ---------------------------------------------------------------------------
# Constants / resolution
# ---------------------------------------------------------------------------


def test_should_validate_known_privacy_modes():
    assert PrivacyMode.is_valid("full")
    assert PrivacyMode.is_valid("pseudonymous")
    assert PrivacyMode.is_valid("anonymous")
    assert not PrivacyMode.is_valid("bogus")
    assert not PrivacyMode.is_valid(None)


def test_should_default_to_full_hook_when_unset(settings):
    # No AIFW_PRIVACY_MODE configured → full (identity) hook.
    hook = get_privacy_hook()
    assert hook.mode == PrivacyMode.FULL
    assert isinstance(hook, PrivacyHook)


@override_settings(AIFW_PRIVACY_MODE="pseudonymous")
def test_should_resolve_pseudonymous_hook():
    assert isinstance(get_privacy_hook(), PseudonymousHook)


@override_settings(AIFW_PRIVACY_MODE="anonymous")
def test_should_resolve_anonymous_hook():
    assert isinstance(get_privacy_hook(), AnonymousHook)


@override_settings(AIFW_PRIVACY_MODE="garbage")
def test_should_fall_back_to_full_on_invalid_mode():
    assert get_privacy_hook().mode == PrivacyMode.FULL


# ---------------------------------------------------------------------------
# apply_privacy() — unit level
# ---------------------------------------------------------------------------


@override_settings(AIFW_PRIVACY_MODE="full")
def test_should_pass_payload_through_unchanged_in_full_mode(user):
    payload = apply_privacy({"user": user, "metadata": {"nl_question": "how many orders?"}})
    assert payload["user"] is user
    assert payload["metadata"]["nl_question"] == "how many orders?"
    assert payload["privacy_mode"] == "full"


@override_settings(AIFW_PRIVACY_MODE="pseudonymous", AIFW_PRIVACY_HMAC_SECRET="s3cr3t")
def test_should_pseudonymise_user_and_classify_question(user):
    payload = apply_privacy({"user": user, "metadata": {"nl_question": "how many orders?"}})
    assert payload["user"] is None
    assert "nl_question" not in payload["metadata"]
    assert payload["metadata"]["topic"] == "unclassified"
    assert len(payload["metadata"]["user_hash"]) == 64  # sha256 hexdigest
    assert payload["privacy_mode"] == "pseudonymous"


@override_settings(AIFW_PRIVACY_MODE="pseudonymous", AIFW_PRIVACY_HMAC_SECRET="s3cr3t")
def test_should_produce_stable_user_hash(user):
    h1 = apply_privacy({"user": user, "metadata": {}})["metadata"]["user_hash"]
    h2 = apply_privacy({"user": user, "metadata": {}})["metadata"]["user_hash"]
    assert h1 == h2


@override_settings(AIFW_PRIVACY_MODE="anonymous")
def test_should_strip_all_user_trace_in_anonymous_mode(user):
    payload = apply_privacy({"user": user, "metadata": {"nl_question": "secret", "extra": 1}})
    assert payload["user"] is None
    assert list(payload["metadata"].keys()) == ["day_bucket"]
    assert payload["privacy_mode"] == "anonymous"


# ---------------------------------------------------------------------------
# Custom hook registration
# ---------------------------------------------------------------------------


class _ShoutHook(PrivacyHook):
    mode = "pseudonymous"

    def transform(self, payload):
        payload["user"] = None
        payload["metadata"] = {"custom": "applied"}
        return payload


_shout_instance = _ShoutHook()


@override_settings(AIFW_PRIVACY_HOOK="tests.test_privacy:_ShoutHook")
def test_should_load_custom_hook_class_by_dotted_path(user):
    payload = apply_privacy({"user": user, "metadata": {"nl_question": "x"}})
    assert payload["metadata"] == {"custom": "applied"}
    assert payload["user"] is None


@override_settings(AIFW_PRIVACY_HOOK="tests.test_privacy:_shout_instance")
def test_should_load_custom_hook_instance_by_dotted_path(user):
    payload = apply_privacy({"user": user, "metadata": {}})
    assert payload["metadata"] == {"custom": "applied"}


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


class _BrokenHook(PrivacyHook):
    mode = "pseudonymous"

    def transform(self, payload):
        raise RuntimeError("classifier exploded")


@override_settings(
    AIFW_PRIVACY_HOOK="tests.test_privacy:_BrokenHook",
    AIFW_PRIVACY_MODE="pseudonymous",
)
def test_should_fail_closed_and_scrub_pii_when_hook_raises(user):
    payload = apply_privacy({"user": user, "metadata": {"nl_question": "leak me"}})
    assert payload["user"] is None
    assert payload["metadata"] == {"privacy_error": True}
    assert payload["privacy_mode"] == "pseudonymous"


# ---------------------------------------------------------------------------
# E2E through _log_usage (real DB write)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@override_settings(AIFW_PRIVACY_MODE="pseudonymous", AIFW_PRIVACY_HMAC_SECRET="k")
async def test_should_write_pseudonymous_row(config, result, user):
    from aifw.service import _log_usage

    await _log_usage(
        config,
        result,
        user=user,
        metadata={"nl_question": "how many late orders?"},
    )

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.user_id is None
    assert log.privacy_mode == "pseudonymous"
    assert "nl_question" not in log.metadata
    assert log.metadata["topic"] == "unclassified"
    assert log.metadata["user_hash"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@override_settings(AIFW_PRIVACY_MODE="anonymous")
async def test_should_write_anonymous_row(config, result, user):
    from aifw.service import _log_usage

    tenant = uuid.uuid4()
    await _log_usage(
        config,
        result,
        user=user,
        tenant_id=tenant,
        metadata={"nl_question": "secret"},
    )

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.user_id is None
    assert log.privacy_mode == "anonymous"
    assert log.tenant_id == tenant  # tenant survives anonymisation
    assert log.total_tokens == 150  # token counts survive
    assert list(log.metadata.keys()) == ["day_bucket"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_default_to_full_raw_row(config, result, user):
    from aifw.service import _log_usage

    await _log_usage(
        config,
        result,
        user=user,
        metadata={"nl_question": "how many orders?"},
    )

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.user_id == user.id
    assert log.privacy_mode == "full"
    assert log.metadata["nl_question"] == "how many orders?"


# ---------------------------------------------------------------------------
# k-anonymity helper
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_should_suppress_buckets_below_k(action, model):
    # 3 rows for ql=5, 1 row for ql=8 → with k=3 only the ql=5 bucket survives.
    for _ in range(3):
        AIUsageLog.objects.create(
            action_type=action,
            model_used=model,
            quality_level=5,
            input_tokens=10,
            output_tokens=5,
        )
    AIUsageLog.objects.create(
        action_type=action,
        model_used=model,
        quality_level=8,
        input_tokens=10,
        output_tokens=5,
    )

    buckets = list(AIUsageLog.objects.aggregate_with_k_anonymity("quality_level", k=3))
    assert len(buckets) == 1
    assert buckets[0]["quality_level"] == 5
    assert buckets[0]["entry_count"] == 3
    assert buckets[0]["total_tokens"] == 45
