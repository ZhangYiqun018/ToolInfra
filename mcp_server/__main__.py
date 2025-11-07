"""CLI entrypoint for the MCP server."""

from __future__ import annotations

import argparse

from mcp_server import MCPConfig, run_mcp_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ToolInfra MCP server.")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], help="Transport to use.")
    parser.add_argument("--host", help="Host binding for HTTP transports.")
    parser.add_argument("--port", type=int, help="Port for HTTP transports.")
    parser.add_argument("--mount-path", help="Mount path for HTTP/SSE transports.")
    parser.add_argument("--tools", help="Comma-separated list of tool names to register.")
    parser.add_argument("--enable-tools", help="Comma-separated allowlist (applied after --tools).")
    parser.add_argument("--disable-tools", help="Comma-separated denylist.")
    parser.add_argument("--instructions", help="Override MCP instructions/system message.")
    parser.add_argument("--name", help="Server name exposed to clients.")
    return parser.parse_args()


def apply_overrides(config: MCPConfig, args: argparse.Namespace) -> MCPConfig:
    if args.transport:
        config.transport = args.transport
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.mount_path:
        config.mount_path = args.mount_path
    if args.tools:
        config.registry_tools = {item.strip() for item in args.tools.split(",") if item.strip()}
    if args.enable_tools:
        config.enabled_tools = {item.strip() for item in args.enable_tools.split(",") if item.strip()}
    if args.disable_tools:
        config.disabled_tools = {item.strip() for item in args.disable_tools.split(",") if item.strip()}
    if args.instructions:
        config.instructions = args.instructions
    if args.name:
        config.server_name = args.name
    return config


def main() -> None:
    config = MCPConfig.from_env()
    args = parse_args()
    config = apply_overrides(config, args)
    run_mcp_server(config)


if __name__ == "__main__":
    main()
