import inspect
from typing import Union, get_args, get_origin

from mcp_server.signature import build_signature_from_schema


def test_signature_from_simple_schema():
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "num_results": {"type": "integer", "default": 3},
        },
        "required": ["query"],
    }
    signature = build_signature_from_schema(schema)
    assert signature is not None
    params = signature.parameters
    assert params["query"].annotation is str
    assert params["query"].default is inspect.Parameter.empty
    assert params["num_results"].annotation is int
    assert params["num_results"].default == 3


def test_signature_handles_union_types():
    schema = {
        "type": "object",
        "properties": {"url": {"type": ["string", "array"], "items": {"type": "string"}}},
    }
    signature = build_signature_from_schema(schema)
    assert signature is not None
    annotation = signature.parameters["url"].annotation
    assert get_origin(annotation) is Union
    args = get_args(annotation)
    assert str in args
    # list[str] becomes typing.List[str]; we just ensure list is represented
    assert any(get_origin(arg) is list or arg is list for arg in args)


def test_signature_falls_back_when_empty():
    signature = build_signature_from_schema(None)
    assert signature is None
