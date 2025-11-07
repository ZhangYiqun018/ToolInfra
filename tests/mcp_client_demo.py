"""Manual MCP client helper for quick verification."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple MCP client to test ToolInfra MCP server.")
    parser.add_argument("--url", help="Full server URL (overrides host/port/path).")
    parser.add_argument("--host", default="127.0.0.1", help="Server host for HTTP transports.")
    parser.add_argument("--port", type=int, default=23445, help="Server port for HTTP transports.")
    parser.add_argument("--path", default="/mcp", help="Base path for streamable-http transport.")
    parser.add_argument("--token", help="Bearer token if the server requires auth.")
    parser.add_argument("--tool", help="Tool name to invoke (optional).")
    parser.add_argument("--payload", help="JSON payload to send when invoking a tool.")
    return parser.parse_args()


def _load_client_class():
    try:
        from mcp.client.fastmcp import FastMCPClient  # type: ignore
    except ImportError as exc:  # pragma: no cover - only triggered when dependency missing
        raise RuntimeError("Install mcp[cli]>=1.2.0 to run the MCP client demo.") from exc
    return FastMCPClient


async def _call_tool(client: Any, name: str, payload: Dict[str, Any]) -> None:
    print(f"\nInvoking tool '{name}' with payload: {payload}")
    result = await client.call_tool(name, payload)
    print("Result:", result)


async def run_client(args: argparse.Namespace) -> None:
    base_url = args.url or f"http://{args.host}:{args.port}{args.path}"
    print(f"Connecting to MCP server at {base_url}")
    FastMCPClient = _load_client_class()

    async with FastMCPClient(server_url=base_url, token=args.token) as client:
        tools = await client.list_tools()
        print("\nAvailable tools:")
        for tool in tools:
            print(f"- {tool.name}: {tool.description}")

        if args.tool:
            payload: Dict[str, Any] = {}
            if args.payload:
                payload = json.loads(args.payload)
            await _call_tool(client, args.tool, payload)


def main() -> None:
    args = parse_args()
    asyncio.run(run_client(args))


if __name__ == "__main__":
    main()
