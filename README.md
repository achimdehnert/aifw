# aifw — Django AI Services Framework

DB-driven LLM provider, model & usage management for Django projects.

## Installation

```bash
pip install aifw
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
```

```python
# Use in views, tasks, management commands
from aifw.service import sync_completion, LLMResult

result: LLMResult = sync_completion(
    action_code="story_writing",
    messages=[{"role": "user", "content": "Write a short story about a dragon."}],
)

if result.success:
    print(result.content)
```

## Features

- **DB-driven model routing** — swap LLM providers/models via Django Admin, zero code changes
- **Multi-provider** — OpenAI, Anthropic, Google, Ollama, any LiteLLM-compatible provider
- **Async & sync** — `completion()` (async), `sync_completion()` (sync), `completion_with_fallback()`
- **Usage logging** — automatic token & cost tracking per action type
- **Fallback models** — configure primary + fallback model per action type

## Models

- `LLMProvider` — provider config (API key env var, base URL)
- `LLMModel` — model config (max tokens, cost per million tokens)
- `AIActionType` — action → model mapping with fallback
- `AIUsageLog` — token/cost/latency tracking per request

## Management Commands

```bash
python manage.py init_llm_config   # seed default providers & models
```
