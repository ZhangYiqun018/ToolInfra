"""Environment-driven configuration for the MCP server."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Set


def _split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, Mapping):
            return data
    except Exception:
        pass
    return {}


@dataclass
class MCPConfig:
    """Runtime configuration for the MCP server."""

    transport: str = "streamable-http"
    host: str = "127.0.0.1"
    port: int = 8000
    mount_path: str = "/mcp"
    server_name: str = "ToolInfra MCP"
    instructions: Optional[str] = None
    auth_token: Optional[str] = None
    registry_tools: Optional[Set[str]] = None
    enabled_tools: Optional[Set[str]] = None
    disabled_tools: Set[str] = field(default_factory=set)
    config_path: Path = Path("config/mcp.json")

    @classmethod
    def from_env(cls) -> "MCPConfig":
        path = Path(os.getenv("MCP_CONFIG_PATH", "config/mcp.json"))
        data = _load_json(path)
        config = cls.from_dict(data, config_path=path)
        config._apply_env_overrides()
        return config

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, config_path: Path) -> "MCPConfig":
        return cls(
            transport=str(data.get("transport", "streamable-http")).strip().lower(),
            host=str(data.get("host", "127.0.0.1")).strip(),
            port=_to_int(data.get("port"), 8000),
            mount_path=str(data.get("mount_path", "/mcp")).strip() or "/mcp",
            server_name=str(data.get("server_name", "ToolInfra MCP")).strip(),
            instructions=data.get("instructions"),
            auth_token=data.get("auth_token") or None,
            registry_tools=_to_set(data.get("tools")),
            enabled_tools=_to_set(data.get("enabled_tools")),
            disabled_tools=_to_set(data.get("disabled_tools")) or set(),
            config_path=config_path,
        )

    def _apply_env_overrides(self) -> None:
        env = os.environ
        if env.get("MCP_TRANSPORT"):
            self.transport = env["MCP_TRANSPORT"].strip().lower()
        if env.get("MCP_HOST"):
            self.host = env["MCP_HOST"].strip()
        if env.get("MCP_PORT"):
            self.port = _to_int(env["MCP_PORT"], self.port)
        if env.get("MCP_MOUNT_PATH"):
            self.mount_path = env["MCP_MOUNT_PATH"].strip() or self.mount_path
        if env.get("MCP_SERVER_NAME"):
            self.server_name = env["MCP_SERVER_NAME"].strip()
        if env.get("MCP_INSTRUCTIONS"):
            self.instructions = env["MCP_INSTRUCTIONS"]
        if env.get("MCP_AUTH_TOKEN"):
            self.auth_token = env["MCP_AUTH_TOKEN"]
        tools_override = _split_csv(env.get("MCP_TOOLS"))
        if tools_override:
            self.registry_tools = set(tools_override)
        enabled_override = _split_csv(env.get("MCP_ENABLED_TOOLS"))
        if enabled_override:
            self.enabled_tools = set(enabled_override)
        disabled_override = _split_csv(env.get("MCP_DISABLED_TOOLS"))
        if disabled_override:
            self.disabled_tools = set(disabled_override)

    def tool_selected(self, name: str) -> bool:
        """Return True if the tool should be exposed."""
        normalized = name.strip()
        if normalized in self.disabled_tools:
            return False
        if self.enabled_tools is not None and normalized not in self.enabled_tools:
            return False
        return True


def _to_set(value: Any) -> Optional[Set[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        items = _split_csv(value)
    elif isinstance(value, Iterable):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        return None
    return set(items) or None
