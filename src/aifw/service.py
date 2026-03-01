"""
Provider-agnostic LLM service via LiteLLM + DB-driven config.

Provider/model/pricing swaps require only DB changes — zero code changes.

New in 0.2.0:
- TTL-based in-memory config cache (avoid per-call DB queries)
- Streaming via completion_stream() / sync_completion_stream()
- Tenacity retry with exponential backoff (rate limits, 503s)
- RenderedPrompt integration — pass promptfw output directly
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import litellm
from asgiref.sync import sync_to_async

from aifw.schema import LLMResult, ToolCall

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

    def _make_retry(fn):  # type: ignore[return]
        return retry(
            retry=retry_if_exception_type((Exception,)),
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
    """Convert a promptfw RenderedPrompt to LiteLLM messages list."""
    messages: list[dict[str, Any]] = []
    if rendered.system:
        messages.append({"role": "system", "content": rendered.system})
    if rendered.user:
        messages.append({"role": "user", "content": rendered.user})
    return messages


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
                    "model_string": _build_model_string(model.provider.name, model.name),
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

async def _log_usage(config: dict, result: LLMResult, user=None) -> None:
    try:
        from aifw.models import AIUsageLog

        await sync_to_async(
            lambda: AIUsageLog.objects.create(
                action_type_id=config.get("action_id"),
                model_used_id=config.get("model_id"),
                user=user,
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


def _build_kwargs(config: dict, messages: list[dict], overrides: dict) -> dict[str, Any]:
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
    **overrides: Any,
) -> LLMResult:
    """
    Async LLM completion with DB-driven config, TTL cache, and retry.

    ``messages`` can be a list of dicts OR a ``promptfw.RenderedPrompt``.
    """
    if hasattr(messages, "system") and hasattr(messages, "user"):
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
                "default_model in Admin → AI Services → AI Action Types."
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

    await _log_usage(config, result, user=user)
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
    if hasattr(messages, "system") and hasattr(messages, "user"):
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

    Usage::

        def my_view(request):
            return StreamingHttpResponse(
                sync_completion_stream("story_writing", messages),
                content_type="text/event-stream",
            )
    """
    if hasattr(messages, "system") and hasattr(messages, "user"):
        messages = _rendered_prompt_to_messages(messages)

    config_future: dict[str, Any] = {}

    async def _collect():
        config = await get_model_config(action_code)
        config_future.update(config)
        kwargs = _build_kwargs(config, messages, dict(overrides))
        kwargs["stream"] = True
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def _to_list():
        return [chunk async for chunk in _collect()]

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        chunks = pool.submit(asyncio.run, _to_list()).result(timeout=180)

    yield from chunks


def sync_completion(
    action_code: str,
    messages: list[dict[str, Any]] | Any,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    user=None,
    **overrides: Any,
) -> LLMResult:
    """Synchronous wrapper — safe in Django views, Celery tasks, management commands."""
    coro = completion(
        action_code=action_code,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        user=user,
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
    **overrides: Any,
) -> LLMResult:
    """Completion with automatic fallback to the configured fallback model."""
    result = await completion(
        action_code=action_code,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        user=user,
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
                model=_build_model_string(fb.provider.name, fb.name),
                api_key=_get_api_key(fb.provider),
                **overrides,
            )
    except Exception as e:
        logger.warning("Fallback lookup failed: %s", e)

    return result
