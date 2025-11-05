import os
import unittest

from tool_core import ToolRegistry
from tools import create_python_tool_definition


class PythonToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        for env_key in ("SANDBOX_FUSION_ENDPOINTS", "SANDBOX_FUSION_ENDPOINT"):
            os.environ.pop(env_key, None)
        self.registry = ToolRegistry()
        self.registry.register(
            create_python_tool_definition(
                client_config={"timeout": 5, "max_retries": 0},
                sandbox_endpoints=[],
                fallback_enabled=True,
            )
        )

    def test_basic_execution(self):
        result = self.registry.invoke("python", {"code": "print('hello')"})
        self.assertEqual(result["status"], "success")
        self.assertIn("hello", result["stdout"])
        self.assertEqual(result["stderr"], "")

    def test_security_check_blocks_dangerous_code(self):
        result = self.registry.invoke("python", {"code": "os.system('echo hi')"})
        self.assertEqual(result["status"], "security_error")
        self.assertIn("Security check failed", result["stderr"])
        self.assertEqual(result["stdout"], "")


if __name__ == "__main__":
    unittest.main()
