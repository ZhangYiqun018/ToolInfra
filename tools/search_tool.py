"""Web search tool using the Serper API."""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

from tool_core import ToolDefinition, ToolExecutionError


class SearchClientError(Exception):
    """Raised when the underlying search client fails."""


@dataclass
class SearchResult:
    index: int
    title: str
    snippet: str
    url: str
    favicon: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "favicon": self.favicon or "",
        }


class SerperSearchClient:
    """Thin wrapper around the Serper Google Search API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://google.serper.dev",
        gl: str = "us",
        hl: str = "en",
        timeout: int = 15,
        max_retries: int = 2,
        backoff: float = 0.6,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not api_key:
            raise SearchClientError("SERPER_API_KEY is required for the search tool.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.gl = gl
        self.hl = hl
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }
        )

    @classmethod
    def from_env(cls, **overrides: Any) -> "SerperSearchClient":
        api_key = overrides.pop("api_key", None) or os.getenv("SERPER_API_KEY") or ""
        base_url = overrides.pop("base_url", None) or os.getenv("SERPER_API_BASE_URL") or "https://google.serper.dev"
        gl = overrides.pop("gl", None) or os.getenv("SERPER_API_GL") or "us"
        hl = overrides.pop("hl", None) or os.getenv("SERPER_API_HL") or "en"
        return cls(api_key=api_key, base_url=base_url, gl=gl, hl=hl, **overrides)

    def search(
        self,
        query: str,
        *,
        num_results: int,
        tbs: Optional[str] = None,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
    ) -> List[SearchResult]:
        payload: Dict[str, Any] = {
            "q": query,
            "gl": gl or self.gl,
            "hl": hl or self.hl,
            "num": num_results,
        }
        if tbs:
            payload["tbs"] = tbs

        url = f"{self.base_url}/search"
        data: Optional[Dict[str, Any]] = None
        response: Optional[requests.Response] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.post(url, json=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                break
            except requests.HTTPError as exc:
                body = ""
                try:
                    body = response.text
                except Exception:
                    body = ""
                if response.status_code in (401, 403):
                    raise SearchClientError(f"Serper authentication failed: {body or response.reason}") from exc
                if attempt == self.max_retries:
                    raise SearchClientError(
                        f"Serper returned {response.status_code}: {body or response.reason}"
                    ) from exc
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    raise SearchClientError(f"Serper request failed: {exc}") from exc
            time.sleep(self.backoff * (2 ** attempt) + random.uniform(0, 0.3))

        organic: Iterable[Dict[str, Any]] = (data or {}).get("organic") or []
        results: List[SearchResult] = []
        for idx, item in enumerate(organic, start=1):
            if idx > num_results:
                break
            title = (item.get("title") or "").strip()
            snippet = (item.get("snippet") or item.get("description") or "").strip()
            url_value = (item.get("link") or item.get("url") or "").strip()
            favicon = (item.get("faviconUrl") or item.get("favicon_url") or "").strip() or None
            if not url_value:
                continue
            results.append(
                SearchResult(
                    index=idx,
                    title=title or "(no title)",
                    snippet=snippet,
                    url=url_value,
                    favicon=favicon,
                )
            )
        return results


class SearchToolCallable:
    """Registry-compatible callable for performing Serper searches."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], SerperSearchClient],
        default_num_results: int = 5,
        max_results: int = 10,
    ) -> None:
        self._client_factory = client_factory
        self._client: Optional[SerperSearchClient] = None
        self.default_num_results = default_num_results
        self.max_results = max_results

    def __call__(self, payload: Dict[str, Any], context: Optional[dict] = None) -> Dict[str, Any]:
        query: str = payload["query"].strip()
        if not query:
            raise ToolExecutionError("Search query cannot be empty.")

        requested_num = payload.get("num_results") or self.default_num_results
        num_results = max(1, min(int(requested_num), self.max_results))
        tbs = payload.get("tbs")
        gl = payload.get("gl")
        hl = payload.get("hl")

        client = self._get_client()
        try:
            results = client.search(query, num_results=num_results, tbs=tbs, gl=gl, hl=hl)
        except SearchClientError as exc:
            message = str(exc)
            if "Not enough credits" in message or "quota" in message.lower():
                return {
                    "query": query,
                    "requested_results": num_results,
                    "returned_results": 0,
                    "results": [],
                    "provider": "serper",
                    "tbs": tbs or "",
                    "gl": gl or client.gl,
                    "hl": hl or client.hl,
                    "error": message,
                }
            raise ToolExecutionError(message) from exc

        return {
            "query": query,
            "requested_results": num_results,
            "returned_results": len(results),
            "results": [item.to_payload() for item in results],
            "provider": "serper",
            "tbs": tbs or "",
            "gl": gl or client.gl,
            "hl": hl or client.hl,
        }

    def _get_client(self) -> SerperSearchClient:
        if self._client is None:
            try:
                self._client = self._client_factory()
            except SearchClientError as exc:
                raise ToolExecutionError(str(exc)) from exc
        return self._client


SEARCH_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query string.",
        },
        "num_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": "Maximum number of organic results to return (1-10).",
        },
        "tbs": {
            "type": "string",
            "description": "Optional Google time range spec (e.g. 'qdr:d' for last day).",
        },
        "gl": {
            "type": "string",
            "description": "Country code override for the search request.",
        },
        "hl": {
            "type": "string",
            "description": "Language override for the search request.",
        },
    },
    "required": ["query"],
}

SEARCH_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "requested_results": {"type": "integer"},
        "returned_results": {"type": "integer"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "snippet": {"type": "string"},
                    "url": {"type": "string"},
                    "favicon": {"type": "string"},
                },
                "required": ["index", "title", "url", "snippet"],
            },
        },
        "provider": {"type": "string"},
        "tbs": {"type": "string"},
        "gl": {"type": "string"},
        "hl": {"type": "string"},
    },
    "required": [
        "query",
        "requested_results",
        "returned_results",
        "results",
        "provider",
        "tbs",
        "gl",
        "hl",
    ],
}


def create_search_tool_definition(
    *,
    client_factory: Optional[Callable[[], SerperSearchClient]] = None,
    default_num_results: int = 5,
    max_results: int = 10,
) -> ToolDefinition:
    """Return a ToolDefinition for the Serper-backed web search tool."""

    factory = client_factory or (lambda: SerperSearchClient.from_env())

    return ToolDefinition(
        name="web_search",
        description="Perform a web search using the Serper Google Search API.",
        input_schema=SEARCH_INPUT_SCHEMA,
        output_schema=SEARCH_OUTPUT_SCHEMA,
        factory=lambda: SearchToolCallable(
            client_factory=factory,
            default_num_results=default_num_results,
            max_results=max_results,
        ),
        metadata={"provider": "serper"},
    )
