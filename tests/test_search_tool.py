import os
import unittest

from tool_core import ToolExecutionError, ToolRegistry, ToolValidationError
from tools.search_tool import (
    SearchClientError,
    SearchResult,
    create_search_tool_definition,
)


class _StubSearchClient:
    def __init__(self):
        self.gl = "us"
        self.hl = "en"
        self.calls = []

    def search(self, query, *, num_results, tbs=None, gl=None, hl=None):
        self.calls.append(
            {
                "query": query,
                "num_results": num_results,
                "tbs": tbs,
                "gl": gl,
                "hl": hl,
            }
        )
        return [
            SearchResult(
                index=1,
                title="Example Title",
                snippet="Example snippet",
                url="https://example.com",
                favicon="https://example.com/favicon.ico",
            )
        ]


class _ErrorSearchClient:
    def __init__(self, exc):
        self.gl = "us"
        self.hl = "en"
        self._exc = exc

    def search(self, query, *, num_results, tbs=None, gl=None, hl=None):
        raise self._exc


class WebSearchToolTests(unittest.TestCase):
    def setUp(self):
        self.stub_client = _StubSearchClient()
        self.registry = ToolRegistry()
        self.registry.register(
            create_search_tool_definition(
                client_factory=lambda: self.stub_client,
                default_num_results=3,
                max_results=5,
            )
        )

    def test_successful_search(self):
        result = self.registry.invoke("web_search", {"query": "python"})

        self.assertEqual(result["query"], "python")
        self.assertEqual(result["requested_results"], 3)
        self.assertEqual(result["returned_results"], 1)
        self.assertEqual(result["provider"], "serper")
        self.assertEqual(len(result["results"]), 1)
        recorded_call = self.stub_client.calls[0]
        self.assertEqual(recorded_call["num_results"], 3)
        self.assertIsNone(recorded_call["tbs"])

    def test_num_results_is_clamped(self):
        result = self.registry.invoke("web_search", {"query": "python", "num_results": 10})
        self.assertEqual(result["requested_results"], 5)
        recorded_call = self.stub_client.calls[-1]
        self.assertEqual(recorded_call["num_results"], 5)

    def test_query_must_not_be_blank(self):
        with self.assertRaises(ToolExecutionError):
            self.registry.invoke("web_search", {"query": "   "})

    def test_input_validation_requires_string(self):
        with self.assertRaises(ToolValidationError):
            self.registry.invoke("web_search", {"query": 123})

    def test_client_error_is_wrapped(self):
        error_registry = ToolRegistry()
        error_registry.register(
            create_search_tool_definition(
                client_factory=lambda: _ErrorSearchClient(SearchClientError("boom")), default_num_results=2
            )
        )
        with self.assertRaises(ToolExecutionError):
            error_registry.invoke("web_search", {"query": "python"})


@unittest.skipUnless(os.getenv("SERPER_API_KEY"), "SERPER_API_KEY not configured")
class WebSearchToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            create_search_tool_definition(
                default_num_results=2,
                max_results=3,
            )
        )

    def test_real_search_request(self):
        result = self.registry.invoke("web_search", {"query": "OpenAI latest news", "num_results": 2})
        self.assertEqual(result["provider"], "serper")
        self.assertGreaterEqual(result["returned_results"], 0)
        if result["results"]:
            first = result["results"][0]
            self.assertIn("url", first)
            self.assertTrue(first["url"])


if __name__ == "__main__":
    unittest.main()
