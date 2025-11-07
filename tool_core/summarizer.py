"""Shared summarizer component for tools that need goal-aware condensing."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol

import requests


DEFAULT_SYSTEM_PROMPT = (
    "You are an assistant that extracts precise evidence from webpages for a research agent. "
    "Always focus on the user's stated goal."
)

DEFAULT_USER_PROMPT = (
    "You will receive a webpage title, a goal, and the cleaned page content.\n"
    "Goal:\n{goal}\n"
    "Title:\n{title}\n"
    "Webpage Content:\n{content}\n\n"
    "Provide a concise summary (<=5 sentences) that highlights the evidence most relevant to the goal. "
    "Avoid speculation and include key facts verbatim when necessary."
)


class SummarizerError(Exception):
    """Raised when the summarizer cannot produce a response."""


class Summarizer(Protocol):
    """Protocol for summarizer implementations."""

    def summarize(self, *, title: str, content: str, goal: str) -> str: ...  # pragma: no cover - protocol stub


@dataclass
class SummarizerConfig:
    """Configuration for the LLM-backed summarizer."""

    enabled: bool = False
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    user_prompt_template: str = DEFAULT_USER_PROMPT
    temperature: float = 0.2
    max_tokens: int = 512
    timeout: int = 60
    max_retries: int = 2
    backoff: float = 0.8
    response_json: bool = False
    max_input_chars: int = 120_000

    @property
    def api_endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if not base:
            raise SummarizerError("Summarizer base URL is not configured.")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def _load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def build_summarizer_config(
    *,
    config_path: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> SummarizerConfig:
    """Merge config file data and environment overrides into a SummarizerConfig."""

    data: Dict[str, Any] = {}
    source_env = env or os.environ
    chosen_path = config_path or source_env.get("SUMMARIZER_CONFIG_PATH")
    if chosen_path:
        data.update(_load_json_file(Path(chosen_path)))

    def _env(name: str, default: Optional[str] = None) -> Optional[str]:
        return source_env.get(name, default)

    enabled = _to_bool(
        _env("SUMMARIZER_ENABLED", str(data.get("enabled", "false")) if data else "false")
    )
    merged = SummarizerConfig(
        enabled=enabled,
        provider=_env("SUMMARIZER_PROVIDER", data.get("provider", "openai_compatible")),
        base_url=_env("SUMMARIZER_BASE_URL", data.get("base_url", "")),
        api_key=_env("SUMMARIZER_API_KEY", data.get("api_key", "")),
        model=_env("SUMMARIZER_MODEL", data.get("model", "")),
        system_prompt=_env("SUMMARIZER_SYSTEM_PROMPT", data.get("system_prompt", DEFAULT_SYSTEM_PROMPT)),
        user_prompt_template=_env(
            "SUMMARIZER_PROMPT_TEMPLATE",
            data.get("user_prompt_template", DEFAULT_USER_PROMPT),
        ),
        temperature=float(_env("SUMMARIZER_TEMPERATURE", data.get("temperature", 0.2))),
        max_tokens=int(_env("SUMMARIZER_MAX_TOKENS", data.get("max_tokens", 512))),
        timeout=int(_env("SUMMARIZER_TIMEOUT", data.get("timeout", 60))),
        max_retries=int(_env("SUMMARIZER_MAX_RETRIES", data.get("max_retries", 2))),
        backoff=float(_env("SUMMARIZER_BACKOFF", data.get("backoff", 0.8))),
        response_json=_to_bool(_env("SUMMARIZER_RESPONSE_JSON", data.get("response_json", False))),
        max_input_chars=int(_env("SUMMARIZER_MAX_INPUT_CHARS", data.get("max_input_chars", 120_000))),
    )
    return merged


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class NoOpSummarizer:
    """Fallback summarizer used when no LLM configuration is provided."""

    def summarize(self, *, title: str, content: str, goal: str) -> str:
        del title, goal
        return ""


class LLMSummarizer:
    """Summarizer that calls an OpenAI-compatible chat completions endpoint."""

    def __init__(self, config: SummarizerConfig, *, session: Optional[requests.Session] = None) -> None:
        if not config.model:
            raise SummarizerError("Summarizer model is not configured.")
        if not config.api_key:
            raise SummarizerError("Summarizer API key is not configured.")
        self.config = config
        self._session = session or requests.Session()

    def summarize(self, *, title: str, content: str, goal: str) -> str:
        text = (content or "").strip()
        if not text:
            return ""
        truncated = text[: max(1, self.config.max_input_chars)]
        prompt = self.config.user_prompt_template.format(
            goal=goal or "Summarize the most important evidence.",
            title=title or "(untitled)",
            content=truncated,
        )
        messages = []
        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.response_json:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Optional[Exception] = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._session.post(
                    self.config.api_endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                data = response.json()
                content_text = self._extract_content(data)
                if not content_text:
                    raise SummarizerError("Summarizer returned empty content.")
                return content_text.strip()
            except (requests.RequestException, ValueError, KeyError, SummarizerError) as exc:
                last_exc = exc
                if attempt == self.config.max_retries:
                    break
                time.sleep(self.config.backoff * (2**attempt))
        raise SummarizerError(f"Summarizer request failed: {last_exc}") from last_exc

    def _extract_content(self, data: Dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise SummarizerError("Summarizer response missing choices.")
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for chunk in content:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    parts.append(chunk.get("text") or "")
            return "\n".join(parts)
        return ""


def create_summarizer_from_env(
    *,
    config_path: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Summarizer]:
    """Return a configured summarizer or None when disabled."""

    config = build_summarizer_config(config_path=config_path, env=env)
    if not config.enabled:
        return None
    if not config.base_url:
        raise SummarizerError("Summarizer is enabled but SUMMARIZER_BASE_URL is not set.")
    provider = config.provider.lower()
    if provider in {"openai", "openai_compatible", "openai-compatible"}:
        return LLMSummarizer(config)
    raise SummarizerError(f"Unsupported summarizer provider '{config.provider}'.")
