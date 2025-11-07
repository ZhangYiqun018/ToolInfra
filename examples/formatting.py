"""Console formatting helpers for interactive demos."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Optional

ANSI_RESET = "\033[0m"


class ConversationFormatter:
    """Render chat messages with lightweight styling."""

    ROLE_STYLES = {
        "system": {
            "label": "SYSTEM",
            "glyph": "[SYS]",
            "color": "\033[95m",
            "accent": "\033[35m",
            "border_char": "=",
        },
        "user": {
            "label": "USER",
            "glyph": "[USR]",
            "color": "\033[96m",
            "accent": "\033[36m",
            "border_char": "-",
        },
        "assistant": {
            "label": "ASSISTANT",
            "glyph": "[AST]",
            "color": "\033[92m",
            "accent": "\033[32m",
            "border_char": "-",
        },
        "tool": {
            "label": "TOOL",
            "glyph": "[TLS]",
            "color": "\033[93m",
            "accent": "\033[33m",
            "border_char": "-",
        },
        "info": {
            "label": "INFO",
            "glyph": "[INF]",
            "color": "\033[94m",
            "accent": "\033[34m",
            "border_char": "",
        },
    }

    def __init__(self) -> None:
        self.enable_color = self._supports_color()
        width = shutil.get_terminal_size(fallback=(90, 24)).columns
        self.width = max(60, min(width, 110))

    def _supports_color(self) -> bool:
        return sys.stdout.isatty() and os.getenv("NO_COLOR") is None

    def _colorize(self, text: str, color: str) -> str:
        if not color or not self.enable_color:
            return text
        return f"{color}{text}{ANSI_RESET}"

    def _render_block(
        self,
        *,
        role: str,
        label: str,
        glyph: str,
        content: str,
        border_char: str,
        color: str,
        accent_color: str,
    ) -> None:
        header = f"{glyph} {label}"
        if border_char:
            border_line = border_char * self.width
            print(self._colorize(border_line, accent_color))
        print(self._colorize(header, color))

        body_color = color
        lines = content.splitlines() or [""]
        for line in lines:
            print(self._colorize(f"  {line}", body_color))

        if border_char:
            border_line = border_char * self.width
            print(self._colorize(border_line, accent_color))
        print()

    def show(self, role: str, content: str, *, title: Optional[str] = None) -> None:
        """Pretty-print a block for the given role."""
        style = self.ROLE_STYLES.get(role, self.ROLE_STYLES["assistant"])
        label = title or style["label"]
        self._render_block(
            role=role,
            label=label,
            glyph=style.get("glyph", ">>>"),
            content=content,
            border_char=style.get("border_char", ""),
            color=style.get("color", ""),
            accent_color=style.get("accent", style.get("color", "")),
        )

    def info(self, message: str) -> None:
        """Print an informational message block."""
        self.show("info", message)
