# Changelog

## 2025-11-06
- ensured `examples/registry_openai_demo.py` always records assistant replies in the conversation history while retaining the additional tool result entries after sandbox calls

## 2025-02-14
- scaffolded `tool_core` package with minimal `ToolRegistry`, schema validation, and error handling
- added unit tests (`tests/test_tool_registry.py`) verifying registration, validation failures, and context usage
- documented design direction in `tool_module_development.md` and noted reference project paths
- introduced `tools/python_tool.py` with sandbox-first execution, local fallback, and integration tests (`tests/test_python_tool.py`)
- refactored Python tool to a standalone implementation (no external client dependency), reused real sandbox endpoints when available, and expanded tests accordingly
- added `examples/registry_openai_demo.py` showcasing ToolRegistry with OpenAI completions using prompt-driven tool calls
- updated examples to honor optional `OPENAI_BASE_URL` for custom-compatible endpoints
