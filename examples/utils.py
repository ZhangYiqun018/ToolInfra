"""Shared helpers for interactive examples."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Callable

from tool_core import ToolDefinition, ToolRegistry

DEFAULT_OUTPUT_DIR = Path("examples/outputs")


def current_timestamp() -> str:
    """Return the current local timestamp in ISO 8601 format."""
    return dt.datetime.now().isoformat()


def build_registry(
    available_tools: Mapping[str, Callable[[], ToolDefinition]],
    selected_tools: Optional[Iterable[str]],
) -> ToolRegistry:
    """Create a registry containing the requested tools."""
    registry = ToolRegistry()
    selection = list(selected_tools) if selected_tools else list(available_tools.keys())
    unknown = sorted(set(selection) - set(available_tools))
    if unknown:
        raise ValueError(f"Unknown tool(s): {', '.join(unknown)}")

    for tool_name in selection:
        registry.register(available_tools[tool_name]())
    return registry


def parse_demo_args(
    tool_names: Iterable[str],
    *,
    default_output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> argparse.Namespace:
    """Parse common command-line arguments for interactive demos."""
    parser = argparse.ArgumentParser(description="ToolRegistry demo with OpenAI completions.")
    parser.add_argument(
        "--tools",
        nargs="+",
        choices=sorted(tool_names),
        help="Subset of tools to register (defaults to all available tools).",
    )
    parser.add_argument(
        "--export-history",
        action="store_true",
        help="Export chat history to JSON after the session ends.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_dir,
        help="Directory to store exported chat histories (defaults to examples/outputs).",
    )
    return parser.parse_args()


def export_history(
    history: Iterable[Dict[str, Any]],
    *,
    model: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Persist chat history to disk and return the file path."""
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_model = model.replace("/", "-")
    dest_dir = output_dir / safe_model
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_path = dest_dir / f"chat-history-{timestamp}.json"
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(list(history), handle, ensure_ascii=False, indent=2)
    return file_path
