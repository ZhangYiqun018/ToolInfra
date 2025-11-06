"""MySQL-backed cache adapter."""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Optional

from .adapter import CacheAdapter, CacheEntry
from .config import MySQLConfig

try:
    import pymysql
except ImportError:  # pragma: no cover - optional dependency
    pymysql = None


class _MySQLConnectionPool:
    """Simple connection pool inspired by the reference implementation."""

    def __init__(
        self,
        connect_func,
        *,
        pool_size: int,
        max_overflow: int,
        pool_timeout: int,
        pool_recycle: int,
    ) -> None:
        self._connect = connect_func
        self._pool = queue.Queue(maxsize=pool_size)
        self._overflow = set()
        self._max_overflow = max_overflow
        self._pool_timeout = pool_timeout
        self._pool_recycle = pool_recycle
        self._lock = threading.Lock()

        for _ in range(pool_size):
            conn = self._create()
            self._pool.put(conn)

    def _create(self):
        conn = self._connect()
        conn._created_at = time.time()  # type: ignore[attr-defined]
        return conn

    def _expired(self, conn) -> bool:
        created = getattr(conn, "_created_at", None)
        if created is None:
            return True
        return (time.time() - created) > self._pool_recycle

    def acquire(self):
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            if self._expired(conn):
                try:
                    conn.close()
                finally:
                    continue
            try:
                conn.ping(reconnect=False)
                return conn
            except Exception:
                continue

        with self._lock:
            if len(self._overflow) < self._max_overflow:
                conn = self._create()
                self._overflow.add(conn)
                return conn

        try:
            conn = self._pool.get(timeout=self._pool_timeout)
            if self._expired(conn):
                try:
                    conn.close()
                finally:
                    return self._create()
            conn.ping(reconnect=False)
            return conn
        except queue.Empty as exc:
            raise RuntimeError("Timed out waiting for MySQL connection") from exc

    def release(self, conn) -> None:
        if conn is None:
            return
        with self._lock:
            if conn in self._overflow:
                self._overflow.remove(conn)
                try:
                    conn.close()
                finally:
                    return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass

    def close(self) -> None:
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            try:
                conn.close()
            except Exception:
                pass
        with self._lock:
            for conn in list(self._overflow):
                try:
                    conn.close()
                except Exception:
                    pass
            self._overflow.clear()


class MySQLCacheAdapter(CacheAdapter):
    """MySQL implementation of the cache adapter."""

    def __init__(self, config: MySQLConfig) -> None:
        if pymysql is None:
            raise RuntimeError("PyMySQL is required for MySQLCacheAdapter. Install pymysql first.")

        self.config = config
        self._pool: Optional[_MySQLConnectionPool] = None
        self._local = threading.local()
        self._ensure_schema()
        if self.config.use_connection_pool:
            self._pool = _MySQLConnectionPool(
                self._connect,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_timeout=self.config.pool_timeout,
                pool_recycle=self.config.pool_recycle,
            )

    # --------------------------------------------------------------------- #
    # Connection helpers
    # --------------------------------------------------------------------- #
    def _connect(self):
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            autocommit=self.config.autocommit,
            charset=self.config.charset,
        )

    def _get_connection(self):
        if self._pool is not None:
            return self._pool.acquire()

        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        try:
            conn.ping(reconnect=True)
        except Exception:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def _return_connection(self, conn) -> None:
        if self._pool is not None:
            self._pool.release(conn)

    def _ensure_schema(self) -> None:
        admin = None
        try:
            admin = pymysql.connect(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                autocommit=True,
            )
            with admin.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{self.config.database}` DEFAULT CHARACTER SET {self.config.charset}")
        finally:
            if admin:
                try:
                    admin.close()
                except Exception:
                    pass

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(self._create_table_sql())
        finally:
            conn.close()

    def _create_table_sql(self) -> str:
        return (
            f"CREATE TABLE IF NOT EXISTS {self.config.table_name} ("
            "  cache_key VARCHAR(128) PRIMARY KEY,"
            "  value_json LONGTEXT NOT NULL,"
            "  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "  ttl_sec INT NULL,"
            "  expires_at TIMESTAMP NULL,"
            "  INDEX (expires_at)"
            f") ENGINE=InnoDB DEFAULT CHARSET={self.config.charset};"
        )

    # --------------------------------------------------------------------- #
    # CacheAdapter API
    # --------------------------------------------------------------------- #
    def get(self, key: str) -> Optional[CacheEntry]:
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT value_json, expires_at FROM {self.config.table_name} WHERE cache_key=%s",
                    (key,),
                )
                row = cur.fetchone()
            if not row:
                return None
            value_json, expires_at = row
            if expires_at is not None:
                # convert to timestamp seconds
                expires_ts = expires_at.timestamp() if hasattr(expires_at, "timestamp") else None
                if expires_ts is not None and expires_ts <= time.time():
                    self.invalidate(key)
                    return None
            value = json.loads(value_json)
            expires_ts = expires_at.timestamp() if expires_at and hasattr(expires_at, "timestamp") else None
            return CacheEntry(value=value, expires_at=expires_ts)
        except Exception:
            return None
        finally:
            if conn is not None:
                self._return_connection(conn)

    def set(self, key: str, value, ttl: Optional[int]) -> None:
        conn = None
        ttl = ttl if ttl is not None else self.config.default_ttl_seconds
        try:
            payload = json.dumps(value, ensure_ascii=False)
            conn = self._get_connection()
            with conn.cursor() as cur:
                if ttl is not None and ttl >= 0:
                    cur.execute(
                        f"INSERT INTO {self.config.table_name} (cache_key, value_json, ttl_sec, expires_at) "
                        "VALUES (%s, %s, %s, NOW() + INTERVAL %s SECOND) "
                        "ON DUPLICATE KEY UPDATE value_json=VALUES(value_json), ttl_sec=VALUES(ttl_sec), expires_at=VALUES(expires_at)",
                        (key, payload, ttl, ttl),
                    )
                else:
                    cur.execute(
                        f"INSERT INTO {self.config.table_name} (cache_key, value_json, ttl_sec, expires_at) "
                        "VALUES (%s, %s, NULL, NULL) "
                        "ON DUPLICATE KEY UPDATE value_json=VALUES(value_json), ttl_sec=NULL, expires_at=NULL",
                        (key, payload),
                    )
        except Exception:
            return None
        finally:
            if conn is not None:
                self._return_connection(conn)

    def invalidate(self, key: Optional[str] = None) -> None:
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                if key is None:
                    cur.execute(f"DELETE FROM {self.config.table_name}")
                else:
                    cur.execute(f"DELETE FROM {self.config.table_name} WHERE cache_key=%s", (key,))
        except Exception:
            return None
        finally:
            if conn is not None:
                self._return_connection(conn)

    def close(self) -> None:
        if self._pool:
            self._pool.close()
            self._pool = None
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None
