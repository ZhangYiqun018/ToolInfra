"""FastMCP server wiring for ToolInfra."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Iterable, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import ToolAnnotations

from examples.tool_catalog import AVAILABLE_TOOLS
from examples.utils import build_registry, load_cache_from_env
from mcp_server.config import MCPConfig
from mcp_server.signature import build_signature_from_schema
from tool_core import ToolRegistry


def create_mcp_server(config: MCPConfig, *, tool_selection: Optional[Iterable[str]] = None) -> FastMCP:
    """Return a configured FastMCP server that exposes ToolInfra tools."""

    cache_setup = load_cache_from_env()
    registry = ToolRegistry(
        cache_adapter=cache_setup.adapter if cache_setup else None,
        cache_key_generator=cache_setup.key_generator if cache_setup else None,
    )

    selected_tools = tool_selection or config.registry_tools
    registry = build_registry(AVAILABLE_TOOLS, selected_tools, registry=registry)

    server = FastMCP(
        name=config.server_name,
        instructions=config.instructions,
        host=config.host,
        port=config.port,
        streamable_http_path=config.mount_path,
    )

    for tool_def in registry.list():
        if not config.tool_selected(tool_def.name):
            continue
        handler = _build_handler(tool_def.name, registry, tool_def.description, tool_def.input_schema)
        annotations = _build_annotations(tool_def.metadata or {})
        metadata = tool_def.metadata or {}
        meta = {
            "provider": metadata.get("provider"),
            "cacheable": tool_def.cacheable,
            "summary": metadata.get("summary"),
        }
        server.add_tool(
            handler,
            name=tool_def.name,
            description=tool_def.description,
            annotations=annotations,
            meta={key: value for key, value in meta.items() if value not in (None, "")},
        )
    return server


def run_mcp_server(config: MCPConfig) -> None:
    """Create and run the MCP server."""
    server = create_mcp_server(config)
    mount_path = config.mount_path if config.transport == "sse" else None
    server.run(transport=config.transport, mount_path=mount_path)


def _build_handler(
    tool_name: str,
    registry: ToolRegistry,
    description: str,
    input_schema: Dict[str, Any],
) -> Callable[..., Any]:
    """Create a FastMCP handler for the given tool."""

    def handler(**kwargs: Any) -> Any:
        payload = dict(kwargs)
        return registry.invoke(tool_name, payload)

    handler.__name__ = f"{tool_name}_handler"
    handler.__doc__ = description
    signature = build_signature_from_schema(input_schema)
    if signature is not None:
        handler.__signature__ = signature  # type: ignore[attr-defined]
    return handler


def _build_annotations(metadata: Dict[str, Any]) -> Optional[ToolAnnotations]:
    """Map ToolDefinition metadata to FastMCP annotations."""
    if not metadata:
        return None
    read_only = metadata.get("read_only")
    destructive = metadata.get("destructive")
    idempotent = metadata.get("idempotent")
    open_world = metadata.get("open_world")
    if not any(value is not None for value in (read_only, destructive, idempotent, open_world)):
        return None
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )
