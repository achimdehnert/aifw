"""
Integration tests for _log_usage — verifies that tenant_id, object_id,
and metadata are correctly persisted to AIUsageLog in the database.

These tests call _log_usage directly (not mocked) to cover the full
DB write path introduced in migration 0003 / aifw 0.5.0.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aifw.models import AIActionType, AIUsageLog, LLMModel, LLMProvider
from aifw.schema import LLMResult


@pytest.fixture
def provider(db):
    return LLMProvider.objects.create(
        name="openai",
        display_name="OpenAI",
        api_key_env_var="OPENAI_API_KEY",
    )


@pytest.fixture
def model(provider):
    return LLMModel.objects.create(
        provider=provider,
        name="gpt-4o-mini",
        display_name="GPT-4o Mini",
        max_tokens=4096,
        input_cost_per_million=0.15,
        output_cost_per_million=0.60,
        is_default=True,
    )


@pytest.fixture
def action(model):
    return AIActionType.objects.create(
        code="test_action",
        name="Test Action",
        default_model=model,
        max_tokens=1000,
        temperature=0.5,
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
def success_result():
    return LLMResult(
        success=True,
        content="Generated text",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=50,
        latency_ms=250,
    )


# ---------------------------------------------------------------------------
# _log_usage DB write tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_write_tenant_id_to_usage_log(config, success_result):
    """_log_usage persists tenant_id to AIUsageLog."""
    from aifw.service import _log_usage

    tenant = uuid.uuid4()
    await _log_usage(config, success_result, tenant_id=tenant)

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.tenant_id == tenant


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_write_object_id_to_usage_log(config, success_result):
    """_log_usage persists object_id to AIUsageLog."""
    from aifw.service import _log_usage

    await _log_usage(config, success_result, object_id="chapter:42")

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.object_id == "chapter:42"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_write_metadata_to_usage_log(config, success_result):
    """_log_usage persists metadata dict to AIUsageLog."""
    from aifw.service import _log_usage

    meta = {"pipeline": "enrich", "prompt_version": "v3"}
    await _log_usage(config, success_result, metadata=meta)

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.metadata["pipeline"] == "enrich"
    assert log.metadata["prompt_version"] == "v3"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_write_all_three_fields_together(config, success_result):
    """_log_usage persists tenant_id + object_id + metadata in a single call."""
    from aifw.service import _log_usage

    tenant = uuid.uuid4()
    await _log_usage(
        config,
        success_result,
        tenant_id=tenant,
        object_id="story:99",
        metadata={"source": "test", "version": 1},
    )

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.tenant_id == tenant
    assert log.object_id == "story:99"
    assert log.metadata["source"] == "test"
    assert log.metadata["version"] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_default_null_when_not_provided(config, success_result):
    """_log_usage stores null/empty defaults when fields are not passed."""
    from aifw.service import _log_usage

    await _log_usage(config, success_result)

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.tenant_id is None
    assert log.object_id == ""
    assert log.metadata == {}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_write_failed_result_with_tenant_id(config):
    """_log_usage writes failed LLM result with tenant_id correctly."""
    from aifw.service import _log_usage

    failed = LLMResult(success=False, error="timeout", model="gpt-4o-mini")
    tenant = uuid.uuid4()

    await _log_usage(config, failed, tenant_id=tenant, object_id="job:7")

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.success is False
    assert log.tenant_id == tenant
    assert log.object_id == "job:7"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_accept_string_uuid_as_tenant_id(config, success_result):
    """_log_usage accepts tenant_id as string UUID (auto-coerced or stored as-is)."""
    from aifw.service import _log_usage

    tenant_str = "550e8400-e29b-41d4-a716-446655440000"
    await _log_usage(config, success_result, tenant_id=tenant_str)

    log = await AIUsageLog.objects.alatest("created_at")
    assert log.tenant_id is not None
    assert str(log.tenant_id) == tenant_str
