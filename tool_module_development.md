# Tool Module Development Guide

## Objective
Build a lightweight yet extensible tool layer for LLM agents, covering registration, schemas, documentation, optional caching, optional port forwarding, and an MCP server adapter. The initial goal is clarity and reliability; advanced governance can land later without accumulating debt.

## Scope
- Focus on the tool ingestion layer: registry, schema validation, documentation, and minimal adapters.
- Business-specific tools, agent policies, and external infra (monitoring, auth) are out of scope for the first iteration.

## Reference Projects
- `DeepResearch/inference`: legacy tool implementations and agent wiring for research workflows.
- `ToolInfra/dr_inference`: copied baseline tool clients and multi-turn orchestration used as initial scaffolding.

## Architecture Overview
- **Tool Registry**: central authority to register, discover, and invoke tools.
- **Schema Layer**: shared request/response contracts powering validation, typing, and documentation.
- **Documentation Generator**: turns tool metadata into human- and machine-readable references.
- **Optional Adapters**: cache, port forwarding, MCP server exposure.
- **Invocation API**: unified `invoke(tool_name, payload, context=None)` entry point consumed by agents or MCP clients.

## Implemented Modules
- **Tool Registry (`tool_core.registry`)**: in-memory registry, JSON Schema validation (with fallback), error taxonomy, and singleton-aware callable lifecycle management.
- **Python Execution Tool (`tools.python_tool`)**: sandbox-first code runner with safety checks, local fallback, and schema-driven contracts.
- **Web Search Tool (`tools.search_tool`)**: Serper-backed organic search integration with configurable locale parameters, retries, and registry-friendly factory helpers.
- **Visit Tool (`tools.visit_tool`)**: fetch webpages through Jina Reader with BeautifulSoup fallback, multi-URL batching, lightweight goal-aware summarization, and registry-level caching toggles.
- **Summarizer Component (`tool_core.summarizer`)**: shared interface that loads LLM-backed or no-op summarizers via JSON config / `SUMMARIZER_*` env vars for tools to reuse.
- **Cache Utilities (`tool_core.cache`)**: adapter interface, in-memory stub, SQLite file-backed storage, PyMySQL backend, and registry-level cache orchestration.

## Core Components

### Tool Registry
- Interfaces: `register(tool_def)`, `get(name)`, `list(filter=None)`, `invoke(name, payload, context=None)`.
- Tool definition payload `ToolDef` minimally includes `name`, `description`, `input_schema`, `output_schema`, `factory`, with optional fields like `version`, `tags`, or `doc_extra`.
- Registration flow stays explicit: decorator or function call. Lazy loading is optional but not required for v0.
- Lifecycle management (health checks, hot-reload) is future work; v0 assumes static registration during process startup.

### Schema Layer
- Recommend authoring schemas in JSON Schema; optionally pair with Pydantic models for developer ergonomics.
- Validation occurs before and after `tool.run` to guarantee contract adherence. Validation errors consolidate into a `ToolValidationError`.
- Schema assets are reused for documentation, MCP metadata, and type hints.

### Documentation Generator
- Input: `ToolDef` plus schema. Output: Markdown sections (purpose, parameters, return value, examples, cache/port notes) and a machine-readable `toolcard.json`.
- Distribution can start with CLI or build-time generation. Rich UI or portals can be added later.

## Optional Adapters (Minimal Baseline)

### Cache Adapter
- Interface: `get(cache_key)`, `set(cache_key, value, ttl=None)`, `invalidate(cache_key=None)`.
- Default implementation: in-process dictionary with TTL support; SQLite and MySQL adapters provide persistent storage; backends like Redis remain optional plug-ins.
- Tool definition flags: `cacheable: bool`, `cache_key_fn(payload)`, `default_ttl`.
- `invoke` checks `cacheable` before execution: read cache → fall back to execution → write cache if enabled.
- Hooks for future expansion (metrics, distributed locks) remain placeholders only.
- Deployment knobs: `.env` toggles caching (`CACHE_ENABLED`), points to the JSON config (`CACHE_CONFIG_PATH`), and can override the backend (`CACHE_BACKEND`).

### Port Forwarding Adapter
- Interface: `ensure_tunnel(target_host, target_port, context=None)` returning a local endpoint.
- Minimal implementation: wrap SSH local port forwarding with simple reuse; credentials managed through existing SSH config.
- Tool flags: `needs_port_forwarding`, `target_endpoint`. Registry resolves the tunnel ahead of invocation and hands the reachable address to the tool.
- Later enhancements (protocol variety, credential brokers, pooling) stay out of the first iteration.

### MCP Server Adapter
- Convert registry data into MCP-compliant endpoints:
  - `list_tools`: serialize `ToolDef` into MCP `Tool` descriptions (name, description, schemas).
  - `call_tool`: accept MCP payload, call `invoke`, return the tool response or structured error.
- Transport: initial HTTP or Unix socket server leveraging lightweight frameworks (FastAPI, Starlette).
- Context propagation: allow `invoke(..., context)` to receive MCP channel/session info; default is empty.
- Metadata extensions (doc URLs, cache hints) can be appended in the MCP description for richer clients.

