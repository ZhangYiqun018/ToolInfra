import os
import unittest

from tool_core import SummarizerError, ToolExecutionError, ToolRegistry
from tools.visit_tool import (
    ABSOLUTE_MAX_CHARS,
    PageContent,
    VisitFetchError,
    create_visit_tool_definition,
)


class _StubFetcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def fetch(self, url, *, max_chars):
        self.calls.append({"url": url, "max_chars": max_chars})
        value = self.mapping.get(url)
        if value is None:
            raise VisitFetchError("missing")
        if isinstance(value, Exception):
            raise value
        return value


class _StubSummarizer:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def summarize(self, *, title: str, content: str, goal: str) -> str:
        self.calls += 1
        return f"{self.response}::{title}::{goal}"


class _FailSummarizer:
    def summarize(self, *, title: str, content: str, goal: str) -> str:
        raise SummarizerError("summary boom")


class VisitToolTests(unittest.TestCase):
    def _make_registry(self, fetcher, summarizer=None):
        registry = ToolRegistry()
        registry.register(
            create_visit_tool_definition(
                fetcher_factory=lambda: fetcher,
                default_max_chars=5_000,
                max_urls=3,
                summary_section_limit=2,
                summarizer_factory=(lambda: summarizer) if summarizer else None,
            )
        )
        return registry

    def test_single_url_visit_success(self):
        content = (
            "Example Domain is a placeholder website used for documentation.\n\n"
            "The example domain explains examples for documentation."
        )
        page = PageContent(
            input_url="https://example.com",
            final_url="https://example.com",
            title="Example Domain",
            content=content,
            source="stub",
            word_count=10,
        )
        fetcher = _StubFetcher({"https://example.com": page})
        registry = self._make_registry(fetcher)

        result = registry.invoke("web_visit", {"url": "https://example.com", "goal": "example domain usage"})

        self.assertEqual(result["requested_urls"], 1)
        entry = result["results"][0]
        self.assertEqual(entry["title"], "Example Domain")
        self.assertEqual(entry["status"], "success")
        self.assertTrue(entry["summary"])

    def test_multiple_urls_and_error_handling(self):
        good_page = PageContent(
            input_url="https://good.com",
            final_url="https://good.com",
            title="Good",
            content="Useful information about good things.",
            source="stub",
            word_count=5,
        )
        fetcher = _StubFetcher(
            {
                "https://good.com": good_page,
                "https://bad.com": VisitFetchError("network boom"),
            }
        )
        registry = self._make_registry(fetcher)

        result = registry.invoke("web_visit", {"url": ["https://good.com", "https://bad.com"]})

        self.assertEqual(result["requested_urls"], 2)
        statuses = [entry["status"] for entry in result["results"]]
        self.assertIn("success", statuses)
        self.assertIn("error", statuses)

    def test_missing_url_field_raises(self):
        fetcher = _StubFetcher({})
        registry = self._make_registry(fetcher)

        with self.assertRaises(ToolExecutionError):
            registry.invoke("web_visit", {"goal": "anything"})

    def test_max_chars_is_clamped(self):
        page = PageContent(
            input_url="https://example.com",
            final_url="https://example.com",
            title="Example Domain",
            content="content",
            source="stub",
            word_count=1,
        )
        fetcher = _StubFetcher({"https://example.com": page})
        registry = self._make_registry(fetcher)

        registry.invoke("web_visit", {"url": "https://example.com", "max_chars": ABSOLUTE_MAX_CHARS + 5_000})

        self.assertEqual(fetcher.calls[0]["max_chars"], ABSOLUTE_MAX_CHARS)

    def test_custom_summarizer_is_used(self):
        content = "Alpha beta gamma.\n\nDelta epsilon."
        page = PageContent(
            input_url="https://example.com",
            final_url="https://example.com",
            title="Example Domain",
            content=content,
            source="stub",
            word_count=5,
        )
        fetcher = _StubFetcher({"https://example.com": page})
        summarizer = _StubSummarizer("RESP")
        registry = self._make_registry(fetcher, summarizer=summarizer)

        result = registry.invoke("web_visit", {"url": "https://example.com", "goal": "alpha"})

        entry = result["results"][0]
        self.assertIn("RESP", entry["summary"])
        self.assertEqual(summarizer.calls, 1)

    def test_summarizer_failure_falls_back_to_heuristic(self):
        content = "Alpha beta gamma.\n\nDelta epsilon."
        page = PageContent(
            input_url="https://example.com",
            final_url="https://example.com",
            title="Example Domain",
            content=content,
            source="stub",
            word_count=5,
        )
        fetcher = _StubFetcher({"https://example.com": page})
        registry = self._make_registry(fetcher, summarizer=_FailSummarizer())

        result = registry.invoke("web_visit", {"url": "https://example.com", "goal": "alpha"})

        entry = result["results"][0]
        self.assertTrue(entry["summary"])


@unittest.skipUnless(os.getenv("RUN_VISIT_INTEGRATION") == "1", "Set RUN_VISIT_INTEGRATION=1 to enable integration test")
class VisitToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            create_visit_tool_definition(
                default_max_chars=2_000,
                max_urls=1,
                summary_section_limit=3,
            )
        )

    def test_visit_example_domain(self):
        result = self.registry.invoke("web_visit", {"url": "https://example.com", "goal": "example domain overview"})
        self.assertEqual(result["requested_urls"], 1)
        self.assertEqual(result["provider"], "jina_reader+fallback")
        self.assertTrue(result["results"])
        first = result["results"][0]
        self.assertEqual(first["status"], "success")
        self.assertIn("Example", first["title"])
        self.assertTrue(first["content"])


if __name__ == "__main__":
    unittest.main()
