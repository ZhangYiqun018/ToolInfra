# ToolInfra

[简体中文](README.zh-CN.md)

ToolInfra is a lightweight yet extensible tool layer for LLM agents. It focuses on clear contracts (schemas, docs), reliable execution (sandbox-first Python runner, web tooling), and optional infrastructure such as caching, port forwarding, and MCP exposure. The goal is to provide a solid core that can evolve without accumulating governance debt.

## Highlights

- **Structured registry** – `tool_core` registers, validates, and invokes tools with JSON Schema (or a safe fallback) and cache-aware orchestration.
- **Production-ready tools** – Python executor, Serper-backed search, and a Jina Reader + HTML visit tool with optional LLM summarization.
- **Pluggable adapters** – cache backends (memory, SQLite, MySQL), summarizer component, future port-forward/MCP hooks.
- **Tests & examples** – comprehensive unit tests plus example workflows under `examples/`.

## Repository Layout

| Path | Description |
| --- | --- |
| `tool_core/` | Registry, cache adapters, summarizer component, and shared primitives. |
| `tools/` | Concrete tool implementations (`python_tool`, `search_tool`, `visit_tool`). |
| `tests/` | Unit/integration tests (registry, tools, cache, summarizer). |
| `config/` | Cache and summarizer sample configs. |
| `examples/` | Example scripts showing registry usage. |
| `tool_module_development.md` | Design/implementation guide. |
| `changelog.md` | Daily change log. |

## Quick Start

```bash
git clone <repo-url>
cd ToolInfra
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.template .env
# if you want to use cache
cp config/cache.example.json config/cache.json
# if you want to use summarizer
cp config/summary.example.json config/summary.json
```

Fill out `.env` as needed (e.g., sandbox endpoints, API keys). For Linux sandbox issues, run commands with the provided CLI escalation flag.

### Running Tests

```bash
python -m pytest
```

Some suites require credentials or feature flags:

- `SERPER_API_KEY` for real web-search tests.
- `SERPER_API_KEY` (same key) also powers `scholar_search` integration tests.
- `RUN_VISIT_INTEGRATION=1` to hit live websites.
- `SUMMARIZER_ENABLED=true` + `config/summary.json` + `RUN_SUMMARIZER_INTEGRATION=1` for live summarizer calls.

## Configuration Highlights

| Feature | Files / Env | Notes |
| --- | --- | --- |
| Caching | `.env` (`CACHE_*`), `config/cache*.json` | Supports in-memory, SQLite, MySQL adapters. |
| Summarizer | `.env` (`SUMMARIZER_ENABLED`, `SUMMARIZER_CONFIG_PATH`), `config/summary.json` | Enables LLM-backed summarization for visit (falls back to heuristic otherwise). |
| Sandbox | `.env` (`SANDBOX_FUSION_ENDPOINTS`) | Controls the sandbox-first Python runner. |

## Available Tools

- **`web_search`** (`tools/search_tool.py`): Serper API integration with locale overrides, retries, and caching.
- **`scholar_search`** (`tools/scholar_tool.py`): Google Scholar queries via Serper with structured metadata (PDF link, citation counts) and multi-query batching.
- **`python`** (`tools/python_tool.py`): Sandbox-first exec with safe-mode checks and local fallback.
- **`web_visit`** (`tools/visit_tool.py`): Multi-URL fetch via Jina Reader + BeautifulSoup fallback, optional LLM summarization, cache-aware responses. Raw page text stays in the cache, and responses default to summaries only—set `return_raw_content=true` when callers need the original text.

Each tool exposes JSON Schemas for validation/documentation; see `tool_module_development.md` for adding new tools.

## Extending

1. Author your tool callable and schema definitions.
2. Wrap them in a `ToolDefinition` (see existing factories).
3. Register the definition with `ToolRegistry` and add tests under `tests/`.
4. Update docs/changelog as appropriate.

Consult `tool_module_development.md` for architecture details and changelog history.

## Contributing

Issues and PRs are welcome. Please:

- Run `python -m pytest` before submitting.
- Update `changelog.md` and relevant docs when adding features.
- Keep English/Chinese docs (README + guide snippets) in sync.

For questions or roadmap discussions, open an issue referencing the relevant module or design section.
