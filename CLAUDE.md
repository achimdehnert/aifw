# CLAUDE.md — iil-aifw operating guide

## What this is

`iil-aifw` (import package `aifw`) is a **Django AI Services Framework**: DB-driven
LLM provider/model/usage management, quality-tier routing, privacy-by-design usage
logging, and an optional NL2SQL (text-to-SQL) subsystem. It is a reusable library
published to PyPI as `iil-aifw` and consumed by platform apps (bfagent, weltenhub,
travel-beat, …). It is **not** a standalone application.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate   # optional
make install                                     # pip install -e ".[dev]"
```

`requires-python >= 3.12`. Core deps: Django (>=5.0,<6.0), litellm, tenacity, asgiref.
Optional extras: `nl2sql` (no extra wheels — activate via INSTALLED_APPS), `promptfw`,
`rag` (pgvector), `all`, `dev`.

## Test / lint / types

```bash
make test     # python3 -m pytest tests/ --tb=short -q
make test-v   # verbose
make lint     # ruff check src/ tests/
```

- Tests run on in-memory SQLite via `tests/settings.py` (`DJANGO_SETTINGS_MODULE=tests.settings`);
  no live Postgres or secrets needed. `pytest.ini_options` sets `pythonpath = ["src", "."]`,
  so `make test` works without an editable install.
- Lint = ruff (rules `E`, `F`, `I`, line-length 100, `target-version py312`). Migrations are
  excluded; a few NL2SQL prompt/SQL modules carry a justified per-file `E501` ignore.
- No mypy configured (the package ships `py.typed` for downstream type checking, but there is
  no type-check gate in this repo).
- CI (`.github/workflows/ci.yml`) runs ruff + `pytest -v` on Python 3.12 for push/PR to `main`.

## Architecture (module map)

Source lives under `src/aifw/`:

| Module | Role |
|---|---|
| `__init__.py` | Public API surface + `__version__` (read from installed metadata). |
| `service.py` | Core entrypoints: `completion` / `sync_completion` (+ `_stream`, `_with_fallback`), `get_action_config`, `get_quality_level_for_tier`, cache invalidation. |
| `models.py` | Django models: AI action types, usage logs (incl. k-anonymity aggregation), tier→quality mappings. |
| `constants.py` | `QualityLevel`, `PrivacyMode`. |
| `privacy.py` | Privacy-by-design pre-write transform (`PrivacyHook`, `apply_privacy`, `get_privacy_hook`). |
| `cost.py` | Cost estimation (`estimate_cost`, `cost_from_rates`). |
| `schema.py` / `types.py` | `LLMResult`, `ToolCall`, `RenderedPromptProtocol`, `ActionConfig`. |
| `exceptions.py` | `AIFWError`, `ConfigurationError`, `OrchestrationError`. |
| `apps.py` / `signals.py` / `admin.py` | Django app wiring. |
| `management/commands/` | `check_aifw_config`, `init_aifw_config`, `promote_feedback`, `seed_nl2sql_examples`, `validate_schema`. |
| `nl2sql/` | Optional text-to-SQL subsystem (`engine.py`, `semantic.py`, `clarification.py`, `results.py`, own models/migrations/commands). Activated by adding `aifw.nl2sql` to INSTALLED_APPS. |
| `migrations/` | Core schema (0001–0009). Auto-generated; not linted. |

## Conventions

- Commits: `[feat|fix|refactor|docs|test|chore](scope): description`.
- `__version__` is **always** resolved from package metadata — never hardcode it
  (past 0.10.x metadata/code drift tripped the consumer CI guard).
- Keep ruff `target-version`, mypy `python_version` (none today), and the Python
  classifiers consistent with `requires-python`. Do not change `requires-python`
  casually — it is a consumer-facing contract.
- `aifw` must not import `iil-promptfw` at runtime; topic classification is an
  injected callable (privacy hook factory).

## Release (GATED — not on-merge)

Publishing to PyPI is **manual and gated**, never automatic on merge to `main`.
Merging a PR does **not** publish. A release is a deliberate step (version bump in
`pyproject.toml` + `CHANGELOG.md`, then the gated `publish.yml` workflow / `/release`
flow). Agents must not publish, tag, or trigger a release without explicit human
approval.

## Known issues / gotchas

- Tests emit a pytest naming-convention warning (`test_should_<...>` preferred) for a
  number of existing tests — cosmetic, not failing.
- NEXT.md is an **auto-generated editor cache**, not a source of truth — ignore it for
  planning; use this file + AGENT_HANDOVER.md + CHANGELOG.md.
- Default `AIFW_PRIVACY_MODE` will flip from `"full"` to `"pseudonymous"` in 0.12.0
  (documented breaking change); 0.11.x is non-breaking.
