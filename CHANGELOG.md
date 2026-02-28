# Changelog — aifw

## [Unreleased]

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
