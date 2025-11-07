"""Interactive demo using the OpenAI Responses API with MCP tools."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

if __package__ in (None, ""):  # pragma: no cover - script execution support
    import sys
    from pathlib import Path as _Path

    sys.path.append(str(_Path(__file__).resolve().parents[1]))

try:
    from formatting import ConversationFormatter
    from prompts import MCP_SYSTEM_PROMPT_TEMPLATE
    from utils import (
        DEFAULT_OUTPUT_DIR,
        export_history,
        parse_demo_args,
        current_timestamp,
    )
except ImportError:  # pragma: no cover
    from .formatting import ConversationFormatter
    from .prompts import MCP_SYSTEM_PROMPT_TEMPLATE
    from .utils import (
        DEFAULT_OUTPUT_DIR,
        export_history,
        parse_demo_args,
        current_timestamp,
    )

from mcp_server import MCPConfig


def _extract_text(response: Any) -> str:
    chunks: List[str] = []
    for item in response.output or []:
        if getattr(item, "type", None) == "message":
            for part in item.content or []:
                if getattr(part, "type", None) == "text":
                    chunks.append(part.text or "")
    return "\n".join(chunks).strip()


def _build_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    return OpenAI(api_key=api_key, base_url=base_url)


def _resolve_mcp_config() -> tuple[str, Optional[str]]:
    override_url = os.getenv("RESPONSES_MCP_URL")
    override_token = os.getenv("RESPONSES_MCP_TOKEN")
    if override_url:
        return override_url.strip(), (override_token.strip() if override_token else None)

    config = MCPConfig.from_env()
    if config.transport != "streamable-http":
        raise RuntimeError(
            "Responses demo expects the MCP server to run with streamable-http transport. "
            "Set RESPONSES_MCP_URL manually if you are using stdio."
        )
    base_url = f"http://{config.host}:{config.port}{config.mount_path}"
    return base_url, config.auth_token


def _build_mcp_tool_spec() -> Dict[str, Any]:
    url, token = _resolve_mcp_config()
    connection: Dict[str, Any] = {"server_url": url}
    if token:
        connection["auth"] = {"type": "bearer", "token": token}
    return {"type": "mcp", "connection": connection}


def main() -> None:
    args = parse_demo_args([], default_output_dir=DEFAULT_OUTPUT_DIR)
    system_prompt = MCP_SYSTEM_PROMPT_TEMPLATE

    formatter = ConversationFormatter()
    client = _build_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    history_log: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt, "timestamp": current_timestamp()}
    ]

    formatter.show("system", system_prompt)
    export_on_exit = bool(args.export_history)

    tool_spec = _build_mcp_tool_spec()

    while True:
        user_input = input("Enter a prompt (or 'exit'): ").strip()
        lowered = user_input.lower()
        if lowered in {"exit", "quit"}:
            break
        if lowered == "reset":
            messages = [{"role": "system", "content": system_prompt}]
            history_log = [
                {"role": "system", "content": system_prompt, "timestamp": current_timestamp()}
            ]
            formatter.info("Conversation reset.")
            formatter.show("system", system_prompt)
            continue
        if lowered in {"export", "output"}:
            path = export_history(history_log, model=model, output_dir=args.output_dir)
            formatter.info(f"History exported to {path}")
            continue
        if not user_input:
            continue

        formatter.show("user", user_input)
        messages.append({"role": "user", "content": user_input})
        history_log.append({"role": "user", "content": user_input, "timestamp": current_timestamp()})

        response = client.responses.create(
            model=model,
            input=messages,
            tools=[tool_spec],
        )
        text = _extract_text(response) or "(empty response)"
        formatter.show("assistant", text)

        messages.append({"role": "assistant", "content": text})
        history_log.append({"role": "assistant", "content": text, "timestamp": current_timestamp()})

    if export_on_exit:
        path = export_history(history_log, model=model, output_dir=args.output_dir)
        formatter.info(f"History exported to {path}")


if __name__ == "__main__":
    main()
