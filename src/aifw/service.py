"""
Provider-agnostic LLM service via LiteLLM + DB-driven config.

Provider/model/pricing swaps require only DB changes — zero code changes.

New in 0.2.0:
- TTL-based in-memory config cache (avoid per-call DB queries)
- Streaming via completion_stream() / sync_completion_stream()
- Tenacity retry with exponential backoff (rate limits, 503s)
- RenderedPrompt integration — pass promptfw output directly

New in 0.4.0:
- Retry restricted to transient errors only (RateLimitError, ServiceUnavailableError,
  Timeout, APIConnectionError) — avoids retrying auth/validation failures
- Django signals for cache invalidation on model changes
- AIUsageLog extended with tenant_id, object_id, metadata
- sync_completion_stream uses queue.Queue for true streaming
- RenderedPromptProtocol (typing.Protocol) replaces duck-typing

New in 0.5.0:
- tenant_id, object_id, metadata forwarded through completion() / sync_completion()
  to AIUsageLog — enables per-tenant cost tracking without boilerplate in consumers
- sync_completion_with_fallback() — sync wrapper for completion_with_fallback()
- check_action_code() — lightweight validation helper for pre-deploy checks
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

from aifw.schema import LLMResult, RenderedPromptProtocol, ToolCall

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True

# ---------------------------------------------------------------------------
# Config cache — TTL in seconds (default 60s, override via AIFW_CONFIG_TTL)
# ---------------------------------------------------------------------------
_config_cache: dict[str, tuple[dict[str, Any], float]] = {}
_CONFIG_TTL: int = int(os.environ.get("AIFW_CONFIG_TTL", "60"))


def invalidate_config_cache(action_code: str | None = None) -> None:
    """Invalidate config cache. Pass action_code to clear only one entry."""
    if action_code:
        _config_cache.pop(action_code, None)
    else:
        _config_cache.clear()


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
    """Convert a promptfw RenderedPrompt to LiteLLM messages list.

    Includes few_shot_messages (interleaved user/assistant turns) if present.
    """
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
    """Extract response_format / output_schema from a promptfw RenderedPrompt.

    Maps promptfw ``response_format`` values to the LiteLLM
    ``response_format`` parameter:
    - ``"json_object"``  -> ``{"type": "json_object"}``
    - ``"json_schema"``  -> ``{"type": "json_schema", "json_schema": output_schema}``
    - ``"text"`` / None -> no override (default LiteLLM behaviour)
    """
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


# ---------------------------------------------------------------------------
# DB config loader with TTL cache
# ---------------------------------------------------------------------------

async def get_model_config(action_code: str) -> dict[str, Any]:
    """Load model config from DB, with TTL-based in-memory cache."""
    now = time.monotonic()
    cached = _config_cache.get(action_code)
    if cached and (now - cached[1]) < _CONFIG_TTL:
        return cached[0]

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
                _config_cache[action_code] = (cfg, now)
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
            _config_cache[action_code] = (cfg, now)
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
# Usage logging
# ---------------------------------------------------------------------------

async def _log_usage(
    config: dict,
    result: LLMResult,
    user=None,
    tenant_id: uuid.UUID | str | None = None,
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        from aifw.models import AIUsageLog

        _tenant_id = tenant_id
        if isinstance(_tenant_id, str) and _tenant_id:
            try:
                _tenant_id = uuid.UUID(_tenant_id)
            except ValueError:
                _tenant_id = None

        await sync_to_async(
            lambda: AIUsageLog.objects.create(
                action_type_id=config.get("action_id"),
                model_used_id=config.get("model_id"),
                user=user,
                tenant_id=_tenant_id,
                object_id=object_id or "",
                metadata=metadata or {},
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                success=result.success,
                error_message=result.error,
            )
        )()
    except Exception as e:
        logger.warning("Failed to log AI usage: %s", e)


# ---------------------------------------------------------------------------
# Core LiteLLM call (wrapped with retry)
# ---------------------------------------------------------------------------

async def _call_litellm(kwargs: dict[str, Any]):
    """Raw LiteLLM call — wrapped by tenacity retry in completion()."""
    return await litellm.acompletion(**kwargs)


_call_litellm_with_retry = _make_retry(_call_litellm)


def _build_kwargs(
    config: dict, messages: list[dict], overrides: dict
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": overrides.pop("model", config["model_string"]),
        "messages": messages,
        "max_tokens": overrides.pop("max_tokens", config["max_tokens"]),
        "temperature": overrides.pop("temperature", config["temperature"]),
        "api_key": overrides.pop("api_key", config["api_key"]),
    }
    if config["api_base"]:
        kwargs["api_base"] = config["api_base"]
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# Public API
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
    **overrides: Any,
) -> LLMResult:
    """
    Async LLM completion with DB-driven config, TTL cache, and retry.

    ``messages`` can be a list of dicts OR a ``promptfw.RenderedPrompt``
    (or any object satisfying ``RenderedPromptProtocol``).
    If a ``RenderedPrompt`` is passed, ``response_format`` and ``output_schema``
    are automatically forwarded to LiteLLM (json_object / json_schema).

    Args:
        tenant_id: UUID of the tenant (multi-tenant apps). Stored in AIUsageLog.
        object_id: Opaque domain object reference, e.g. ``"chapter:42"``.
        metadata: Arbitrary context dict, e.g. ``{"pipeline": "enrich"}``.
    """
    if isinstance(messages, RenderedPromptProtocol):
        prompt_overrides = _rendered_prompt_to_overrides(messages)
        for k, v in prompt_overrides.items():
            overrides.setdefault(k, v)
        messages = _rendered_prompt_to_messages(messages)

    config = await get_model_config(action_code)
    start_time = time.perf_counter()

    effective_model = overrides.get("model") or config["model_string"]
    if not effective_model:
        return LLMResult(
            success=False,
            error=(
                f"No LLM model configured for action '{action_code}'. "
                "Run 'python manage.py init_aifw_config' or assign a "
                "default_model in Admin -> AI Services -> AI Action Types."
            ),
        )

    kwargs = _build_kwargs(config, messages, dict(overrides))
    if tools:
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

    try:
        response = await _call_litellm_with_retry(kwargs)
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
        config, result,
        user=user,
        tenant_id=tenant_id,
        object_id=object_id,
        metadata=metadata,
    )
    return result


async def completion_stream(
    action_code: str,
    messages: list[dict[str, Any]] | Any,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    **overrides: Any,
) -> AsyncIterator[str]:
    """
    Async streaming completion — yields text chunks as they arrive.

    Usage::

        async for chunk in completion_stream("story_writing", messages):
            print(chunk, end="", flush=True)
    """
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
    """
    Synchronous streaming generator — for Django views (StreamingHttpResponse).

    Yields text chunks as they arrive from the LLM (true streaming via
    queue.Queue). A producer thread runs the async event loop; the main
    thread consumes from the queue so Django can flush chunks immediately.

    Usage::

        def my_view(request):
            return StreamingHttpResponse(
                sync_completion_stream("story_writing", messages),
                content_type="text/event-stream",
            )
    """
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
    **overrides: Any,
) -> LLMResult:
    """Synchronous wrapper — safe in Django views, Celery tasks, management commands.

    Args:
        tenant_id: UUID of the tenant (multi-tenant apps). Stored in AIUsageLog.
        object_id: Opaque domain object reference, e.g. ``"chapter:42"``.
        metadata: Arbitrary context dict, e.g. ``{"pipeline": "enrich"}``.
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
    **overrides: Any,
) -> LLMResult:
    """Synchronous wrapper for completion_with_fallback().

    Tries the default model; automatically retries with the configured
    fallback model on failure. Safe in Django views, Celery tasks, management commands.

    Args:
        tenant_id: UUID of the tenant (multi-tenant apps). Stored in AIUsageLog.
        object_id: Opaque domain object reference, e.g. ``"project:7"``.
        metadata: Arbitrary context dict, e.g. ``{"pipeline": "enrich"}``.
    """
    coro = completion_with_fallback(
        action_code=action_code,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        user=user,
        tenant_id=tenant_id,
        object_id=object_id,
        metadata=metadata,
        **overrides,
    )

    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=180)
    except RuntimeError:
        return asyncio.run(coro)


def check_action_code(action_code: str) -> bool:
    """Return True if action_code exists and is active in the DB.

    Lightweight pre-deploy / management-command check. Does NOT raise —
    logs a warning and returns False if the code is missing.

    Usage::

        from aifw import check_action_code
        assert check_action_code("story_writing"), "Seed aifw config first"
    """
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
    except Exception as e:
        logger.warning("check_action_code('%s') failed: %s", action_code, e)
        return False
