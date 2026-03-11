"""
Provider-agnostic LLM service via LiteLLM + DB-driven config.

New in 0.6.0 (ADR-095/097):
- get_action_config(code, quality_level, priority) — 4-step deterministic lookup
- _lookup_cascade() — exact → ql-only → prio-only → catch-all
- get_quality_level_for_tier() — DB-driven tier → quality_level mapping
- Hybrid 2-layer cache: process-local dict (30s) + Django cache framework (600s)
- invalidate_action_cache() / invalidate_tier_cache() replace invalidate_config_cache()
- sync_completion() / completion() extended with quality_level parameter

New in 0.5.0:
- tenant_id, object_id, metadata forwarded through completion()/sync_completion()
- sync_completion_with_fallback()
- check_action_code()

New in 0.4.0:
- Django signals for cache invalidation
- AIUsageLog.tenant_id / object_id / metadata
- sync_completion_stream with queue.Queue (true streaming)
- RenderedPromptProtocol replaces duck-typing
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import queue
import time
import threading
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import litellm
from asgiref.sync import sync_to_async

from aifw.constants import QualityLevel, VALID_PRIORITIES
from aifw.exceptions import ConfigurationError
from aifw.schema import LLMResult, RenderedPromptProtocol, ToolCall
from aifw.types import ActionConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True

# ---------------------------------------------------------------------------
# Hybrid 2-layer cache
# ---------------------------------------------------------------------------
# Layer 1: process-local dict (zero latency, no deps)
# Layer 2: Django cache framework (Redis if configured, otherwise LocMemCache)
#
# TTLs configurable via env vars:
#   AIFW_LOCAL_CACHE_TTL  — process-local TTL in seconds (default 30)
#   AIFW_CACHE_TTL        — shared cache TTL in seconds (default 600)
# ---------------------------------------------------------------------------

_LOCAL_CACHE: dict[str, tuple[Any, float]] = {}
_LOCAL_TTL: int = int(os.environ.get("AIFW_LOCAL_CACHE_TTL", "30"))
_SHARED_TTL: int = int(os.environ.get("AIFW_CACHE_TTL", "600"))

# Legacy alias — still read by existing code that sets AIFW_CONFIG_TTL
if "AIFW_CONFIG_TTL" in os.environ and "AIFW_LOCAL_CACHE_TTL" not in os.environ:
    _LOCAL_TTL = int(os.environ["AIFW_CONFIG_TTL"])


def _local_get(key: str) -> Any | None:
    entry = _LOCAL_CACHE.get(key)
    if entry and (time.monotonic() - entry[1]) < _LOCAL_TTL:
        return entry[0]
    return None


def _local_set(key: str, value: Any) -> None:
    _LOCAL_CACHE[key] = (value, time.monotonic())


def _shared_get(key: str) -> Any | None:
    try:
        from django.core.cache import cache
        return cache.get(key)
    except Exception:
        return None


def _shared_set(key: str, value: Any) -> None:
    try:
        from django.core.cache import cache
        cache.set(key, value, timeout=_SHARED_TTL)
    except Exception:
        pass  # graceful — local cache is sufficient


def _shared_delete_many(keys: list[str]) -> None:
    try:
        from django.core.cache import cache
        cache.delete_many(keys)
    except Exception:
        pass


def _cache_get(key: str) -> Any | None:
    """Check local then shared cache."""
    value = _local_get(key)
    if value is not None:
        return value
    value = _shared_get(key)
    if value is not None:
        _local_set(key, value)  # promote to local layer
    return value


def _cache_set(key: str, value: Any) -> None:
    """Write to both local and shared cache."""
    _local_set(key, value)
    _shared_set(key, value)


# ---------------------------------------------------------------------------
# Cache key helpers
# ---------------------------------------------------------------------------

def _action_cache_key(code: str, quality_level: int | None, priority: str | None) -> str:
    ql = str(quality_level) if quality_level is not None else "_"
    prio = priority if priority is not None else "_"
    return f"aifw:action:{code}:{ql}:{prio}"


def _all_action_cache_keys_for_code(code: str) -> list[str]:
    """Generate all possible cache keys for a given action code."""
    keys = []
    for ql in [None, *QualityLevel.ALL]:
        for prio in [None, *VALID_PRIORITIES]:
            keys.append(_action_cache_key(code, ql, prio))
    return keys


def _tier_cache_key(tier: str) -> str:
    return f"aifw:tier:{tier}"


# ---------------------------------------------------------------------------
# Cache invalidation (public API)
# ---------------------------------------------------------------------------

def invalidate_action_cache(action_code: str | None = None) -> None:
    """Invalidate action config cache.

    Pass action_code to clear only that code's entries.
    Pass None to clear all cached action configs.
    """
    if action_code:
        keys = _all_action_cache_keys_for_code(action_code)
        for k in keys:
            _LOCAL_CACHE.pop(k, None)
        _shared_delete_many(keys)
    else:
        _LOCAL_CACHE.clear()
        try:
            from django.core.cache import cache
            cache.clear()
        except Exception:
            pass


def invalidate_tier_cache(tier: str | None = None) -> None:
    """Invalidate tier quality mapping cache.

    Pass tier name to clear only that tier. Pass None to clear all tier caches.
    """
    if tier:
        key = _tier_cache_key(tier)
        _LOCAL_CACHE.pop(key, None)
        _shared_delete_many([key])
    else:
        # Clear all tier keys from local cache
        tier_keys = [k for k in _LOCAL_CACHE if k.startswith("aifw:tier:")]
        for k in tier_keys:
            _LOCAL_CACHE.pop(k, None)
        _shared_delete_many(tier_keys)


def invalidate_config_cache(action_code: str | None = None) -> None:
    """Backwards-compatible alias for invalidate_action_cache()."""
    invalidate_action_cache(action_code)


# ---------------------------------------------------------------------------
# Core lookup: 4-step cascade (ADR-097 §5.1)
# ---------------------------------------------------------------------------

def _lookup_cascade(
    code: str,
    quality_level: int | None,
    priority: str | None,
) -> "AIActionType":  # type: ignore[name-defined]
    """Deterministic 4-step DB lookup for (code, quality_level, priority).

    Step 1: Exact match  (ql=X, prio=Y) — only if both non-NULL
    Step 2: ql-only      (ql=X, prio=NULL) — only if quality_level non-NULL
    Step 3: prio-only    (ql=NULL, prio=Y) — only if priority non-NULL
    Step 4: Catch-all    (ql=NULL, prio=NULL) — always

    Raises ConfigurationError if no row found at any step.
    """
    from aifw.models import AIActionType

    base_qs = AIActionType.objects.select_related(
        "default_model__provider",
        "fallback_model__provider",
    ).filter(code=code, is_active=True)

    # Step 1: exact match
    if quality_level is not None and priority is not None:
        row = base_qs.filter(
            quality_level=quality_level, priority=priority
        ).first()
        if row:
            return row

    # Step 2: quality_level only
    if quality_level is not None:
        row = base_qs.filter(
            quality_level=quality_level, priority__isnull=True
        ).first()
        if row:
            return row

    # Step 3: priority only
    if priority is not None:
        row = base_qs.filter(
            quality_level__isnull=True, priority=priority
        ).first()
        if row:
            return row

    # Step 4: catch-all
    row = base_qs.filter(
        quality_level__isnull=True, priority__isnull=True
    ).first()
    if row:
        return row

    raise ConfigurationError(
        f"No AIActionType found for code={code!r} with "
        f"quality_level={quality_level}, priority={priority!r}. "
        f"Ensure a catch-all row (quality_level=NULL, priority=NULL) exists "
        f"and run 'manage.py check_aifw_config'."
    )


def _to_action_config(action: "AIActionType") -> ActionConfig:  # type: ignore[name-defined]
    """Convert AIActionType ORM object to ActionConfig TypedDict."""
    model = action.get_model()
    if model is None or model.provider is None:
        raise ConfigurationError(
            f"AIActionType {action.code!r} has no resolvable model. "
            f"Check default_model and fallback_model configuration."
        )
    from aifw.service import _build_model_string, _get_api_key
    ms = _build_model_string(model.provider.name, model.name)
    return ActionConfig(
        action_id=action.id,
        action_code=action.code,
        model_id=model.id,
        model=ms,
        model_string=ms,
        provider=model.provider.name,
        base_url=model.provider.base_url or "",
        api_key_env_var=model.provider.api_key_env_var or "",
        prompt_template_key=action.prompt_template_key,
        max_tokens=action.max_tokens,
        temperature=action.temperature,
    )


# ---------------------------------------------------------------------------
# Public: get_action_config (ADR-097 §5.2)
# ---------------------------------------------------------------------------

def get_action_config(
    action_code: str,
    quality_level: int | None = None,
    priority: str | None = None,
) -> ActionConfig:
    """Resolve ActionConfig for (action_code, quality_level, priority).

    Uses hybrid 2-layer cache (local dict + Django cache).
    Falls back through 4-step lookup cascade on cache miss.

    Args:
        action_code: Action identifier e.g. 'story_writing'.
        quality_level: Quality band 1–9 or None (use catch-all).
        priority: 'fast'|'balanced'|'quality' or None.

    Returns:
        ActionConfig TypedDict with all fields populated.

    Raises:
        ConfigurationError: If no matching AIActionType row exists.
    """
    cache_key = _action_cache_key(action_code, quality_level, priority)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    action = _lookup_cascade(action_code, quality_level, priority)
    config = _to_action_config(action)
    _cache_set(cache_key, config)
    return config


# ---------------------------------------------------------------------------
# Public: get_quality_level_for_tier (ADR-097 §5.3)
# ---------------------------------------------------------------------------

def get_quality_level_for_tier(tier: str | None) -> int:
    """Resolve quality_level for a subscription tier name.

    Args:
        tier: Subscription tier name e.g. 'premium', 'pro', 'freemium'.
              None or unknown tier returns QualityLevel.BALANCED (5).

    Returns:
        Quality level integer 1–9.
    """
    if not tier:
        return QualityLevel.BALANCED

    cache_key = _tier_cache_key(tier)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        from aifw.models import TierQualityMapping
        mapping = TierQualityMapping.objects.filter(
            tier=tier, is_active=True
        ).first()
        result = mapping.quality_level if mapping else QualityLevel.BALANCED
    except Exception as exc:
        logger.warning("get_quality_level_for_tier(%r) DB error: %s", tier, exc)
        result = QualityLevel.BALANCED

    _cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
_RETRY_ENABLED: bool = True

try:
    from tenacity import (
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )

    try:
        from litellm.exceptions import (
            APIConnectionError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        _TRANSIENT_ERRORS = (
            RateLimitError, ServiceUnavailableError, Timeout, APIConnectionError
        )
    except ImportError:
        _TRANSIENT_ERRORS = (Exception,)  # type: ignore[assignment]

    def _make_retry(fn):  # type: ignore[return]
        return retry(
            retry=retry_if_exception_type(_TRANSIENT_ERRORS),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )(fn)

except ImportError:
    _RETRY_ENABLED = False

    def _make_retry(fn):  # noqa: F811
        return fn


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_model_string(provider_name: str, model_name: str) -> str:
    provider = provider_name.lower()
    if provider == "openai":
        return model_name
    return f"{provider}/{model_name}"


def _get_api_key(provider) -> str:
    env_var = provider.api_key_env_var or ""
    if env_var:
        return os.environ.get(env_var, "")
    fallback_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    name = provider.name.lower()
    env_var = fallback_map.get(name, "")
    return os.environ.get(env_var, "") if env_var else ""


def _parse_tool_calls(message) -> list[ToolCall]:
    tool_calls = []
    if not message.tool_calls:
        return tool_calls
    for tc in message.tool_calls:
        arguments = tc.function.arguments
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        tool_calls.append(
            ToolCall(id=tc.id or "", name=tc.function.name or "", arguments=arguments)
        )
    return tool_calls


def _rendered_prompt_to_messages(rendered) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if rendered.system:
        messages.append({"role": "system", "content": rendered.system})
    few_shot = getattr(rendered, "few_shot_messages", None)
    if few_shot:
        messages.extend(few_shot)
    if rendered.user:
        messages.append({"role": "user", "content": rendered.user})
    return messages


def _rendered_prompt_to_overrides(rendered) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    rf = getattr(rendered, "response_format", None)
    if rf == "json_object":
        overrides["response_format"] = {"type": "json_object"}
    elif rf == "json_schema":
        schema = getattr(rendered, "output_schema", None)
        if schema:
            overrides["response_format"] = {
                "type": "json_schema", "json_schema": schema
            }
        else:
            overrides["response_format"] = {"type": "json_object"}
    return overrides


def _build_kwargs(
    config: dict[str, Any],
    messages: list[dict[str, Any]],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": config["model_string"],
        "messages": messages,
        "max_tokens": config.get("max_tokens", 2000),
        "temperature": config.get("temperature", 0.7),
    }
    api_key = config.get("api_key", "")
    if api_key:
        kwargs["api_key"] = api_key
    api_base = config.get("api_base")
    if api_base:
        kwargs["api_base"] = api_base
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# Legacy: get_model_config (backwards-compatible wrapper)
# ---------------------------------------------------------------------------

async def get_model_config(action_code: str) -> dict[str, Any]:
    """Load model config from DB with hybrid cache. Legacy API — 0.5.x compatible.

    New code should use get_action_config() instead.
    """
    cache_key = _action_cache_key(action_code, None, None)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        from aifw.models import AIActionType, LLMModel

        action = await sync_to_async(
            lambda: AIActionType.objects.select_related(
                "default_model__provider",
                "fallback_model__provider",
            )
            .filter(code=action_code, is_active=True)
            .first()
        )()

        if action:
            model = action.get_model()
            if model and model.provider:
                cfg = {
                    "model_string": _build_model_string(
                        model.provider.name, model.name
                    ),
                    "api_key": _get_api_key(model.provider),
                    "api_base": model.provider.base_url or None,
                    "max_tokens": action.max_tokens,
                    "temperature": action.temperature,
                    "action_id": action.id,
                    "model_id": model.id,
                    "provider_name": model.provider.name,
                    "model_name": model.name,
                }
                _cache_set(cache_key, cfg)
                return cfg

        global_default = await sync_to_async(
            lambda: LLMModel.objects.select_related("provider")
            .filter(is_default=True, is_active=True)
            .first()
        )()

        if global_default and global_default.provider:
            cfg = {
                "model_string": _build_model_string(
                    global_default.provider.name, global_default.name
                ),
                "api_key": _get_api_key(global_default.provider),
                "api_base": global_default.provider.base_url or None,
                "max_tokens": 2000,
                "temperature": 0.7,
                "action_id": None,
                "model_id": global_default.id,
                "provider_name": global_default.provider.name,
                "model_name": global_default.name,
            }
            _cache_set(cache_key, cfg)
            return cfg

    except Exception as e:
        logger.warning("DB config unavailable for '%s': %s", action_code, e)

    return {
        "model_string": "",
        "api_key": "",
        "api_base": None,
        "max_tokens": 2000,
        "temperature": 0.7,
        "action_id": None,
        "model_id": None,
        "provider_name": "",
        "model_name": "",
    }


# ---------------------------------------------------------------------------
# Internal usage logger
# ---------------------------------------------------------------------------

async def _log_usage(
    config: dict[str, Any],
    result: LLMResult,
    user=None,
    tenant_id: uuid.UUID | str | None = None,
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
    quality_level: int | None = None,
) -> None:
    try:
        from aifw.models import AIActionType, AIUsageLog, LLMModel

        action_id = config.get("action_id")
        model_id = config.get("model_id")

        action = None
        model = None
        if action_id:
            action = await sync_to_async(
                lambda: AIActionType.objects.filter(id=action_id).first()
            )()
        if model_id:
            model = await sync_to_async(
                lambda: LLMModel.objects.filter(id=model_id).first()
            )()

        if isinstance(tenant_id, str):
            try:
                tenant_id = uuid.UUID(tenant_id)
            except ValueError:
                tenant_id = None

        await sync_to_async(AIUsageLog.objects.create)(
            action_type=action,
            model_used=model,
            user=user,
            tenant_id=tenant_id,
            object_id=object_id or "",
            metadata=metadata or {},
            quality_level=quality_level,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            success=result.success,
            error_message=result.error or "",
        )
    except Exception as exc:
        logger.warning("Failed to log usage: %s", exc)


# ---------------------------------------------------------------------------
# Core async completion
# ---------------------------------------------------------------------------

async def completion(
    action_code: str,
    messages: list[dict[str, Any]] | Any,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    user=None,
    tenant_id: uuid.UUID | str | None = None,
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
    quality_level: int | None = None,
    priority: str | None = None,
    **overrides: Any,
) -> LLMResult:
    """Async LLM completion with quality-level routing.

    Args:
        action_code: Action identifier.
        messages: Message list or promptfw RenderedPrompt.
        quality_level: Quality band 1–9 (new in 0.6.0). None = catch-all.
        priority: 'fast'|'balanced'|'quality' (new in 0.6.0). None = catch-all.
        tenant_id: UUID for multi-tenant cost tracking.
        object_id: Opaque domain object reference.
        metadata: Arbitrary context dict.
    """
    if isinstance(messages, RenderedPromptProtocol):
        prompt_overrides = _rendered_prompt_to_overrides(messages)
        for k, v in prompt_overrides.items():
            overrides.setdefault(k, v)
        messages = _rendered_prompt_to_messages(messages)

    config = await get_model_config(action_code)
    kwargs = _build_kwargs(config, messages, dict(overrides))
    if tools:
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

    if not kwargs.get("model"):
        return LLMResult(
            success=False,
            error=f"No model configured for action {action_code!r}",
        )

    start_time = time.perf_counter()
    try:
        response = await litellm.acompletion(**kwargs)
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        choice = response.choices[0]
        message = choice.message
        result = LLMResult(
            success=True,
            content=message.content or "",
            tool_calls=_parse_tool_calls(message),
            finish_reason=choice.finish_reason or "",
            model=response.model or kwargs["model"],
            input_tokens=getattr(response.usage, "prompt_tokens", 0),
            output_tokens=getattr(response.usage, "completion_tokens", 0),
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.exception("LLM call failed for action '%s'", action_code)
        result = LLMResult(
            success=False,
            error=str(e),
            latency_ms=latency_ms,
            model=kwargs.get("model", ""),
        )

    await _log_usage(
        config,
        result,
        user=user,
        tenant_id=tenant_id,
        object_id=object_id,
        metadata=metadata,
        quality_level=quality_level,
    )
    return result


async def completion_stream(
    action_code: str,
    messages: list[dict[str, Any]] | Any,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    **overrides: Any,
) -> AsyncIterator[str]:
    """Async streaming completion — yields text chunks as they arrive."""
    if isinstance(messages, RenderedPromptProtocol):
        prompt_overrides = _rendered_prompt_to_overrides(messages)
        for k, v in prompt_overrides.items():
            overrides.setdefault(k, v)
        messages = _rendered_prompt_to_messages(messages)

    config = await get_model_config(action_code)
    kwargs = _build_kwargs(config, messages, dict(overrides))
    kwargs["stream"] = True
    if tools:
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

    response = await litellm.acompletion(**kwargs)
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


def sync_completion_stream(
    action_code: str,
    messages: list[dict[str, Any]] | Any,
    **overrides: Any,
):
    """Synchronous streaming generator — for Django StreamingHttpResponse."""
    if isinstance(messages, RenderedPromptProtocol):
        prompt_overrides = _rendered_prompt_to_overrides(messages)
        for k, v in prompt_overrides.items():
            overrides.setdefault(k, v)
        messages = _rendered_prompt_to_messages(messages)

    _DONE = object()
    _ERROR = object()
    chunk_queue: queue.Queue = queue.Queue(maxsize=256)

    async def _produce() -> None:
        try:
            config = await get_model_config(action_code)
            kwargs = _build_kwargs(config, messages, dict(overrides))
            kwargs["stream"] = True
            response = await litellm.acompletion(**kwargs)
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    chunk_queue.put(delta.content)
            chunk_queue.put(_DONE)
        except Exception as exc:
            chunk_queue.put((_ERROR, exc))

    def _run_producer() -> None:
        asyncio.run(_produce())

    producer = threading.Thread(target=_run_producer, daemon=True)
    producer.start()

    while True:
        item = chunk_queue.get(timeout=180)
        if item is _DONE:
            break
        if isinstance(item, tuple) and item[0] is _ERROR:
            raise item[1]
        yield item


def sync_completion(
    action_code: str,
    messages: list[dict[str, Any]] | Any,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    user=None,
    tenant_id: uuid.UUID | str | None = None,
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
    quality_level: int | None = None,
    priority: str | None = None,
    **overrides: Any,
) -> LLMResult:
    """Synchronous wrapper — safe in Django views, Celery tasks, management commands.

    New in 0.6.0: quality_level, priority parameters for routing.
    """
    coro = completion(
        action_code=action_code,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        user=user,
        tenant_id=tenant_id,
        object_id=object_id,
        metadata=metadata,
        quality_level=quality_level,
        priority=priority,
        **overrides,
    )
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=180)
    except RuntimeError:
        return asyncio.run(coro)


async def completion_with_fallback(
    action_code: str,
    messages: list[dict[str, Any]] | Any,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    user=None,
    tenant_id: uuid.UUID | str | None = None,
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
    quality_level: int | None = None,
    priority: str | None = None,
    **overrides: Any,
) -> LLMResult:
    """Completion with automatic fallback to the configured fallback model."""
    result = await completion(
        action_code=action_code,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        user=user,
        tenant_id=tenant_id,
        object_id=object_id,
        metadata=metadata,
        quality_level=quality_level,
        priority=priority,
        **overrides,
    )
    if result.success:
        return result

    try:
        from aifw.models import AIActionType

        action = await sync_to_async(
            lambda: AIActionType.objects.select_related("fallback_model__provider")
            .filter(code=action_code, is_active=True)
            .first()
        )()
        if action and action.fallback_model and action.fallback_model.is_active:
            fb = action.fallback_model
            logger.info(
                "Falling back from %s to %s for action '%s'",
                result.model,
                _build_model_string(fb.provider.name, fb.name),
                action_code,
            )
            return await completion(
                action_code=action_code,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                user=user,
                tenant_id=tenant_id,
                object_id=object_id,
                metadata=metadata,
                quality_level=quality_level,
                priority=priority,
                model=_build_model_string(fb.provider.name, fb.name),
                api_key=_get_api_key(fb.provider),
                **overrides,
            )
    except Exception as e:
        logger.warning("Fallback lookup failed: %s", e)

    return result


def sync_completion_with_fallback(
    action_code: str,
    messages: list[dict[str, Any]] | Any,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    user=None,
    tenant_id: uuid.UUID | str | None = None,
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
    quality_level: int | None = None,
    priority: str | None = None,
    **overrides: Any,
) -> LLMResult:
    """Synchronous wrapper for completion_with_fallback(). New in 0.6.0: quality_level, priority."""
    coro = completion_with_fallback(
        action_code=action_code,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        user=user,
        tenant_id=tenant_id,
        object_id=object_id,
        metadata=metadata,
        quality_level=quality_level,
        priority=priority,
        **overrides,
    )
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=180)
    except RuntimeError:
        return asyncio.run(coro)


def check_action_code(action_code: str) -> bool:
    """Return True if action_code has at least one active row (any quality_level/priority)."""
    try:
        from aifw.models import AIActionType
        exists = AIActionType.objects.filter(
            code=action_code, is_active=True
        ).exists()
        if not exists:
            logger.warning(
                "aifw: action_code '%s' not found — run 'manage.py init_aifw_config'",
                action_code,
            )
        return exists
    except Exception as exc:
        logger.warning("check_action_code('%s') failed: %s", action_code, exc)
        return False
