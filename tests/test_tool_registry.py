import unittest

from tool_core import ToolDefinition
from tool_core import ToolNotFoundError
from tool_core import ToolRegistrationError
from tool_core import ToolRegistry
from tool_core import ToolValidationError


class _EchoTool:
    def __call__(self, payload, context=None):
        text = payload["text"]
        if context and context.get("uppercase"):
            text = text.upper()
        return {"message": text}


class _BadOutputTool:
    def __call__(self, payload, context=None):
        return {"message": 42}


def _echo_tool_factory():
    return _EchoTool()


def _bad_output_factory():
    return _BadOutputTool()


ECHO_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
    },
    "required": ["text"],
}

ECHO_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
    },
    "required": ["message"],
}


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            ToolDefinition(
                name="echo",
                description="Simple echo tool",
                input_schema=ECHO_INPUT_SCHEMA,
                output_schema=ECHO_OUTPUT_SCHEMA,
                factory=_echo_tool_factory,
            )
        )

    def test_invoke_success(self):
        result = self.registry.invoke("echo", {"text": "hello"})
        self.assertEqual(result, {"message": "hello"})

    def test_context_is_passed(self):
        result = self.registry.invoke("echo", {"text": "hello"}, context={"uppercase": True})
        self.assertEqual(result, {"message": "HELLO"})

    def test_duplicate_registration_fails(self):
        with self.assertRaises(ToolRegistrationError):
            self.registry.register(
                ToolDefinition(
                    name="echo",
                    description="Duplicate",
                    input_schema=ECHO_INPUT_SCHEMA,
                    output_schema=ECHO_OUTPUT_SCHEMA,
                    factory=_echo_tool_factory,
                )
            )

    def test_input_validation_failure(self):
        with self.assertRaises(ToolValidationError):
            self.registry.invoke("echo", {"text": 123})

    def test_output_validation_failure(self):
        self.registry.register(
            ToolDefinition(
                name="bad_output",
                description="Returns wrong type",
                input_schema=ECHO_INPUT_SCHEMA,
                output_schema=ECHO_OUTPUT_SCHEMA,
                factory=_bad_output_factory,
            )
        )
        with self.assertRaises(ToolValidationError):
            self.registry.invoke("bad_output", {"text": "hi"})

    def test_missing_tool(self):
        with self.assertRaisesRegex(ToolNotFoundError, "Tool 'missing'"):
            self.registry.invoke("missing", {})


if __name__ == "__main__":
    unittest.main()
