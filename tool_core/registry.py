"""Minimal tool registry and schema validation layer."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional, Protocol, Tuple

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    jsonschema = None  # type: ignore

from .cache import CacheAdapter, CacheKeyGenerator, NoOpCacheAdapter


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


def _type_matches(expected: str, value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float))
    if expected == "integer":
        return isinstance(value, int)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "boolean":
        return isinstance(value, bool)
    return False


def _assert_type(expected_type: Any, value: Any, *, location: str, field: Optional[str] = None) -> None:
    """Raise a validation error when the value does not match the expected type(s)."""
    if isinstance(expected_type, (list, tuple)):
        allowed = tuple(str(item) for item in expected_type)
    else:
        allowed = (str(expected_type),)

    for candidate in allowed:
        if _type_matches(candidate, value):
            return

    label = " or ".join(allowed)
    if field:
        raise ToolValidationError(f"{location} field '{field}' must be a {label}")
    raise ToolValidationError(f"{location} must be a {label}")


def _basic_validate(schema: Dict[str, Any], payload: Any, *, location: str) -> None:
    """Fallback validation when jsonschema is unavailable."""
    schema_type = schema.get("type")
    if schema_type == "object":
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
            _assert_type(expected["type"], value, location=location, field=key)
    elif schema_type is not None:
        _assert_type(schema_type, payload, location=location)


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
    cacheable: bool = False
    cache_ttl: Optional[int] = None
    cache_key_fn: Optional[Callable[[Any, Optional[dict]], str]] = None


class ToolRegistry:
    """In-memory registry that wires metadata and execution together."""

    def __init__(
        self,
        *,
        cache_adapter: Optional[CacheAdapter] = None,
        cache_key_generator: Optional[CacheKeyGenerator] = None,
    ) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._instances: Dict[str, ToolCallable] = {}
        self._lock = threading.RLock()
        self._cache_adapter = cache_adapter or NoOpCacheAdapter()
        self._cache_key_generator = cache_key_generator or CacheKeyGenerator()

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

        cached = self._maybe_read_cache(tool_def, payload, context)
        if cached is not None:
            return cached

        handler = self._get_callable(tool_def)
        try:
            result = handler(payload, context)
        except ToolRegistryError:
            raise
        except Exception as exc:  # pragma: no cover - defensive wrap
            raise ToolExecutionError(f"Tool '{name}' execution failed: {exc}") from exc
        _validate(tool_def.output_schema, result, location=f"Output for tool '{name}'")
        self._maybe_store_cache(tool_def, payload, context, result)
        return result

    def _get_callable(self, tool_def: ToolDefinition) -> ToolCallable:
        """Return a callable instance, respecting singleton preference."""
        if tool_def.singleton:
            with self._lock:
                if tool_def.name not in self._instances:
                    self._instances[tool_def.name] = tool_def.factory()
                return self._instances[tool_def.name]
        return tool_def.factory()

    # ------------------------------------------------------------------ #
    # Cache helpers
    # ------------------------------------------------------------------ #
    def _cache_enabled_for(self, tool_def: ToolDefinition) -> bool:
        return tool_def.cacheable and not isinstance(self._cache_adapter, NoOpCacheAdapter)

    def _compute_cache_key(
        self,
        tool_def: ToolDefinition,
        payload: Any,
        context: Optional[dict],
    ) -> Optional[str]:
        try:
            if tool_def.cache_key_fn:
                key = tool_def.cache_key_fn(payload, context)
            else:
                key = self._cache_key_generator.make_key(tool_def.name, payload, context)
            if not key:
                return None
            return key
        except Exception:
            return None

    def _maybe_read_cache(
        self,
        tool_def: ToolDefinition,
        payload: Any,
        context: Optional[dict],
    ) -> Optional[Any]:
        if not self._cache_enabled_for(tool_def):
            return None
        key = self._compute_cache_key(tool_def, payload, context)
        if not key:
            return None
        entry = self._cache_adapter.get(key)
        if entry is None:
            return None
        try:
            _validate(
                tool_def.output_schema,
                entry.value,
                location=f"Cached output for tool '{tool_def.name}'",
            )
        except ToolValidationError:
            self._cache_adapter.invalidate(key)
            return None
        return entry.value

    def _maybe_store_cache(
        self,
        tool_def: ToolDefinition,
        payload: Any,
        context: Optional[dict],
        result: Any,
    ) -> None:
        if not self._cache_enabled_for(tool_def):
            return
        key = self._compute_cache_key(tool_def, payload, context)
        if not key:
            return
        try:
            self._cache_adapter.set(key, result, tool_def.cache_ttl)
        except Exception:
            return
