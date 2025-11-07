"""Google Scholar search tool powered by the Serper API."""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

from tool_core import ToolDefinition, ToolExecutionError


class ScholarClientError(Exception):
    """Raised when the underlying scholar client fails."""


@dataclass
class ScholarPaper:
    index: int
    title: str
    snippet: str
    link: str
    pdf_url: str
    publication_info: str
    year: Optional[int]
    cited_by: Optional[int]
    authors: str

    def to_payload(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "snippet": self.snippet,
            "link": self.link,
            "pdf_url": self.pdf_url,
            "publication_info": self.publication_info,
            "year": self.year if self.year is not None else 0,
            "cited_by": self.cited_by if self.cited_by is not None else 0,
            "authors": self.authors,
        }


class SerperScholarClient:
    """Thin wrapper around the Serper Google Scholar API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://google.serper.dev",
        timeout: int = 20,
        max_retries: int = 2,
        backoff: float = 0.6,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not api_key:
            raise ScholarClientError("SERPER_API_KEY is required for the scholar tool.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
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
    def from_env(cls, **overrides: Any) -> "SerperScholarClient":
        api_key = overrides.pop("api_key", None) or os.getenv("SERPER_API_KEY") or ""
        base_url = overrides.pop("base_url", None) or os.getenv("SERPER_API_BASE_URL") or "https://google.serper.dev"
        return cls(api_key=api_key, base_url=base_url, **overrides)

    def search(self, query: str, *, num_results: int) -> List[ScholarPaper]:
        payload: Dict[str, Any] = {"q": query, "num": num_results}
        url = f"{self.base_url}/scholar"
        response: Optional[requests.Response] = None
        data: Optional[Dict[str, Any]] = None

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
                    raise ScholarClientError(f"Serper authentication failed: {body or response.reason}") from exc
                if attempt == self.max_retries:
                    raise ScholarClientError(
                        f"Serper returned {response.status_code}: {body or response.reason}"
                    ) from exc
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    raise ScholarClientError(f"Serper request failed: {exc}") from exc
            time.sleep(self.backoff * (2 ** attempt) + random.uniform(0, 0.3))

        organic: Iterable[Dict[str, Any]] = (data or {}).get("organic") or []
        results: List[ScholarPaper] = []
        for idx, item in enumerate(organic, start=1):
            if idx > num_results:
                break
            title = (item.get("title") or "").strip() or "(no title)"
            snippet = (item.get("snippet") or "").strip()
            pdf_url = (item.get("pdfUrl") or "").strip()
            link = (pdf_url or item.get("link") or item.get("url") or "").strip()
            publication_info = (item.get("publicationInfo") or "").strip()
            year_value = item.get("year")
            year = None
            if isinstance(year_value, int):
                year = year_value
            elif isinstance(year_value, str):
                try:
                    year = int(year_value)
                except ValueError:
                    year = None
            cited = item.get("citedBy")
            cited_by = None
            if isinstance(cited, int):
                cited_by = cited
            elif isinstance(cited, str):
                try:
                    cited_by = int(cited)
                except ValueError:
                    cited_by = None
            authors_value = item.get("authors")
            if isinstance(authors_value, list):
                authors = ", ".join(str(entry).strip() for entry in authors_value if str(entry).strip())
            else:
                authors = (authors_value or "").strip()
            results.append(
                ScholarPaper(
                    index=idx,
                    title=title,
                    snippet=snippet,
                    link=link or pdf_url or "",
                    pdf_url=pdf_url,
                    publication_info=publication_info,
                    year=year,
                    cited_by=cited_by,
                    authors=authors,
                )
            )
        return results


class ScholarToolCallable:
    """Registry-compatible callable for Serper Google Scholar searches."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], SerperScholarClient],
        default_num_results: int = 5,
        max_results: int = 10,
        max_queries: int = 5,
    ) -> None:
        self._client_factory = client_factory
        self._client: Optional[SerperScholarClient] = None
        self.default_num_results = default_num_results
        self.max_results = max_results
        self.max_queries = max_queries

    def __call__(self, payload: Dict[str, Any], context: Optional[dict] = None) -> Dict[str, Any]:
        queries = self._coerce_queries(payload)
        if not queries:
            raise ToolExecutionError("At least one scholar query must be provided.")
        if len(queries) > self.max_queries:
            raise ToolExecutionError(f"Scholar tool supports up to {self.max_queries} queries per call.")

        requested_num = payload.get("max_results") or self.default_num_results
        num_results = max(1, min(int(requested_num), self.max_results))

        client = self._get_client()
        per_query: List[Dict[str, Any]] = []
        for query in queries:
            try:
                papers = client.search(query, num_results=num_results)
                per_query.append(
                    {
                        "query": query,
                        "returned_results": len(papers),
                        "results": [paper.to_payload() for paper in papers],
                        "error": "",
                    }
                )
            except ScholarClientError as exc:
                per_query.append(
                    {
                        "query": query,
                        "returned_results": 0,
                        "results": [],
                        "error": str(exc),
                    }
                )

        return {
            "requested_queries": queries,
            "max_results": num_results,
            "provider": "serper_scholar",
            "response": per_query,
        }

    def _coerce_queries(self, payload: Dict[str, Any]) -> List[str]:
        queries_value = payload.get("queries")
        if queries_value is None:
            single = payload.get("query")
            if single is None:
                return []
            queries_value = [single]
        if isinstance(queries_value, str):
            queries = [queries_value]
        elif isinstance(queries_value, list):
            queries = []
            for entry in queries_value:
                if not isinstance(entry, str):
                    raise ToolExecutionError("Each scholar query must be a string.")
                queries.append(entry)
        else:
            raise ToolExecutionError("Field 'queries' must be a string or list of strings.")
        normalized = [item.strip() for item in queries if item and item.strip()]
        return normalized

    def _get_client(self) -> SerperScholarClient:
        if self._client is None:
            try:
                self._client = self._client_factory()
            except ScholarClientError as exc:
                raise ToolExecutionError(str(exc)) from exc
        return self._client