#### MCP Module Development Notes
- **Module placement**: add a new optional package (e.g., `mcp_server/`) that wires a `ToolRegistry` to MCP routes. This layer depends on FastAPI/Starlette + Uvicorn but keeps `tool_core` free of web dependencies.
- **Registry reuse**: build the registry with existing helpers (`examples.utils.build_registry`, cache loaders, summarizer config). All tool schemas/metadata flow through unchanged.
- **Endpoints**:
  - `GET /mcp/tools`: returns MCP `tool` descriptions (name, description, JSON Schema input/output, metadata flags like `cacheable`, `provider`).
  - `POST /mcp/tools/{name}/invoke`: validates auth/allowlists, forwards payload + context to `ToolRegistry.invoke`, and returns success/error responses matching the MCP spec.
- **Configuration**: expose env vars for binding (`MCP_HOST`, `MCP_PORT`), auth (`MCP_BEARER_TOKEN`, etc.), and tool filtering (`MCP_ENABLED_TOOLS`, `MCP_DISABLED_TOOLS`). Defaults should mirror CLI behavior (all tools enabled, cache honoring existing `.env` flags).
- **Security & policy**: support per-request allowlists by checking headers/tokens and filtering tool access. Reject disabled tools with MCP-compliant error objects.
- **Testing**: add FastAPI `TestClient` suites covering catalog output, successful invocation, validation errors, disabled-tool responses, and auth failures. Reuse stub tools from existing tests to avoid network hits.
- **Docs**: README + README.zh-CN should include a new section on running the MCP server (`uvicorn mcp_server.server:app --host 0.0.0.0 --port 8000`), configuring clients (Claude, GPT-5, etc.), and disabling tools. The development guide should remain the canonical reference for the MCP architecture (this section) and note how to align with community MCP specs.

#### MCP Implementation TODO
1. **Spec alignment**: Review the latest community MCP specification (message formats, transports, auth expectations). Document any deltas we must honor; request the canonical spec link if unavailable locally.
2. **Module scaffold**: Create `mcp_server/` with config loader (env/tool filtering/auth), registry bootstrap (reusing cache/summarizer helpers), and dependency isolation (optional extras for FastAPI/Uvicorn).
3. **Endpoints**: Implement `GET /mcp/tools` and `POST /mcp/tools/{name}/invoke`, including context passthrough, structured error mapping, and per-request allowlist enforcement.
4. **Security & observability**: Add bearer-token or API-key auth, request logging, and basic health checks; ensure disabled tools return MCP-compliant errors.
5. **Testing**: Write FastAPI `TestClient` suites exercising catalog responses, successful tool calls, validation failures, disabled-tool behavior, and auth rejection. Use stub tools to avoid external traffic.
6. **Documentation & examples**: Update READMEs with setup instructions, env vars, client-integration walkthroughs (Claude, GPT-5), and add an example script demonstrating MCP consumption.
7. **Packaging & release**: Record dependencies in `requirements.txt` (or extras), extend `.env.template`, and add changelog entries when the MCP server ships.

### Summarizer Component
- Configured via `config/summary.json` (sample provided) plus dedicated env vars (`SUMMARIZER_ENABLED`, `SUMMARIZER_BASE_URL`, `SUMMARIZER_MODEL`, `SUMMARIZER_API_KEY`, etc.) to avoid conflicts with other LLM settings.
- Default implementation targets OpenAI-compatible `/chat/completions` endpoints with retry/backoff, prompt templating, max-input guards, and optional JSON responses.
- Tools inject the summarizer during factory construction; if unavailable or it fails, they can fall back to heuristic extraction to keep responses stable.

## End-to-End Flow
1. Tool author decorates or registers a class/function with `ToolDef`.
2. Agent requests `invoke("search", payload)`.
3. Registry validates input schema.
4. If the tool needs port forwarding, the adapter provisions the tunnel and injects the reachable endpoint.
5. If caching is enabled, lookup occurs before execution; cache miss leads to tool execution and deferred cache write.
6. Output schema validation runs before returning the payload.
7. MCP adapter, when active, reuses the same flow without additional tool logic.

## Implementation Roadmap
1. Prototype registry, schema validation, and a CLI smoke test.
2. Wire the documentation generator and in-memory cache; onboard a small set of baseline tools (e.g., search, visit, python).
3. Add the basic port forwarding adapter and MCP server overlay; validate end-to-end by calling the MCP interface from a client stub.
4. Plan subsequent iterations (observability, dynamic registration) based on actual usage feedback.

## Testing Strategy
- Unit tests: registry operations, schema validation, cache behavior, port forwarding setup (mock), MCP endpoints.
- Integration tests: exercise a realistic tool suite via both direct `invoke` and MCP calls.
- Ensure adapters are optional: default configuration disables cache and port forwarding to avoid surprising tool authors.
- Testing policy: avoid using mocks when validating tool behaviours; prefer running against real clients or controlled fixtures so results reflect actual execution paths.

## Future Extensions (Deferred)
- Multi-tier caching, eviction metrics, adaptive strategies.
- Health checks, heartbeats, dynamic tool onboarding/offboarding.
- Authentication, authorization, rate limiting.
- GUI or web-based tool catalogue.
- Multi-language tool hosting and containerized execution.
- TODO: Expand `examples` to cover OpenAI SDK `chat.completions` tool calls and the Responses API tool call flow, not just text-prompt driven usage.
- TODO: Consolidate visit/search summarization by pairing a shared `SummaryManager` (central LLM client, retries, monitoring, keyword fallback) with structured outputs (evidence/summary JSON plus raw excerpts), blending the dr_inference and DeepResearch approaches.
