"""Web visit tool powered by Jina Reader with HTML fallback."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from tool_core import (
    ToolDefinition,
    ToolExecutionError,
    Summarizer,
    SummarizerError,
    create_summarizer_from_env,
)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_JINA_BASE_URL = "https://r.jina.ai"
DEFAULT_MAX_CHARS = 60_000
ABSOLUTE_MAX_CHARS = 150_000
DEFAULT_MAX_URLS = 5
SUMMARY_SECTION_LIMIT = 4


class VisitFetchError(Exception):
    """Raised when fetching or parsing a page fails."""


@dataclass
class PageContent:
    input_url: str
    final_url: str
    title: str
    content: str
    source: str
    word_count: int


def _normalize_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return value
    parsed = urlparse(value)
    if not parsed.scheme:
        return f"https://{value}"
    return value


def _truncate_text(text: str, limit: Optional[int]) -> str:
    if limit is None or limit <= 0 or len(text) <= limit:
        return text
    trimmed = text[:limit].rstrip()
    suffix = f"\n...[truncated after {limit} characters]"
    return trimmed + suffix


def _unique_preserving_order(items: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _extract_keywords(goal: str) -> List[str]:
    lowered = goal.lower()
    tokens = re.findall(r"[a-z0-9]{3,}", lowered)
    if not tokens:
        tokens = [token for token in lowered.split() if token]
    return _unique_preserving_order(tokens)


class WebPageFetcher:
    """Fetch pages via Jina Reader with BeautifulSoup fallback."""

    def __init__(
        self,
        *,
        jina_base_url: str = DEFAULT_JINA_BASE_URL,
        jina_api_key: str = "",
        timeout: int = 40,
        max_retries: int = 2,
        user_agent: str = DEFAULT_USER_AGENT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.jina_base_url = jina_base_url.rstrip("/")
        self.jina_api_key = jina_api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls, **overrides: Any) -> "WebPageFetcher":
        return cls(
            jina_base_url=overrides.get("jina_base_url")
            or os.getenv("VISIT_JINA_BASE_URL")
            or DEFAULT_JINA_BASE_URL,
            jina_api_key=overrides.get("jina_api_key") or os.getenv("JINA_API_KEY") or "",
            timeout=int(overrides.get("timeout") or os.getenv("VISIT_TIMEOUT") or 40),
            max_retries=int(overrides.get("max_retries") or os.getenv("VISIT_MAX_RETRIES") or 2),
            user_agent=overrides.get("user_agent") or os.getenv("VISIT_USER_AGENT") or DEFAULT_USER_AGENT,
        )

    def fetch(self, url: str, *, max_chars: Optional[int]) -> PageContent:
        normalized = _normalize_url(url)
        if not normalized:
            raise VisitFetchError("URL cannot be empty.")

        last_error: Optional[Exception] = None
        try:
            result = self._fetch_via_jina(normalized, max_chars=max_chars)
            if result:
                return result
        except VisitFetchError as exc:
            last_error = exc

        try:
            fallback = self._fetch_via_http(normalized, max_chars=max_chars)
            if fallback:
                return fallback
        except VisitFetchError as exc:
            last_error = exc

        message = str(last_error) if last_error else "Unable to fetch page content."
        raise VisitFetchError(message)

    # ------------------------------------------------------------------ #
    # Fetch strategies
    # ------------------------------------------------------------------ #
    def _fetch_via_jina(self, url: str, *, max_chars: Optional[int]) -> Optional[PageContent]:
        endpoint = f"{self.jina_base_url}/{url}"
        headers = {"Accept": "application/json"}
        if self.jina_api_key:
            headers["Authorization"] = f"Bearer {self.jina_api_key}"

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.get(endpoint, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                parsed = self._parse_jina_payload(response)
                if not parsed:
                    return None
                title, content, final_url = parsed
                return self._build_page(
                    input_url=url,
                    final_url=final_url or url,
                    title=title or "",
                    content=content,
                    source="jina_reader",
                    max_chars=max_chars,
                )
            except requests.RequestException as exc:
                last_exc = exc
        if last_exc:
            raise VisitFetchError(f"Jina Reader request failed: {last_exc}") from last_exc
        return None

    def _fetch_via_http(self, url: str, *, max_chars: Optional[int]) -> Optional[PageContent]:
        headers = {"User-Agent": self.user_agent}
        try:
            response = self._session.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise VisitFetchError(f"Direct fetch failed: {exc}") from exc

        soup = BeautifulSoup(response.content, "html.parser")
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        text = self._extract_text_from_soup(soup)
        if not text:
            text = soup.get_text(" ", strip=True)
        if not text:
            return None

        return self._build_page(
            input_url=url,
            final_url=response.url or url,
            title=title or "(no title)",
            content=text,
            source="html_fallback",
            max_chars=max_chars,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _parse_jina_payload(
        self,
        response: requests.Response,
    ) -> Optional[tuple[str, str, str]]:
        try:
            data = response.json()
        except ValueError:
            text = response.text.strip()
            if not text:
                return None
            return "", text, response.url

        payload = data.get("data") if isinstance(data, dict) and data.get("data") else data
        if isinstance(payload, dict):
            title = (payload.get("title") or payload.get("meta", {}).get("title") or "").strip()
            content = (payload.get("content") or payload.get("text") or payload.get("excerpt") or "").strip()
            final_url = (payload.get("url") or response.url or "").strip()
        elif isinstance(payload, str):
            title = ""
            content = payload.strip()
            final_url = response.url or ""
        else:
            return None

        if not content:
            return None
        return title, content, final_url

    def _extract_text_from_soup(self, soup: BeautifulSoup) -> str:
        blocks: List[str] = []
        for selector in ("article", "main", "section"):
            for tag in soup.find_all(selector):
                text = tag.get_text(" ", strip=True)
                if len(text) >= 120:
                    blocks.append(text)
        if not blocks:
            for tag in soup.find_all(["p", "li"]):
                text = tag.get_text(" ", strip=True)
                if len(text) >= 40:
                    blocks.append(text)
        combined = "\n\n".join(_unique_preserving_order(blocks))
        return combined.strip()

    def _build_page(
        self,
        *,
        input_url: str,
        final_url: str,
        title: str,
        content: str,
        source: str,
        max_chars: Optional[int],
    ) -> PageContent:
        truncated = _truncate_text(content, max_chars)
        word_count = len(truncated.split())
        return PageContent(
            input_url=input_url,
            final_url=final_url or input_url,
            title=title or "(no title)",
            content=truncated,
            source=source,
            word_count=word_count,
        )


class VisitToolCallable:
    """Registry-compatible callable that fetches and summarizes web pages."""

    def __init__(
        self,
        *,
        fetcher_factory: Callable[[], WebPageFetcher],
        default_max_chars: int = DEFAULT_MAX_CHARS,
        absolute_max_chars: int = ABSOLUTE_MAX_CHARS,
        max_urls: int = DEFAULT_MAX_URLS,
        summary_section_limit: int = SUMMARY_SECTION_LIMIT,
        summarizer_factory: Optional[Callable[[], Optional[Summarizer]]] = None,
    ) -> None:
        self._fetcher_factory = fetcher_factory
        self._fetcher: Optional[WebPageFetcher] = None
        self.default_max_chars = default_max_chars
        self.absolute_max_chars = absolute_max_chars
        self.max_urls = max_urls
        self.summary_section_limit = summary_section_limit
        self._summarizer_factory = summarizer_factory or (lambda: create_summarizer_from_env())
        self._summarizer: Optional[Summarizer] = None

    def __call__(self, payload: Dict[str, Any], context: Optional[dict] = None) -> Dict[str, Any]:
        url_value = payload.get("url", payload.get("urls"))
        if url_value is None:
            raise ToolExecutionError("Visit tool requires a 'url' or 'urls' field.")
        urls = self._coerce_url_list(url_value)
        if not urls:
            raise ToolExecutionError("At least one URL must be provided.")
        if len(urls) > self.max_urls:
            raise ToolExecutionError(f"Visit tool can process up to {self.max_urls} URLs per call.")

        goal = (payload.get("goal") or "").strip()
        max_chars = self._sanitize_max_chars(payload.get("max_chars"))
        include_raw_content = self._coerce_return_raw(payload.get("return_raw_content"))
        fetcher = self._get_fetcher()

        results: List[Dict[str, Any]] = []
        for target in urls:
            try:
                page = fetcher.fetch(target, max_chars=max_chars)
                summary = self._summarize(page, goal)
                content_value = page.content if include_raw_content else ""
                results.append(
                    {
                        "input_url": target,
                        "final_url": page.final_url,
                        "title": page.title,
                        "content": content_value,
                        "summary": summary,
                        "source": page.source,
                        "word_count": page.word_count,
                        "status": "success",
                        "error": "",
                    }
                )
            except VisitFetchError as exc:
                results.append(
                    {
                        "input_url": target,
                        "final_url": "",
                        "title": "",
                        "content": "",
                        "summary": "",
                        "source": "",
                        "word_count": 0,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        return {
            "goal": goal,
            "max_chars": max_chars,
            "requested_urls": len(urls),
            "results": results,
            "provider": "jina_reader+fallback",
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _get_fetcher(self) -> WebPageFetcher:
        if self._fetcher is None:
            self._fetcher = self._fetcher_factory()
        return self._fetcher

    def _coerce_url_list(self, value: Any) -> List[str]:
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            candidates = []
            for entry in value:
                if isinstance(entry, str):
                    candidates.append(entry)
                else:
                    raise ToolExecutionError("Each URL must be a string.")
        else:
            raise ToolExecutionError("Field 'url' must be a string or array of strings.")
        normalized = [item.strip() for item in candidates if item and item.strip()]
        return normalized

    def _sanitize_max_chars(self, candidate: Any) -> int:
        limit = self.default_max_chars
        if candidate is not None:
            try:
                limit = int(candidate)
            except (TypeError, ValueError) as exc:
                raise ToolExecutionError("max_chars must be an integer.") from exc
        limit = max(1_000, limit)
        limit = min(limit, self.absolute_max_chars)
        return limit

    def _coerce_return_raw(self, candidate: Any) -> bool:
        if candidate is None:
            return False
        if isinstance(candidate, bool):
            return candidate
        if isinstance(candidate, str):
            value = candidate.strip().lower()
            if value in {"1", "true", "yes", "on"}:
                return True
            if value in {"0", "false", "no", "off"}:
                return False
        raise ToolExecutionError("return_raw_content must be a boolean value.")

    def _summarize(self, page: PageContent, goal: str) -> str:
        if not page.content or not goal:
            return ""
        summarizer = self._get_summarizer()
        if summarizer:
            try:
                return summarizer.summarize(title=page.title, content=page.content, goal=goal)
            except SummarizerError:
                pass
        return self._heuristic_summary(page.content, goal)

    def _heuristic_summary(self, text: str, goal: str) -> str:
        keywords = _extract_keywords(goal)
        if not keywords:
            return ""
        paragraphs = [segment.strip() for segment in re.split(r"\n{2,}", text) if segment.strip()]
        if not paragraphs:
            paragraphs = [text.strip()]
        scored = []
        for index, paragraph in enumerate(paragraphs):
            lower = paragraph.lower()
            score = sum(1 for keyword in keywords if keyword in lower)
            if score:
                scored.append((score, index, paragraph))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = [item[2] for item in scored[: self.summary_section_limit]]
        if not selected:
            selected = paragraphs[: self.summary_section_limit]
        return "\n\n".join(selected)

    def _get_summarizer(self) -> Optional[Summarizer]:
        if self._summarizer is None and self._summarizer_factory:
            self._summarizer = self._summarizer_factory() or None
        return self._summarizer


VISIT_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "description": "Single URL string or array of URLs to visit.",
            "type": ["string", "array"],
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": DEFAULT_MAX_URLS,
        },
        "urls": {
            "description": "Optional alias for url; must be an array of URL strings.",
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": DEFAULT_MAX_URLS,
        },
        "goal": {
            "type": "string",
            "description": "Optional goal describing the information you are trying to extract.",
        },
        "max_chars": {
            "type": "integer",
            "minimum": 1000,
            "description": "Maximum number of characters to keep from each page; values above the internal cap will be truncated.",
        },
        "return_raw_content": {
            "type": ["boolean", "string"],
            "description": "When true, include the raw page content in responses; otherwise summaries omit it.",
        },
    },
}

VISIT_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "max_chars": {"type": "integer"},
        "requested_urls": {"type": "integer"},
        "provider": {"type": "string"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "input_url": {"type": "string"},
                    "final_url": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "summary": {"type": "string"},
                    "source": {"type": "string"},
                    "word_count": {"type": "integer"},
                    "status": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": [
                    "input_url",
                    "final_url",
                    "title",
                    "content",
                    "summary",
                    "source",
                    "word_count",
                    "status",
                    "error",
                ],
            },
        },
    },
    "required": ["goal", "max_chars", "requested_urls", "results", "provider"],
}


def create_visit_tool_definition(
    *,
    fetcher_factory: Optional[Callable[[], WebPageFetcher]] = None,
    summarizer_factory: Optional[Callable[[], Optional[Summarizer]]] = None,
    default_max_chars: int = DEFAULT_MAX_CHARS,
    max_urls: int = DEFAULT_MAX_URLS,
    summary_section_limit: int = SUMMARY_SECTION_LIMIT,
    cache_ttl: Optional[int] = 1_800,
) -> ToolDefinition:
    """Return a ToolDefinition for the visit tool."""

    factory = fetcher_factory or (lambda: WebPageFetcher.from_env())
    summary_factory = summarizer_factory or (lambda: create_summarizer_from_env())
    return ToolDefinition(
        name="web_visit",
        description="Visit webpage(s) via Jina Reader with HTML fallback and return goal-focused excerpts.",
        input_schema=VISIT_INPUT_SCHEMA,
        output_schema=VISIT_OUTPUT_SCHEMA,
        factory=lambda: VisitToolCallable(
            fetcher_factory=factory,
            default_max_chars=default_max_chars,
            max_urls=max_urls,
            summary_section_limit=summary_section_limit,
            summarizer_factory=summary_factory,
        ),
        metadata={"provider": "jina_reader", "summary": "llm_or_heuristic"},
        cacheable=True,
        cache_ttl=cache_ttl,
    )