SCHOLAR_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": ["array", "string"],
            "description": "One or more scholar queries (string or list of strings).",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
        },
        "query": {
            "type": "string",
            "description": "Alias for 'queries' when only one query is provided.",
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": "Maximum number of papers to return per query (1-10).",
        },
    },
    "required": [],
}

SCHOLAR_RESULT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "index": {"type": "integer"},
        "title": {"type": "string"},
        "snippet": {"type": "string"},
        "link": {"type": "string"},
        "pdf_url": {"type": "string"},
        "publication_info": {"type": "string"},
        "year": {"type": "integer"},
        "cited_by": {"type": "integer"},
        "authors": {"type": "string"},
    },
    "required": ["index", "title", "snippet", "link", "pdf_url", "publication_info", "year", "cited_by", "authors"],
}

SCHOLAR_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "requested_queries": {"type": "array", "items": {"type": "string"}},
        "max_results": {"type": "integer"},
        "provider": {"type": "string"},
        "response": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "returned_results": {"type": "integer"},
                    "results": {"type": "array", "items": SCHOLAR_RESULT_SCHEMA},
                    "error": {"type": "string"},
                },
                "required": ["query", "returned_results", "results", "error"],
            },
        },
    },
    "required": ["requested_queries", "max_results", "provider", "response"],
}


def create_scholar_tool_definition(
    *,
    client_factory: Optional[Callable[[], SerperScholarClient]] = None,
    default_num_results: int = 5,
    max_results: int = 10,
    max_queries: int = 5,
) -> ToolDefinition:
    """Return a ToolDefinition for the Serper-backed Google Scholar tool."""

    factory = client_factory or (lambda: SerperScholarClient.from_env())

    return ToolDefinition(
        name="scholar_search",
        description="Search academic papers via Google Scholar using the Serper API.",
        input_schema=SCHOLAR_INPUT_SCHEMA,
        output_schema=SCHOLAR_OUTPUT_SCHEMA,
        factory=lambda: ScholarToolCallable(
            client_factory=factory,
            default_num_results=default_num_results,
            max_results=max_results,
            max_queries=max_queries,
        ),
        metadata={"provider": "serper_scholar"},
        cacheable=True,
        cache_ttl=None,
    )
