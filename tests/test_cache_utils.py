import time
import unittest

import tempfile
from pathlib import Path

from tool_core.cache import CacheKeyGenerator, InMemoryCacheAdapter, SQLiteCacheAdapter


class CacheKeyGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.generator = CacheKeyGenerator(prefix="test")

    def test_same_payload_same_key(self):
        payload = {"a": 1, "b": [2, 3]}
        key1 = self.generator.make_key("tool", payload, None)
        key2 = self.generator.make_key("tool", {"b": [2, 3], "a": 1}, None)
        self.assertEqual(key1, key2)

    def test_context_changes_key(self):
        payload = {"a": 1}
        key1 = self.generator.make_key("tool", payload, {"mode": "fast"})
        key2 = self.generator.make_key("tool", payload, {"mode": "safe"})
        self.assertNotEqual(key1, key2)


class InMemoryCacheAdapterTests(unittest.TestCase):
    def test_set_and_get(self):
        adapter = InMemoryCacheAdapter()
        adapter.set("key", {"x": 1}, ttl=None)
        entry = adapter.get("key")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.value, {"x": 1})

    def test_expiry(self):
        adapter = InMemoryCacheAdapter()
        adapter.set("key", {"x": 1}, ttl=0)
        time.sleep(0.01)
        self.assertIsNone(adapter.get("key"))


class SQLiteCacheAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "cache.db"
        self.adapter = SQLiteCacheAdapter(self.db_path)

    def tearDown(self):
        self.adapter.close()
        self.temp_dir.cleanup()

    def test_set_and_get(self):
        self.adapter.set("key", {"data": 42}, ttl=None)
        entry = self.adapter.get("key")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.value, {"data": 42})

    def test_expiry(self):
        self.adapter.set("key", {"data": 42}, ttl=0)
        time.sleep(0.01)
        self.assertIsNone(self.adapter.get("key"))

    def test_invalidate(self):
        self.adapter.set("key", {"data": 1}, ttl=None)
        self.adapter.invalidate("key")
        self.assertIsNone(self.adapter.get("key"))
        self.adapter.set("key2", {"data": 2}, ttl=None)
        self.adapter.invalidate()
        self.assertIsNone(self.adapter.get("key2"))


if __name__ == "__main__":
    unittest.main()
