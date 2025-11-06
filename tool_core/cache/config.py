"""Configuration models for cache adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
@dataclass
class SQLiteConfig:
    path: str = ".cache/tool_cache.db"
    default_ttl_seconds: Optional[int] = 3600

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SQLiteConfig":
        return cls(**data)


@dataclass
class MySQLConfig:
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "tool_cache"
    table_name: str = "tool_cache_entries"
    charset: str = "utf8mb4"
    autocommit: bool = True
    use_connection_pool: bool = False
    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout: int = 30
    pool_recycle: int = 3600
    default_ttl_seconds: Optional[int] = 3600

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MySQLConfig":
        return cls(**data)


@dataclass
class CacheConfig:
    enabled: bool = False
    default_ttl_seconds: Optional[int] = 3600
    key_prefix: str = "tool_cache"
    backend: str = "sqlite"
    sqlite: Optional[SQLiteConfig] = field(default_factory=SQLiteConfig)
    mysql: Optional[MySQLConfig] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheConfig":
        backend = data.get("backend", "sqlite")
        sqlite_config = data.get("sqlite")
        mysql_config = data.get("mysql")
        return cls(
            enabled=data.get("enabled", False),
            default_ttl_seconds=data.get("default_ttl_seconds"),
            key_prefix=data.get("key_prefix", "tool_cache"),
            backend=backend,
            sqlite=SQLiteConfig.from_dict(sqlite_config) if sqlite_config else SQLiteConfig(),
            mysql=MySQLConfig.from_dict(mysql_config) if mysql_config else None,
        )

    @classmethod
    def disabled(cls) -> "CacheConfig":
        return cls(enabled=False)
