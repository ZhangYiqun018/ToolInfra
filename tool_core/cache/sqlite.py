"""SQLite-backed cache adapter."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .adapter import CacheAdapter, CacheEntry


class SQLiteCacheAdapter(CacheAdapter):
    """SQLite implementation of the cache adapter."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    expires_at REAL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_expires_at ON cache_entries (expires_at)"
            )

    def get(self, key: str) -> Optional[CacheEntry]:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT value_json, expires_at FROM cache_entries WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            expires_at = row["expires_at"]
            if expires_at is not None and expires_at <= time.time():
                self._connection.execute(
                    "DELETE FROM cache_entries WHERE cache_key = ?",
                    (key,),
                )
                return None
            value = json.loads(row["value_json"])
            return CacheEntry(value=value, expires_at=expires_at)

    def set(self, key: str, value, ttl: Optional[int]) -> None:
        expires_at = None
        if ttl is not None and ttl >= 0:
            expires_at = time.time() + ttl
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO cache_entries (cache_key, value_json, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET value_json=excluded.value_json, expires_at=excluded.expires_at
                """,
                (key, payload, expires_at),
            )

    def invalidate(self, key: Optional[str] = None) -> None:
        with self._lock, self._connection:
            if key is None:
                self._connection.execute("DELETE FROM cache_entries")
            else:
                self._connection.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                finally:
                    self._connection = None
