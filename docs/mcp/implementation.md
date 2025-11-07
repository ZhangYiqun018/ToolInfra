# ToolInfra MCP Implementation Notes

## Goals

- Expose ToolInfra's `ToolRegistry` via MCP so clients (Claude, GPT-5, etc.) can discover and invoke tools.
- Reuse existing infrastructure (schemas, caching, summarizer config) while keeping MCP optional.
- Build on the FastMCP SDK to align with community conventions and minimize boilerplate.

## FastMCP Interfaces We Rely On

- `FastMCP(name: str)` – instantiate the server.
- `FastMCP.add_tool(fn, name=None, title=None, description=None, annotations=None, icons=None, meta=None, structured_output=None)` – programmatically register tool handlers. FastMCP inspects `fn` to auto-generate JSON schemas from type hints (or we can pass our own via `meta`).
- `FastMCP.tool(...)` decorator – syntactic sugar for manual functions (not used for dynamic registry import but useful for hand-written tools).
- `FastMCP.__init__(..., host='127.0.0.1', port=8000, streamable_http_path='/mcp', auth: AuthSettings | None = None, transport_security: TransportSecuritySettings | None = None, ...)` – exposes configurable settings when creating the server (host/port/log levels, SSE paths, optional auth providers).
- `FastMCP.run(transport='stdio'|'sse'|'streamable-http', mount_path=None)` plus async variants (`run_stdio_async`, `run_streamable_http_async`) – start the server using the desired transport. The HTTP flavor spins up Uvicorn with the configured host/port/log level.
- `FastMCP.list_tools()` / `call_tool()` – underlying registry; mainly useful for tests or custom routing.
- Tool plumbing lives in `mcp.server.fastmcp.tools.ToolManager` (methods: `add_tool`, `list_tools`, `call_tool`, `remove_tool`) and `mcp.server.fastmcp.tools.base.Tool` which stores:
  - `fn`, `name`, `description`, `parameters` (JSON schema derived from signature), `fn_metadata`, `is_async`, `context_kwarg`.
  - optional `annotations` (`ToolAnnotations`), `icons`, `meta`.
  - `fn_metadata` is a `FuncMetadata` object (with `arg_model`, optional `output_model`/`output_schema`, helpers to validate inputs and convert structured results). FastMCP auto-builds schemas from type hints:  
    - Plain `**payload: dict[str, Any]` yields `{ "payload": { "type": "object", "additionalProperties": true } }`.  
    - Passing a single `BaseModel` parameter produces `$defs` with nested properties, so we can wrap each tool's JSON payload into a single model if needed.  
    - We can also override `__signature__` on bridge functions to force keyword-only named params that mirror our JSON Schema fields.

### MCP Type Reference

- `mcp.types.Tool`: serialized descriptor with `name`, `description`, `inputSchema`, optional `outputSchema`, `icons`, `annotations`, `meta`.
- `mcp.types.ToolAnnotations`: hints such as `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`, etc.
- FastMCP handles JSON-RPC request/response objects (`CallToolRequest`, `CallToolResult`, etc.); we mainly provide the handler function and return value.

## Tool Registration Strategy

1. Build a `ToolRegistry` via existing helpers (`examples.utils.build_registry`, cache loaders, summarizer env).
2. Loop through `registry.list()`:
   - Generate a FastMCP-compatible handler that:
     - Accepts typed kwargs (matching the tool schema) or a `dict` argument.
     - Calls `registry.invoke(tool.name, payload, context_dict)`; propagate FastMCP context if useful.
     - Returns the registry result (FastMCP will convert to JSON for clients).
   - Provide metadata: `description`, `annotations` (read-only vs. destructive), `meta` (provider, cacheable, docs URL).
3. Register each handler with `FastMCP.add_tool` using the ToolDefinition name.

## Configuration Surface

- Primary config lives in `config/mcp.json` (copy from `config/mcp.example.json`). Fields include `transport`, `host`, `port`, `mount_path`, `server_name`, `instructions`, `auth_token`, `tools`, `enabled_tools`, `disabled_tools`.
- `.env` only needs `MCP_CONFIG_PATH` to point to an alternate file. Legacy keys (`MCP_TRANSPORT`, etc.) remain as optional overrides (useful for CI or one-off tweaks).
- Reuse existing `.env` toggles (cache, summarizer, etc.) so behavior matches CLI demos.

When HTTP transport is used, we can rely on FastMCP's `AuthSettings` + `TokenVerifier` plumbing if we need more advanced auth later; for now, a simple bearer-token check based on `auth_token` suffices.

## Auth & Filtering

- If `MCP_AUTH_TOKEN` is set, enforce `Authorization: Bearer <token>` for all HTTP/SSE requests.
- Apply allow/deny lists at registration time and double-check during `call_tool`.
- Consider role-based filtering by mapping tokens to tool sets (future enhancement).

## Testing Plan

- Use FastAPI/Starlette TestClient (FastMCP exposes ASGI apps) to hit `/tools/list` and `/tools/call`.
- Stub the registry with fake tools to avoid network/LLM dependencies.
- Cases to cover: success path, validation error from registry, disabled tool request, auth failure, context propagation.

## Documentation & Samples

- README (EN/ZH) section: how to start the MCP server (`uvicorn mcp_server.app:app` or `python -m mcp_server --transport stdio`), env vars, connecting from Claude/GPT clients, disabling tools.
- `.env.template`: add `MCP_*` knobs.
- Example script (`examples/mcp_registry_demo.py`) showing how to connect via FastMCP client or Claude config snippet.
- Changelog entry once feature lands.

## Open Questions / Follow-ups

- Default transport (stdio required for Claude Desktop, HTTP for general agentic stacks) – might need both entrypoints.
- Resource/Prompt support – plan for later (FastMCP exposes `add_resource`, `add_prompt` we can hook into once registry has equivalents).
- Logging – follow FastMCP guidance (no stdout when running stdio transport).
