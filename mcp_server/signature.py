"""Helpers to convert JSON Schema into FastMCP-compatible function signatures."""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional, Union, get_origin

Schema = Dict[str, Any]


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def _schema_to_annotation(schema: Schema | None) -> Any:
    if not schema:
        return Any
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        options = tuple(_type_from_string(entry, schema) for entry in schema_type)
        return Union[options]  # type: ignore[arg-type]
    if isinstance(schema_type, str):
        return _type_from_string(schema_type, schema)
    if "enum" in schema:
        # fall back to str for enums
        return str
    return Any


def _type_from_string(name: str, schema: Schema) -> Any:
    if name == "array":
        items = schema.get("items")
        inner = _schema_to_annotation(items)
        return List[inner]  # type: ignore[arg-type]
    if name == "object":
        return Dict[str, Any]
    return _TYPE_MAP.get(name, Any)


def build_signature_from_schema(schema: Schema | None) -> Optional[inspect.Signature]:
    """Return a Signature describing the JSON schema."""
    if not schema or schema.get("type") not in (None, "object", ["object"]):
        return None
    properties: Dict[str, Schema] = schema.get("properties") or {}
    if not properties:
        return None
    required = set(schema.get("required") or [])
    params: List[inspect.Parameter] = []
    for name, prop_schema in properties.items():
        annotation = _schema_to_annotation(prop_schema)
        default_provided = "default" in prop_schema
        if default_provided:
            default_value = prop_schema.get("default")
        elif name in required:
            default_value = inspect.Parameter.empty
        else:
            default_value = None
        params.append(
            inspect.Parameter(
                name=name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default_value,
                annotation=annotation,
            )
        )
    if not params:
        return None
    return inspect.Signature(parameters=params)
