import unittest

from tool_core import ToolExecutionError, ToolRegistry
from tools.scholar_tool import ScholarPaper, ScholarClientError, create_scholar_tool_definition


class _StubScholarClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def search(self, query, num_results):
        self.calls.append({"query": query, "num_results": num_results})
        value = self.responses.get(query)
        if value is None:
            return []
        if isinstance(value, Exception):
            raise value
        return value


class ScholarToolTests(unittest.TestCase):
    def _make_registry(self, responses, **kwargs):
        registry = ToolRegistry()
        registry.register(
            create_scholar_tool_definition(
                client_factory=lambda: _StubScholarClient(responses),
                **kwargs,
            )
        )
        return registry

    def test_single_query_success(self):
        papers = [
            ScholarPaper(
                index=1,
                title="Paper A",
                snippet="A great paper.",
                link="https://example.com/a",
                pdf_url="https://example.com/a.pdf",
                publication_info="Conf 2024",
                year=2024,
                cited_by=42,
                authors="Doe, Smith",
            )
        ]
        registry = self._make_registry({"llm agents": papers})

        result = registry.invoke("scholar_search", {"query": "llm agents"})

        self.assertEqual(result["requested_queries"], ["llm agents"])
        payload = result["response"][0]
        self.assertEqual(payload["query"], "llm agents")
        self.assertEqual(payload["returned_results"], 1)
        self.assertFalse(payload["error"])
        self.assertEqual(payload["results"][0]["title"], "Paper A")

    def test_multiple_queries_with_error(self):
        responses = {
            "graph networks": [
                ScholarPaper(
                    index=1,
                    title="Graph Paper",
                    snippet="graphs",
                    link="https://example.com/graph",
                    pdf_url="https://example.com/graph.pdf",
                    publication_info="NeurIPS",
                    year=2023,
                    cited_by=10,
                    authors="Lee",
                )
            ],
            "missing": ScholarClientError("Serper quota exceeded"),
        }
        registry = self._make_registry(responses)

        result = registry.invoke("scholar_search", {"queries": ["graph networks", "missing"], "max_results": 3})

        self.assertEqual(len(result["response"]), 2)
        success, error_case = result["response"]
        self.assertEqual(success["returned_results"], 1)
        self.assertEqual(error_case["returned_results"], 0)
        self.assertIn("quota", error_case["error"].lower())

    def test_query_limit_enforced(self):
        registry = self._make_registry({}, max_queries=1)
        with self.assertRaises(ToolExecutionError):
            registry.invoke("scholar_search", {"queries": ["a", "b"]})

    def test_alias_string_is_normalized(self):
        papers = [
            ScholarPaper(
                index=1,
                title="X",
                snippet="",
                link="https://x",
                pdf_url="https://x.pdf",
                publication_info="",
                year=None,
                cited_by=None,
                authors="",
            )
        ]
        registry = self._make_registry({"x": papers})

        result = registry.invoke("scholar_search", {"query": "x", "max_results": 10})

        self.assertEqual(result["max_results"], 10)
        self.assertEqual(result["response"][0]["returned_results"], 1)


if __name__ == "__main__":
    unittest.main()
