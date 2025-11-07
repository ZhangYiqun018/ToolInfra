"""Shared catalog of available demo tools."""

from __future__ import annotations

from tools import (
    create_python_tool_definition,
    create_scholar_tool_definition,
    create_search_tool_definition,
    create_visit_tool_definition,
)

AVAILABLE_TOOLS = {
    "python": create_python_tool_definition,
    "web_search": create_search_tool_definition,
    "scholar_search": create_scholar_tool_definition,
    "web_visit": create_visit_tool_definition,
}

__all__ = ["AVAILABLE_TOOLS"]
