import json5
import re
import traceback


def print_traceback(is_error: bool = True) -> None:
    """
    Minimal traceback printer.
    When is_error is False it emits the stack without treating it as a failure.
    """
    if is_error:
        traceback.print_exc()
    else:
        try:
            raise Exception("Traceback (most recent call last):")
        except Exception:
            traceback.print_exc()


def extract_code(text: str) -> str:
    """
    Extracts executable Python code from a tool payload.
    Supports Markdown code fences and JSON payloads containing a ``code`` field.
    Falls back to returning the original text when no patterns match.
    """
    if not isinstance(text, str):
        return str(text)

    triple_match = re.search(r"```[^\n]*\n(.+?)```", text, re.DOTALL)
    if triple_match:
        return triple_match.group(1)

    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json5.loads(text)
            if isinstance(data, dict) and "code" in data:
                return data["code"]
        except Exception:
            print_traceback(is_error=False)

    return text
