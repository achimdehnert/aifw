"""
Provider-agnostic LLM service via LiteLLM + DB-driven config.

Provider/model/pricing swaps require only DB changes — zero code changes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import litellm
from asgiref.sync import sync_to_async

from aifw.schema import LLMResult, ToolCall

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True


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


async def get_model_config(action_code: str) -> dict[str, Any]:
    """Load model config from DB for the given action code."""
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
                return {
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

        global_default = await sync_to_async(
            lambda: LLMModel.objects.select_related("provider")
            .filter(is_default=True, is_active=True)
            .first()
        )()

        if global_default and global_default.provider:
            return {
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


async def completion(
    action_code: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    user=None,
    **overrides: Any,
) -> LLMResult:
    """Async provider-agnostic LLM completion with DB-driven config."""
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

    kwargs: dict[str, Any] = {
        "model": overrides.pop("model", config["model_string"]),
        "messages": messages,
        "max_tokens": overrides.pop("max_tokens", config["max_tokens"]),
        "temperature": overrides.pop("temperature", config["temperature"]),
        "api_key": overrides.pop("api_key", config["api_key"]),
    }
    if config["api_base"]:
        kwargs["api_base"] = config["api_base"]
    if tools:
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
    kwargs.update(overrides)

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

    await _log_usage(config, result, user=user)
    return result


def sync_completion(
    action_code: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    user=None,
    **overrides: Any,
) -> LLMResult:
    """Synchronous wrapper — safe in Django views, Celery tasks, management commands."""
    import asyncio
    import concurrent.futures

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
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=180)
    except RuntimeError:
        return asyncio.run(coro)


async def completion_with_fallback(
    action_code: str,
    messages: list[dict[str, Any]],
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
