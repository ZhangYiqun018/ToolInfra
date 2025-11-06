"""Demonstration of ToolRegistry with manual tool prompting using OpenAI completions."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from openai import OpenAI

from tool_core import ToolRegistry
from tools import create_python_tool_definition
from tools.utils import extract_code

SYSTEM_PROMPT_TEMPLATE = """You are a deep research assistant. Your core function is to conduct thorough, multi-source investigations and, when needed, call the available tools to reach a definitive answer.

# Tools

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{tool_docs}
</tools>

For each function call, respond with a JSON object wrapped inside <tool_call></tool_call> tags:
<tool_call>
{{"name": <function-name>, "arguments": <args-json-object>}}
</tool_call>

Once a tool response is returned (inside <tool_response></tool_response>), incorporate the information and continue reasoning. Deliver the final answer once you have gathered sufficient evidence."""

TOOL_RESPONSE_TEMPLATE = """<tool_response name="{name}">
{payload}
</tool_response>"""

TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(create_python_tool_definition())
    return registry

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

def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required")

    registry = build_registry()
    tool_docs = "\n\n".join(format_tool_doc(tool) for tool in registry.list())
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(tool_docs=tool_docs)
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    print(f"SYSTEM: {system_prompt}\n\n")
    
    while True:
        user_input = input("Enter a task (or 'exit'): ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        while True:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
            )
            message = response.choices[0].message
            content = message.content or ""
            print(content)
            messages.append({"role": "assistant", "content": content})

            tool_calls = TOOL_CALL_PATTERN.findall(content)
            if tool_calls:
                for raw_call in tool_calls:
                    call = json.loads(raw_call)
                    tool_name = call["name"]
                    arguments = call.get("arguments", {})
                    code = arguments.get("code", "")
                    arguments["code"] = extract_code(code)
                    result = registry.invoke(tool_name, arguments)
                    payload = json.dumps(result, indent=2, ensure_ascii=False)
                    print(f"\n[Tool Result - {tool_name}]\n{payload}\n")
                    messages.append(
                        {
                            "role": "user",
                            "content": TOOL_RESPONSE_TEMPLATE.format(
                                name=tool_name,
                                payload=payload,
                            ),
                        }
                    )
                continue

            break


if __name__ == "__main__":
    main()
