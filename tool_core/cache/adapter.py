"""Cache adapter interfaces and helpers."""

from __future__ import annotations

import abc
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional


def _canonical_json(data: Any) -> str:
    """Return canonical JSON string for hashing purposes."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class CacheKeyGenerator:
    """Utility to generate stable cache keys."""

    def __init__(self, prefix: str = "tool_cache") -> None:
        self.prefix = prefix

    def make_key(self, tool_name: str, payload: Any, context: Optional[Mapping[str, Any]] = None) -> str:
        digest = hashlib.sha256()
        digest.update(self.prefix.encode("utf-8"))
        digest.update(b":")
        digest.update(tool_name.encode("utf-8"))
        digest.update(b":payload:")
        digest.update(_canonical_json(payload).encode("utf-8"))
        if context:
            digest.update(b":context:")
            digest.update(_canonical_json(context).encode("utf-8"))
        return digest.hexdigest()


@dataclass
class CacheEntry:
    value: Any
    expires_at: Optional[float] = None


class CacheAdapter(abc.ABC):
    """Abstract cache backend."""

    @abc.abstractmethod
    def get(self, key: str) -> Optional[CacheEntry]:
        """Return cache entry for key if present and fresh."""

    @abc.abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int]) -> None:
        """Store value for key with optional TTL (seconds)."""

    @abc.abstractmethod
    def invalidate(self, key: Optional[str] = None) -> None:
        """Invalidate specific key or entire cache."""

    def close(self) -> None:
        """Cleanup adapter resources."""


class NoOpCacheAdapter(CacheAdapter):
    """Adapter used when caching is disabled."""

    def get(self, key: str) -> Optional[CacheEntry]:
        return None

    def set(self, key: str, value: Any, ttl: Optional[int]) -> None:
        return None

    def invalidate(self, key: Optional[str] = None) -> None:
        return None


class InMemoryCacheAdapter(CacheAdapter):
    """Simple in-memory cache, useful for tests."""

    def __init__(self) -> None:
        self._store: MutableMapping[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[CacheEntry]:
        entry = self._store.get(key)
        if not entry:
            return None
        if entry.expires_at is not None and entry.expires_at <= _now():
            self._store.pop(key, None)
            return None
        return entry

    def set(self, key: str, value: Any, ttl: Optional[int]) -> None:
        expires_at = None
        if ttl is not None and ttl >= 0:
            expires_at = _now() + ttl
        self._store[key] = CacheEntry(value=value, expires_at=expires_at)

    def invalidate(self, key: Optional[str] = None) -> None:
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)


def _now() -> float:
    import time

    return time.time()
