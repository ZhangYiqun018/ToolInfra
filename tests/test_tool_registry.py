import sqlite3
import tempfile
import unittest
from pathlib import Path

from tool_core import ToolDefinition
from tool_core import ToolNotFoundError
from tool_core import ToolRegistrationError
from tool_core import ToolRegistry
from tool_core import ToolValidationError
from tool_core.cache import InMemoryCacheAdapter, SQLiteCacheAdapter


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


class ToolRegistryCacheTests(unittest.TestCase):
    def setUp(self):
        adapter = InMemoryCacheAdapter()
        self.calls = 0

        def factory():
            def handler(payload, context=None):
                self.calls += 1
                return {"message": payload["text"]}

            return handler

        self.registry = ToolRegistry(cache_adapter=adapter)
        self.registry.register(
            ToolDefinition(
                name="echo_cached",
                description="Cached echo",
                input_schema=ECHO_INPUT_SCHEMA,
                output_schema=ECHO_OUTPUT_SCHEMA,
                factory=factory,
                cacheable=True,
                cache_ttl=30,
            )
        )

    def test_cache_hit_skips_execution(self):
        payload = {"text": "hello"}
        first = self.registry.invoke("echo_cached", payload)
        second = self.registry.invoke("echo_cached", payload)
        self.assertEqual(first, second)
        self.assertEqual(self.calls, 1, "Tool should only execute once due to caching")

    def test_context_changes_key(self):
        payload = {"text": "hello"}
        self.registry.invoke("echo_cached", payload, context={"voice": "formal"})
        self.registry.invoke("echo_cached", payload, context={"voice": "casual"})
        self.assertEqual(self.calls, 2)


class ToolRegistrySQLiteCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "registry_cache.db"
        self.adapter = SQLiteCacheAdapter(db_path)
        self.calls = 0

        def factory():
            def handler(payload, context=None):
                self.calls += 1
                return {"message": payload["text"]}

            return handler

        self.registry = ToolRegistry(cache_adapter=self.adapter)
        self.registry.register(
            ToolDefinition(
                name="echo_sqlite",
                description="Cached echo (sqlite)",
                input_schema=ECHO_INPUT_SCHEMA,
                output_schema=ECHO_OUTPUT_SCHEMA,
                factory=factory,
                cacheable=True,
                cache_ttl=None,
            )
        )

    def tearDown(self):
        self.adapter.close()
        self.temp_dir.cleanup()

    def test_cache_hits_sqlite(self):
        payload = {"text": "hello"}
        first = self.registry.invoke("echo_sqlite", payload)
        second = self.registry.invoke("echo_sqlite", payload)
        self.assertEqual(first, second)
        self.assertEqual(self.calls, 1)

        conn = sqlite3.connect(self.adapter.path)
        rows = conn.execute("SELECT cache_key, value_json, expires_at FROM cache_entries").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0][2])


if __name__ == "__main__":
    unittest.main()
