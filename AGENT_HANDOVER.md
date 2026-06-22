# AGENT_HANDOVER.md — iil-aifw

Living handover for the next agent (or human). For repo operating details see
`CLAUDE.md`; for the change log see `CHANGELOG.md`. **NEXT.md is an auto-generated
editor cache, not the source of truth — do not rely on it.**

## Current state (observed 2026-06-22)

- **Version:** `0.11.4` (pyproject `version`; `__version__` resolves from installed
  package metadata).
- **Tests:** `make test` → **162 passed** (1 cosmetic pytest naming-convention warning).
  In-memory SQLite, no external services required.
- **Lint:** `make lint` (ruff `E,F,I`, line-length 100, `target-version py312`) →
  **clean**, all checks pass.
- **Types:** no mypy gate configured (package ships `py.typed` for consumers).
- **CI:** `.github/workflows/ci.yml` runs ruff + `pytest -v` on Python 3.12 for
  push/PR to `main`. Publishing is a separate **gated** workflow (`publish.yml`),
  not on-merge.

## Recently landed

- **0.11.x — Privacy-by-design logging (issue #8):** `AIUsageLog.privacy_mode`
  column + `aifw.privacy` pre-write transform (`full`/`pseudonymous`/`anonymous`),
  custom hooks via `AIFW_PRIVACY_HOOK`, fail-closed scrubbing, k-anonymity
  aggregation. Default stays `"full"` (non-breaking).
- **0.10.x — Quality-level routing:** `get_action_config`,
  `get_quality_level_for_tier`, DB-driven tier→quality mapping.
- **0.7.0+ — NL2SQL subsystem** under `aifw.nl2sql` (optional app).

## Known issues / TODO

- Pre-existing pytest naming-convention warnings (`test_should_<...>` preferred) on
  several tests — cosmetic, deferred.
- No mypy/type-check gate yet (deferred to a later agent-readiness tier).
- **Planned breaking change:** default `AIFW_PRIVACY_MODE` moves `"full"` →
  `"pseudonymous"` in **0.12.0** (documented). Consumers relying on raw user logging
  must then set `AIFW_PRIVACY_MODE = "full"` explicitly.

## Next priorities

1. 0.12.0 privacy-default flip + consumer migration notes (bfagent, weltenhub,
   travel-beat).
2. Optional: add a mypy gate (next agent-readiness tier).
3. Tidy up legacy test names to the `test_should_*` convention.

## Pointers

- Operating guide & module map: `CLAUDE.md`
- Public API surface + version logic: `src/aifw/__init__.py`
- Core entrypoints: `src/aifw/service.py`
- Privacy model: `src/aifw/privacy.py`, `src/aifw/constants.py`
- NL2SQL: `src/aifw/nl2sql/`
- Change history: `CHANGELOG.md`
