# Changelog

## 2025-02-14
- scaffolded `tool_core` package with minimal `ToolRegistry`, schema validation, and error handling
- added unit tests (`tests/test_tool_registry.py`) verifying registration, validation failures, and context usage
- documented design direction in `tool_module_development.md` and noted reference project paths
- introduced `tools/python_tool.py` with sandbox-first execution, local fallback, and integration tests (`tests/test_python_tool.py`)
- refactored Python tool to a standalone implementation (no external client dependency), reused real sandbox endpoints when available, and expanded tests accordingly
