"""Demonstration of ToolRegistry with manual tool prompting using OpenAI completions."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path as _Path
from typing import Any, Dict, List

if __package__ in (None, ""):  # pragma: no cover - support direct execution
    sys.path.append(str(_Path(__file__).resolve().parents[1]))

from openai import OpenAI

from tool_core import ToolRegistry
from tools import (
    create_python_tool_definition,
    create_scholar_tool_definition,
    create_search_tool_definition,
    create_visit_tool_definition,
)
from tools.utils import extract_code

try:
    from formatting import ConversationFormatter
    from prompts import TOOL_RESPONSE_TEMPLATE, build_system_prompt
    from utils import (
        DEFAULT_OUTPUT_DIR,
        build_registry,
        export_history,
        load_cache_from_env,
        parse_demo_args,
        current_timestamp,
    )
except ImportError:  # pragma: no cover - support running via `python examples/...`
    from .formatting import ConversationFormatter
    from .prompts import TOOL_RESPONSE_TEMPLATE, build_system_prompt
    from .utils import (
        DEFAULT_OUTPUT_DIR,
        build_registry,
        export_history,
        load_cache_from_env,
        parse_demo_args,
        current_timestamp,
    )

TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

AVAILABLE_TOOLS = {
    "python": create_python_tool_definition,
    "web_search": create_search_tool_definition,
    "scholar_search": create_scholar_tool_definition,
    "web_visit": create_visit_tool_definition,
}


def format_tool_doc(tool_def) -> str:
    descriptor = {
        "type": "function",
        "function": {
            "name": tool_def.name,
            "description": tool_def.description,
            "parameters": tool_def.input_schema,
        },
    }
    return json.dumps(descriptor, ensure_ascii=False)


def record_observation(
    history_log: List[Dict[str, Any]],
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    result: Any,
) -> None:
    history_log.append(
        {
            "role": "observation",
            "tool": tool_name,
            "arguments": arguments,
            "result": result,
            "timestamp": current_timestamp(),
        }
    )


def main() -> None:
    args = parse_demo_args(AVAILABLE_TOOLS.keys(), default_output_dir=DEFAULT_OUTPUT_DIR)

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required")

    cache_setup = load_cache_from_env()
    base_registry = ToolRegistry(
        cache_adapter=cache_setup.adapter if cache_setup else None,
        cache_key_generator=cache_setup.key_generator if cache_setup else None,
    )
    registry = build_registry(AVAILABLE_TOOLS, args.tools, registry=base_registry)
    tool_docs = "\n\n".join(format_tool_doc(tool) for tool in registry.list())
    system_prompt = build_system_prompt(tool_docs)
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    formatter = ConversationFormatter()
    history_log: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt, "timestamp": current_timestamp()},
    ]
    export_on_exit = bool(args.export_history)
    formatter.show("system", system_prompt)

    while True:
        user_input = input("Enter a task (or 'exit'): ").strip()
        lowered = user_input.lower()
        if lowered in {"exit", "quit"}:
            break
        if lowered == "reset":
            messages = [{"role": "system", "content": system_prompt}]
            history_log = [
                {"role": "system", "content": system_prompt, "timestamp": current_timestamp()}
            ]
            formatter.info("Conversation history cleared.")
            formatter.show("system", system_prompt)
            continue
        if lowered in {"export", "output"}:
            file_path = export_history(history_log, model=model, output_dir=args.output_dir)
            formatter.info(f"History exported to {file_path}")
            messages = [{"role": "system", "content": system_prompt}]
            history_log = [
                {"role": "system", "content": system_prompt, "timestamp": current_timestamp()}
            ]
            formatter.info("Conversation history cleared.")
            formatter.show("system", system_prompt)
            continue
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        history_log.append({"role": "user", "content": user_input, "timestamp": current_timestamp()})
        formatter.show("user", user_input)

        while True:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stop=["\n<tool_response>", "<tool_response>"],
                temperature=0.65,
                logprobs=True,
            )
            message = response.choices[0].message
            content = message.content or ""
            formatter.show("assistant", content)
            messages.append({"role": "assistant", "content": content})
            history_log.append({"role": "assistant", "content": content, "timestamp": current_timestamp()})

            tool_calls = TOOL_CALL_PATTERN.findall(content)
            if tool_calls:
                for raw_call in tool_calls:
                    call = json.loads(raw_call)
                    tool_name = call["name"]
                    arguments = dict(call.get("arguments", {}))
                    code = arguments.get("code", "")
                    arguments["code"] = extract_code(code)
                    result = registry.invoke(tool_name, arguments)
                    payload = json.dumps(result, indent=2, ensure_ascii=False)
                    formatter.show("tool", payload, title=f"TOOL RESULT • {tool_name}")
                    messages.append(
                        {
                            "role": "user",
                            "content": TOOL_RESPONSE_TEMPLATE.format(
                                name=tool_name,
                                payload=payload,
                            ),
                        }
                    )
                    record_observation(history_log, tool_name=tool_name, arguments=arguments, result=result)
                continue
            break

    if export_on_exit:
        file_path = export_history(history_log, model=model, output_dir=args.output_dir)
        formatter.info(f"History exported to {file_path}")


if __name__ == "__main__":
    main()
