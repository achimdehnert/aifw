# Changelog — aifw

## [Unreleased]

## [0.7.0] — 2026-03-04

### Added
- `aifw.nl2sql` subpackage (local source — previously only in distributed whl)
- `NL2SQLExample` — verified Q→SQL pairs for few-shot prompting
  - DB table `aifw_nl2sql_examples`
  - `source`, `question`, `sql`, `domain`, `difficulty`, `is_active`, `promoted_from`
  - Injected automatically into LLM system prompt (up to 15 examples, ordered by difficulty)
- `NL2SQLFeedback` — auto-captured SQL execution errors + manual correction pipeline
  - DB table `aifw_nl2sql_feedback`
  - Auto-created by `NL2SQLEngine` on every `NL2SQLExecutionError`
  - Error type classification: `schema_error`, `table_error`, `join_error`, `syntax_error`, `timeout`
  - `corrected_sql` + `promoted` fields for Feedback → Example promotion
- `NL2SQLEngine` enhancements:
  - Few-shot block injected into system prompt from `NL2SQLExample`
  - Auto-captures `NL2SQLFeedback` on SQL execution errors
  - **Self-healing retry**: on execution error, second LLM call with error message as context (max 1 retry)
- Management commands:
  - `seed_nl2sql_examples` — seeds 11 verified odoo_mfg examples (casting, machines, scm, quality)
  - `promote_feedback` — promotes corrected feedback to NL2SQLExample (`--dry-run` supported)
  - `validate_schema` — validates every schema-XML table/column against real DB (CI/CD safe, exit 1 on error)
- Migration `0006_nl2sql_example_feedback`

## [0.5.0] — 2026-03-02

### Added
- `tenant_id`, `object_id`, `metadata` parameters on `completion()`,
  `sync_completion()`, `completion_with_fallback()` — forwarded directly to
  `AIUsageLog`; consumers (bfagent, travel-beat, weltenhub) no longer need
  wrapper boilerplate to track per-tenant costs
- `sync_completion_with_fallback()` — synchronous wrapper for
  `completion_with_fallback()`, safe in Django views / Celery / management
  commands
- `check_action_code(action_code)` — lightweight bool helper that verifies an
  `AIActionType` code exists in the DB; useful in pre-deploy checks and
  management commands

### Changed
- `_log_usage()` signature extended with `tenant_id`, `object_id`, `metadata`
- `import uuid` added to `service.py`; `tenant_id` accepts both `uuid.UUID`
  and `str` (auto-coerced)
- All public functions exported from `aifw.__init__`

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
