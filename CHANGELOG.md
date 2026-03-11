# Changelog — aifw

## [Unreleased]

## [0.9.0] — 2026-03-11

### Fixed
- **`_to_action_config()` KeyError**: `_build_kwargs()` reads `config["model_string"]`
  but `_to_action_config()` only set `config["model"]` via `ActionConfig` TypedDict.
  Now both `model` and `model_string` are set consistently.
- `ActionConfig` TypedDict extended with `model_string: str` field (alias of `model`).
  This is a **backwards-compatible** addition — existing consumers using `config["model"]`
  continue to work unchanged.

## [0.8.1] — 2026-03-09

### Fixed
- `completion()`: guard against empty `model_string` — now returns
  `LLMResult(success=False, error="No model configured for action '<code>'")` 
  immediately instead of raising `litellm.BadRequestError`. Fixes 
  `test_completion_no_model_configured` and improves error clarity for 
  misconfigured action codes.
- `test_tier.py`: `test_should_return_none_for_unknown_tier` expectation corrected
  to `QualityLevel.BALANCED` (the actual default returned by `get_quality_level_for_tier()`).
- Dev dependency pinned to `iil-promptfw>=0.5.5` to pick up the `extract_field()`
  regex fix for `**Field:**` markdown patterns.

## [0.8.0] — 2026-03-04

### Added
- `aifw/nl2sql/apps.py` — `NL2SQLConfig(AppConfig)` with `label="aifw_nl2sql"`
- `aifw/nl2sql/migrations/` — own migrations directory; `0001_initial_from_core`
  transfers NL2SQL models from `aifw` → `aifw_nl2sql` (SeparateDatabaseAndState, no DDL)
- `NL2SQLResult.needs_clarification`, `clarification_question`, `clarification_options`
  — additive fields for upcoming Clarification-Agent (ADR-010); all default to falsy

### Changed
- `aifw.nl2sql` is now a proper Django app (`app_label = "aifw_nl2sql"`)
- Must be added explicitly to `INSTALLED_APPS` to activate NL2SQL models + migrations
- `pyproject.toml` optional-dependency `nl2sql` comment updated (intent marker, no extra download)

### Migration notes
- Run `python manage.py migrate aifw 0007_nl2sql_app_label` then `migrate aifw_nl2sql`
- No DDL — all three `db_table` values are explicitly set and unchanged
- `travel-beat`, `writing-hub`, `weltenhub`: no action required (Core API unchanged)

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
