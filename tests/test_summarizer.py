import json
import os
import tempfile
import unittest
from pathlib import Path

import requests

from tool_core import (
    LLMSummarizer,
    SummarizerError,
    build_summarizer_config,
    create_summarizer_from_env,
)


class _StubResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _StubSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self._response


class SummarizerConfigTests(unittest.TestCase):
    def test_build_config_prefers_env_over_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(
                json.dumps(
                    {
                        "enabled": False,
                        "base_url": "https://file-base",
                        "model": "file-model",
                        "api_key": "file-key",
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "SUMMARIZER_ENABLED": "true",
                "SUMMARIZER_BASE_URL": "https://env-base",
                "SUMMARIZER_MODEL": "env-model",
                "SUMMARIZER_API_KEY": "env-key",
            }
            config = build_summarizer_config(config_path=str(path), env=env)

        self.assertTrue(config.enabled)
        self.assertEqual(config.base_url, "https://env-base")
        self.assertEqual(config.model, "env-model")
        self.assertEqual(config.api_key, "env-key")

    def test_create_summarizer_disabled_returns_none(self):
        env = {
            "SUMMARIZER_ENABLED": "false",
        }
        summarizer = create_summarizer_from_env(env=env)
        self.assertIsNone(summarizer)


class LLMSummarizerTests(unittest.TestCase):
    def test_successful_summarization(self):
        config_env = {
            "SUMMARIZER_ENABLED": "true",
            "SUMMARIZER_BASE_URL": "https://api.example.com/v1",
            "SUMMARIZER_MODEL": "demo-model",
            "SUMMARIZER_API_KEY": "sk-test",
        }
        config = build_summarizer_config(env=config_env)
        response = _StubResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "Summary text",
                        }
                    }
                ]
            }
        )
        session = _StubSession(response)
        summarizer = LLMSummarizer(config, session=session)

        result = summarizer.summarize(title="Title", content="Some content", goal="goal")

        self.assertEqual(result, "Summary text")
        self.assertEqual(session.calls[0]["json"]["model"], "demo-model")

    def test_raises_when_request_fails(self):
        config_env = {
            "SUMMARIZER_ENABLED": "true",
            "SUMMARIZER_BASE_URL": "https://api.example.com",
            "SUMMARIZER_MODEL": "demo-model",
            "SUMMARIZER_API_KEY": "sk-test",
            "SUMMARIZER_MAX_RETRIES": "0",
        }
        config = build_summarizer_config(env=config_env)
        response = _StubResponse({}, status_code=500)
        session = _StubSession(response)
        summarizer = LLMSummarizer(config, session=session)

        with self.assertRaises(SummarizerError):
            summarizer.summarize(title="Title", content="c", goal="g")


@unittest.skipUnless(os.getenv("RUN_SUMMARIZER_INTEGRATION") == "1", "Set RUN_SUMMARIZER_INTEGRATION=1 to enable integration test")
class SummarizerIntegrationTests(unittest.TestCase):
    def test_real_endpoint(self):
        summarizer = create_summarizer_from_env()
        if summarizer is None:
            self.skipTest("Summarizer is disabled; configure SUMMARIZER_* settings to run integration test.")
        result = summarizer.summarize(
            title="Example Domain",
            content="Example Domain is used for illustrative examples in documents.",
            goal="Explain what Example Domain is for",
        )
        self.assertTrue(result.strip())


if __name__ == "__main__":
    unittest.main()
