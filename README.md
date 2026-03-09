# iil-aifw — Django AI Services Framework

DB-driven LLM provider, model & usage management for Django projects.

[![PyPI](https://img.shields.io/pypi/v/iil-aifw)](https://pypi.org/project/iil-aifw/)
[![Python](https://img.shields.io/pypi/pyversions/iil-aifw)](https://pypi.org/project/iil-aifw/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Installation

```bash
pip install iil-aifw
# With NL2SQL support:
pip install "iil-aifw[nl2sql]"
```

## Quick Start

```python
# settings.py
INSTALLED_APPS = [
    ...
    "aifw",
]

# Run migrations
python manage.py migrate aifw
python manage.py init_aifw_config   # seed default providers & models
```

```python
from aifw.service import sync_completion

result = sync_completion(
    action_code="story_writing",
    messages=[{"role": "user", "content": "Write a short story about a dragon."}],
)

if result.success:
    print(result.content)
else:
    print(result.error)
```

## Features

- **DB-driven model routing** — swap LLM providers/models via Django Admin, zero code changes
- **Multi-provider** — OpenAI, Anthropic, Google, Ollama, any LiteLLM-compatible provider
- **Quality-level routing** — map subscription tiers to model quality (economy/balanced/premium)
- **Async & sync** — `completion()` async, `sync_completion()` sync, `completion_with_fallback()`
- **Streaming** — `sync_completion_stream()` for Django `StreamingHttpResponse`
- **Usage logging** — automatic token & latency tracking per action, per tenant
- **Fallback models** — configure primary + fallback model per action type
- **NL2SQL** — natural language → SQL engine with few-shot examples and self-healing retry
- **Hybrid cache** — process-local (30s) + Django cache framework (600s, Redis-aware)

## Core API

```python
from aifw.service import (
    completion,                  # async
    sync_completion,             # sync wrapper
    completion_with_fallback,    # async, tries fallback model on error
    sync_completion_with_fallback,
    sync_completion_stream,      # streaming generator
    get_quality_level_for_tier,  # tier name → QualityLevel int
    check_action_code,           # bool — action code exists in DB
)
```

### Quality-Level Routing (v0.6.0)

Each `AIActionType` row can be scoped to a `quality_level` (1–9) and/or `priority`
(`'fast'`|`'balanced'`|`'quality'`). A NULL in either dimension acts as catch-all.
Lookup uses a deterministic 4-step cascade: exact → ql-only → prio-only → catch-all.

```python
from aifw.constants import QualityLevel
from aifw.service import get_quality_level_for_tier, sync_completion

# Map a subscription tier to a quality level (DB-driven via TierQualityMapping)
ql = get_quality_level_for_tier("pro")          # → QualityLevel.BALANCED (5)
ql = get_quality_level_for_tier("premium")      # → QualityLevel.PREMIUM  (8)
ql = get_quality_level_for_tier("freemium")     # → QualityLevel.ECONOMY  (2)

result = sync_completion(
    "story_writing",
    messages,
    quality_level=ql,
    priority="quality",
)
```

### Multi-Tenant Usage Tracking (v0.5.0)

```python
result = sync_completion(
    "story_writing",
    messages,
    tenant_id=user.organization_id,
    object_id=f"story-{story.pk}",
    metadata={"source": "web", "plan": "pro"},
)
```

### Streaming (v0.4.0)

```python
from aifw.service import sync_completion_stream
from django.http import StreamingHttpResponse

def stream_story(request):
    def generate():
        for chunk in sync_completion_stream("story_writing", messages):
            yield chunk
    return StreamingHttpResponse(generate(), content_type="text/plain")
```

## Django Models

| Model | Purpose |
|---|---|
| `LLMProvider` | Provider config (API key env var, base URL) |
| `LLMModel` | Model config (max tokens, cost per million tokens) |
| `AIActionType` | Action → model mapping; supports `quality_level` + `priority` dimensions |
| `AIUsageLog` | Token/latency/cost tracking per request, with `tenant_id` + `metadata` |
| `TierQualityMapping` | Subscription tier → quality_level mapping (DB-driven) |

## NL2SQL (v0.7.0+)

```python
# settings.py
INSTALLED_APPS = [
    ...
    "aifw",
    "aifw.nl2sql",   # activates NL2SQL models + migrations
]

python manage.py migrate aifw_nl2sql
python manage.py seed_nl2sql_examples   # seed verified few-shot examples
```

```python
from aifw.nl2sql import NL2SQLEngine

engine = NL2SQLEngine(schema_xml="<schema>...</schema>")
result = engine.query("How many open orders do we have?")

if result.success:
    print(result.sql)
    print(result.rows)
```

- **Few-shot examples** injected automatically from `NL2SQLExample` model
- **Self-healing retry** — on SQL execution error, a second LLM call includes the error as context
- **Feedback capture** — `NL2SQLFeedback` auto-created on every execution error
- Management commands: `seed_nl2sql_examples`, `promote_feedback`, `validate_schema`

## Management Commands

```bash
python manage.py init_aifw_config       # seed default providers & models
python manage.py check_aifw_config      # CI gate — verify all action codes have a catch-all row
python manage.py seed_nl2sql_examples   # seed NL2SQL few-shot examples
python manage.py promote_feedback       # promote corrected feedback → NL2SQLExample
python manage.py validate_schema        # validate schema-XML against real DB (exit 1 on error)
```

## Cache Tuning

```bash
# Environment variables (optional)
AIFW_LOCAL_CACHE_TTL=30     # process-local TTL in seconds (default: 30)
AIFW_CACHE_TTL=600          # shared cache TTL in seconds  (default: 600)
```

```python
from aifw.service import invalidate_action_cache, invalidate_tier_cache

invalidate_action_cache("story_writing")   # clear one action's cache entries
invalidate_action_cache()                  # clear all
invalidate_tier_cache("pro")               # clear one tier
```

## Constants

```python
from aifw.constants import QualityLevel

QualityLevel.ECONOMY   # 2
QualityLevel.BALANCED  # 5
QualityLevel.PREMIUM   # 8
QualityLevel.ALL       # (2, 5, 8)
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
