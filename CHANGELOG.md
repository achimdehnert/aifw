# Changelog — aifw

## [Unreleased]

## [0.4.0] — 2026-03-01

### Added
- `RenderedPromptProtocol` (`typing.Protocol`, `@runtime_checkable`) in `schema.py` —
  formalises the duck-typing contract for promptfw-compatible objects; exported via `aifw`
- `AIUsageLog.tenant_id` — nullable UUID, indexed (multi-tenancy support)
- `AIUsageLog.object_id` — CharField(200), indexed (domain object reference, e.g. `"chapter:42"`)
- `AIUsageLog.metadata` — JSONField (arbitrary per-call context)
- Migration `0003_aiusagelog_tenant_object_metadata`
- `aifw/signals.py` — Django signals that invalidate the config cache on
  `AIActionType`, `LLMModel`, `LLMProvider` save/delete events
- `AifwConfig.ready()` registers signals automatically
- Ollama provider entry in `init_aifw_config` defaults
- Gemini 1.5 Pro model entry in `init_aifw_config` defaults

### Changed
- **Retry** now targets only transient LiteLLM errors
  (`RateLimitError`, `ServiceUnavailableError`, `Timeout`, `APIConnectionError`);
  auth and validation errors are no longer retried
- **`sync_completion_stream`** rewritten with `queue.Queue` + `threading.Thread` —
  true streaming (chunks yielded as they arrive, not after full collection);
  exceptions are propagated to the consumer via an error sentinel
- **`completion()` / `completion_stream()` / `sync_completion_stream()`** use
  `isinstance(messages, RenderedPromptProtocol)` instead of fragile `hasattr()` checks
- **`init_aifw_config`** seeds providers and models only — domain-specific
  `AIActionType` entries removed; each consumer app owns its own fixture

### Migration notes
- Run `python manage.py migrate aifw` after upgrading to apply migration 0003
- Consumer apps that relied on domain actions seeded by `init_aifw_config`
  (e.g. `chapter_generation`, `travel_itinerary`) must provide their own fixture

## [0.1.0] — 2026-02-28

### Added
- Initial release
- `LLMProvider`, `LLMModel`, `AIActionType`, `AIUsageLog` Django models
- `completion()` async LLM call via LiteLLM
- `sync_completion()` synchronous wrapper (thread-pool safe)
- `completion_with_fallback()` automatic fallback model support
- `LLMResult`, `ToolCall` dataclasses
- `init_aifw_config` management command (seeds default providers & models)
- Django Admin registration for all models
