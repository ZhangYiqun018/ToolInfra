"""Shared helpers for interactive examples."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, NamedTuple, Optional

from tool_core import ToolDefinition, ToolRegistry
from tool_core.cache import (
    CacheAdapter,
    CacheConfig,
    CacheKeyGenerator,
    MySQLCacheAdapter,
    SQLiteCacheAdapter,
)

DEFAULT_OUTPUT_DIR = Path("examples/outputs")
DEFAULT_CACHE_CONFIG_PATH = Path("config/cache.json")


class CacheSetup(NamedTuple):
    adapter: CacheAdapter
    key_generator: CacheKeyGenerator


def current_timestamp() -> str:
    """Return the current local timestamp in ISO 8601 format."""
    return dt.datetime.now().isoformat()


def build_registry(
    available_tools: Mapping[str, Callable[[], ToolDefinition]],
    selected_tools: Optional[Iterable[str]],
    *,
    registry: Optional[ToolRegistry] = None,
) -> ToolRegistry:
    """Create a registry containing the requested tools."""
    target = registry or ToolRegistry()
    selection = list(selected_tools) if selected_tools else list(available_tools.keys())
    unknown = sorted(set(selection) - set(available_tools))
    if unknown:
        raise ValueError(f"Unknown tool(s): {', '.join(unknown)}")

    for tool_name in selection:
        target.register(available_tools[tool_name]())
    return target


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


def load_cache_config(path: Path) -> CacheConfig:
    """Load cache configuration from JSON file."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return CacheConfig.from_dict(data)


def load_cache_from_env() -> Optional[CacheSetup]:
    """Return cache adapter/key generator if enabled via environment variables."""
    enabled = os.getenv("CACHE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return None

    config_path = Path(os.getenv("CACHE_CONFIG_PATH", DEFAULT_CACHE_CONFIG_PATH))
    if not config_path.exists():
        raise FileNotFoundError(f"CACHE_CONFIG_PATH points to missing file: {config_path}")

    cache_config = load_cache_config(config_path)
    backend_override = os.getenv("CACHE_BACKEND")
    if backend_override:
        cache_config.backend = backend_override.strip().lower()
    if not cache_config.enabled:
        return None
    key_generator = CacheKeyGenerator(prefix=cache_config.key_prefix)

    backend = cache_config.backend.lower()
    if backend == "mysql":
        if cache_config.mysql is None:
            raise ValueError("Cache configuration missing 'mysql' section.")
        adapter = MySQLCacheAdapter(cache_config.mysql)
    elif backend == "sqlite":
        sqlite_config = cache_config.sqlite or SQLiteConfig()
        adapter = SQLiteCacheAdapter(Path(sqlite_config.path))
    else:
        raise ValueError(f"Unsupported cache backend: {backend}")

    return CacheSetup(adapter=adapter, key_generator=key_generator)
