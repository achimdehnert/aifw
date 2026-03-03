# Changelog — aifw

## [Unreleased]

## [0.6.0] — 2026-03-03

### Added (ADR-095 / ADR-097)
- **Quality-level routing**: `AIActionType` now supports multiple rows per `code`
  with `quality_level` (1–9) and `priority` ('fast'|'balanced'|'quality') dimensions.
  NULL in either dimension acts as catch-all. Fully backwards-compatible — existing
  single-row configs continue to work as catch-all rows.
- `get_action_config(code, quality_level, priority)` — deterministic 4-step lookup
  cascade: exact → ql-only → prio-only → catch-all. Returns `ActionConfig` TypedDict.
- `get_quality_level_for_tier(tier)` — DB-driven subscription tier → quality_level
  mapping via new `TierQualityMapping` model. Replaces hardcoded dicts in consumers.
- `TierQualityMapping` model — seeded with premium=8, pro=5, freemium=2 defaults.
- `AIActionType.prompt_template_key` — optional promptfw template key string
  (aifw never imports promptfw — plain string only).
- `AIUsageLog.quality_level` — dedicated column for cost-per-tier analytics
  (no joins needed).
- `QualityLevel` constants class: `ECONOMY=2`, `BALANCED=5`, `PREMIUM=8`.
- `ActionConfig` TypedDict — contract for `get_action_config()` return value.
- `ConfigurationError` / `OrchestrationError` / `AIFWError` exception hierarchy.
- `invalidate_action_cache()` / `invalidate_tier_cache()` — explicit invalidation API.
- `check_aifw_config` management command — CI/pre-deploy gate; verifies all active
  action codes have an active catch-all row.
- **Hybrid 2-layer cache**: process-local dict (30s TTL) + Django cache framework
  (600s TTL, Redis if configured). Zero new dependencies — works without Redis,
  uses it automatically when `CACHES` is configured.
- `sync_completion()` / `completion()` extended with `quality_level` and `priority`
  parameters.

### Changed
- `AIActionType.code`: `unique=True` → `db_index=True` (**Breaking** — allows
  multiple rows per code; uniqueness enforced by 4 partial unique indexes).
- `apps.py` `AifwConfig.ready()` now also connects `TierQualityMapping` signals.
- `admin.py`: `AIActionTypeAdmin` and `AIUsageLogAdmin` updated with new fields;
  `TierQualityMappingAdmin` added.
- Cache TTL configurable via `AIFW_LOCAL_CACHE_TTL` (default 30s) and
  `AIFW_CACHE_TTL` (default 600s). Legacy `AIFW_CONFIG_TTL` still honoured.

### Migration notes
- Run `python manage.py migrate aifw` to apply migration `0005`.
- Migration is reversible (`migrate aifw 0004` to roll back).
- Existing single-row `AIActionType` entries work as catch-all rows — no data
  migration required for existing consumers.
- Consumer apps using `AIActionType.objects.get(code=...)` must migrate to
  `filter(code=...).first()` (multiple rows now allowed per code).

## [0.5.1] — 2026-03-02

### Changed
- Migration `0004`: `AlterModelOptions` + `BigAutoField` housekeeping.
- No functional changes from 0.5.0.

## [0.5.0] — 2026-03-02

### Added
- `tenant_id`, `object_id`, `metadata` parameters on `completion()`,
  `sync_completion()`, `completion_with_fallback()` — forwarded directly to
  `AIUsageLog`; consumers no longer need wrapper boilerplate for per-tenant costs.
- `sync_completion_with_fallback()` — synchronous wrapper for
  `completion_with_fallback()`, safe in Django views / Celery / management commands.
- `check_action_code(action_code)` — lightweight bool helper for pre-deploy checks.

### Changed
- `_log_usage()` signature extended with `tenant_id`, `object_id`, `metadata`.
- All public functions exported from `aifw.__init__`.

## [0.4.0] — 2026-03-01

### Added
- `RenderedPromptProtocol` (`typing.Protocol`, `@runtime_checkable`) in `schema.py`.
- `AIUsageLog.tenant_id`, `object_id`, `metadata`.
- Migration `0003_aiusagelog_tenant_object_metadata`.
- `aifw/signals.py` — Django signals for cache invalidation.
- `AifwConfig.ready()` registers signals automatically.
- Ollama + Gemini 1.5 Pro entries in `init_aifw_config` defaults.

### Changed
- Retry targets only transient LiteLLM errors.
- `sync_completion_stream` rewritten with `queue.Queue` + `threading.Thread`.
- `init_aifw_config` seeds providers/models only; consumer apps own their fixtures.

## [0.1.0] — 2026-02-28

### Added
- Initial release.
- `LLMProvider`, `LLMModel`, `AIActionType`, `AIUsageLog` Django models.
- `completion()` async LLM call via LiteLLM.
- `sync_completion()` synchronous wrapper.
- `completion_with_fallback()` automatic fallback model support.
- `LLMResult`, `ToolCall` dataclasses.
- `init_aifw_config` management command.
- Django Admin registration for all models.
