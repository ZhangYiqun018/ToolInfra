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
- Default implementation: in-process dictionary with TTL support; backends like Redis remain optional plug-ins.
- Tool definition flags: `cacheable: bool`, `cache_key_fn(payload)`, `default_ttl`.
- `invoke` checks `cacheable` before execution: read cache → fall back to execution → write cache if enabled.
- Hooks for future expansion (metrics, distributed locks) remain placeholders only.

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

## Future Extensions (Deferred)
- Multi-tier caching, eviction metrics, adaptive strategies.
- Health checks, heartbeats, dynamic tool onboarding/offboarding.
- Authentication, authorization, rate limiting.
- GUI or web-based tool catalogue.
- Multi-language tool hosting and containerized execution.
