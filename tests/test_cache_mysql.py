import json
import os
import time
import unittest
from dataclasses import replace
from pathlib import Path

import pymysql  # type: ignore

from tool_core.cache import CacheConfig, MySQLCacheAdapter

CACHE_CONFIG_ENV = "CACHE_CONFIG_PATH"
DEFAULT_CACHE_PATH = Path("config/cache.json")


def _load_cache_config(path: Path) -> CacheConfig:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return CacheConfig.from_dict(data)


class MySQLCacheAdapterIntegrationTests(unittest.TestCase):
    def setUp(self):
        env_path = os.getenv(CACHE_CONFIG_ENV)
        path = Path(env_path) if env_path else DEFAULT_CACHE_PATH
        if not path.exists():
            self.fail(
                f"Cache configuration file not found. Provide {CACHE_CONFIG_ENV} or create {DEFAULT_CACHE_PATH} for integration tests."
            )
        cache_config = _load_cache_config(path)
        if cache_config.mysql is None:
            self.fail("Cache configuration file must contain a 'mysql' section.")

        mysql_config = replace(
            cache_config.mysql,
            table_name=f"tool_cache_test_{int(time.time())}",
            use_connection_pool=False,
        )
        self.config = mysql_config
        self.adapter = MySQLCacheAdapter(mysql_config)

    def tearDown(self):
        try:
            conn = pymysql.connect(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                database=self.config.database,
                autocommit=True,
                charset=self.config.charset,
            )
            with conn.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {self.config.table_name}")
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        self.adapter.close()

    def test_store_and_retrieve(self):
        key = "integration-key"
        value = {"message": "hello"}
        self.adapter.set(key, value, ttl=30)
        entry = self.adapter.get(key)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.value, value)

    def test_expiry(self):
        key = "integration-expiry"
        value = {"message": "short lived"}
        self.adapter.set(key, value, ttl=0)
        time.sleep(1)
        self.assertIsNone(self.adapter.get(key))


if __name__ == "__main__":
    unittest.main()
