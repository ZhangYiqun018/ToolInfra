"""Minimal tool registry and schema validation layer."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional, Protocol, Tuple

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    jsonschema = None  # type: ignore


class ToolRegistryError(Exception):
    """Base error for registry operations."""


class ToolRegistrationError(ToolRegistryError):
    """Raised when a tool cannot be registered."""


class ToolNotFoundError(ToolRegistryError):
    """Raised when a requested tool is missing."""


class ToolValidationError(ToolRegistryError):
    """Raised when input or output validation fails."""


class ToolExecutionError(ToolRegistryError):
    """Raised when the tool callable raises an unexpected exception."""


class ToolCallable(Protocol):
    """Callable signature for tool handlers."""

    def __call__(self, payload: Any, context: Optional[dict] = None) -> Any: ...  # pragma: no cover - protocol stub


def _basic_validate(schema: Dict[str, Any], payload: Any, *, location: str) -> None:
    """Fallback validation when jsonschema is unavailable."""
    if schema.get("type") == "object":
        if not isinstance(payload, dict):
            raise ToolValidationError(f"{location} must be an object")

        required: Iterable[str] = schema.get("required", [])
        for key in required:
            if key not in payload:
                raise ToolValidationError(f"{location} missing required field '{key}'")

        properties: Dict[str, Any] = schema.get("properties", {})
        for key, value in payload.items():
            expected = properties.get(key)
            if not expected or "type" not in expected:
                continue
            expected_type = expected["type"]
            if expected_type == "string" and not isinstance(value, str):
                raise ToolValidationError(f"{location} field '{key}' must be a string")
            if expected_type == "number" and not isinstance(value, (int, float)):
                raise ToolValidationError(f"{location} field '{key}' must be a number")
            if expected_type == "integer" and not isinstance(value, int):
                raise ToolValidationError(f"{location} field '{key}' must be an integer")
            if expected_type == "array" and not isinstance(value, list):
                raise ToolValidationError(f"{location} field '{key}' must be an array")
            if expected_type == "object" and not isinstance(value, dict):
                raise ToolValidationError(f"{location} field '{key}' must be an object")
    else:
        if schema.get("type") == "array" and not isinstance(payload, list):
            raise ToolValidationError(f"{location} must be an array")
        if schema.get("type") == "string" and not isinstance(payload, str):
            raise ToolValidationError(f"{location} must be a string")
        if schema.get("type") == "number" and not isinstance(payload, (int, float)):
            raise ToolValidationError(f"{location} must be a number")


def _validate(schema: Dict[str, Any], payload: Any, *, location: str) -> None:
    """Validate payload with JSON Schema when available, otherwise fallback."""
    if schema is None:
        return
    if jsonschema is not None:
        try:
            jsonschema.validate(payload, schema)
        except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
            raise ToolValidationError(f"{location} validation failed: {exc.message}") from exc
    else:
        _basic_validate(schema, payload, location=location)


@dataclass
class ToolDefinition:
    """Metadata and factory for an individual tool."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    factory: Callable[[], ToolCallable]
    tags: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)
    singleton: bool = True


class ToolRegistry:
    """In-memory registry that wires metadata and execution together."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._instances: Dict[str, ToolCallable] = {}
        self._lock = threading.RLock()

    def register(self, tool_def: ToolDefinition, *, overwrite: bool = False) -> None:
        """Register a tool definition."""
        with self._lock:
            if not overwrite and tool_def.name in self._tools:
                raise ToolRegistrationError(f"Tool '{tool_def.name}' already registered")
            self._tools[tool_def.name] = tool_def
            self._instances.pop(tool_def.name, None)

    def list(self) -> Tuple[ToolDefinition, ...]:
        """Return all registered tool definitions."""
        with self._lock:
            return tuple(self._tools.values())

    def get(self, name: str) -> ToolDefinition:
        """Fetch a registered tool definition."""
        with self._lock:
            try:
                return self._tools[name]
            except KeyError as exc:
                raise ToolNotFoundError(f"Tool '{name}' is not registered") from exc

    def invoke(self, name: str, payload: Any, *, context: Optional[dict] = None) -> Any:
        """Validate payload, execute the tool, and validate the response."""
        tool_def = self.get(name)
        _validate(tool_def.input_schema, payload, location=f"Input for tool '{name}'")
        handler = self._get_callable(tool_def)
        try:
            result = handler(payload, context)
        except ToolRegistryError:
            raise
        except Exception as exc:  # pragma: no cover - defensive wrap
            raise ToolExecutionError(f"Tool '{name}' execution failed: {exc}") from exc
        _validate(tool_def.output_schema, result, location=f"Output for tool '{name}'")
        return result

    def _get_callable(self, tool_def: ToolDefinition) -> ToolCallable:
        """Return a callable instance, respecting singleton preference."""
        if tool_def.singleton:
            with self._lock:
                if tool_def.name not in self._instances:
                    self._instances[tool_def.name] = tool_def.factory()
                return self._instances[tool_def.name]
        return tool_def.factory()
