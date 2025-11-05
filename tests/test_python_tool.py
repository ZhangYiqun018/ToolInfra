import os
import unittest

from tool_core import ToolRegistry
from tools import create_python_tool_definition
from tools.python_tool import run_code as sandbox_run_code


SANDBOX_ENV_KEYS = ("SANDBOX_FUSION_ENDPOINTS", "SANDBOX_FUSION_ENDPOINT")


def read_sandbox_endpoints():
    for key in SANDBOX_ENV_KEYS:
        value = os.getenv(key)
        if value:
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


class PythonToolIntegrationTests(unittest.TestCase):
    def _suspend_sandbox_env(self):
        saved = {}
        for key in SANDBOX_ENV_KEYS:
            if key in os.environ:
                saved[key] = os.environ.pop(key)
        return saved

    def _restore_sandbox_env(self, saved):
        for key, value in saved.items():
            os.environ[key] = value

    def _create_registry(self, **kwargs) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            create_python_tool_definition(
                **kwargs,
            )
        )
        return registry

    def test_basic_local_execution(self):
        saved = self._suspend_sandbox_env()
        try:
            registry = self._create_registry(sandbox_endpoints=[], fallback_enabled=True)
            result = registry.invoke("python", {"code": "print('hello')" })
            self.assertEqual(result["backend"], "local")
            self.assertEqual(result["status"], "success")
            self.assertIn("hello", result["stdout"])
        finally:
            self._restore_sandbox_env(saved)

    def test_security_check_blocks_dangerous_code(self):
        saved = self._suspend_sandbox_env()
        try:
            registry = self._create_registry(sandbox_endpoints=[], fallback_enabled=True)
            result = registry.invoke("python", {"code": "os.system('echo hi')" })
            self.assertEqual(result["backend"], "local")
            self.assertEqual(result["status"], "security_error")
            self.assertIn("Security check failed", result["stderr"])
            self.assertEqual(result["stdout"], "")
        finally:
            self._restore_sandbox_env(saved)

    def test_local_execution_when_sandbox_disabled(self):
        saved = self._suspend_sandbox_env()
        try:
            registry = self._create_registry(sandbox_endpoints=[], fallback_enabled=False)
            result = registry.invoke("python", {"code": "print('local only')" })
            self.assertEqual(result["backend"], "local")
            self.assertEqual(result["status"], "success")
        finally:
            self._restore_sandbox_env(saved)

    @unittest.skipUnless(sandbox_run_code is not None, "sandbox_fusion unavailable")
    @unittest.skipUnless(read_sandbox_endpoints(), "Sandbox endpoint not configured")
    def test_sandbox_execution_with_real_endpoint(self):
        endpoints = read_sandbox_endpoints()
        registry = self._create_registry(sandbox_endpoints=endpoints, fallback_enabled=True)
        result = registry.invoke("python", {"code": "print('sandbox run')" })
        self.assertEqual(result["backend"], "sandbox")
        self.assertIn("sandbox run", result["stdout"])
        self.assertIn(result["status"], {"success", "Finished"})


if __name__ == "__main__":
    unittest.main()
