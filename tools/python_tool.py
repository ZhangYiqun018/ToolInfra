"""Python execution tool with sandbox-first strategy and local fallback."""

from __future__ import annotations

import os
import random
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from sandbox_fusion import RunCodeRequest, RunStatus, run_code  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    RunCodeRequest = None  # type: ignore
    RunStatus = None  # type: ignore
    run_code = None  # type: ignore

from tool_core import ToolDefinition
from tools.utils import extract_code


PYTHON_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "Python source code to execute.",
        },
        "safe_mode": {
            "type": "boolean",
            "description": "Enable safety checks before execution.",
            "default": True,
        },
        "sandbox_timeout": {
            "type": "integer",
            "description": "Override sandbox execution timeout in seconds.",
            "minimum": 1,
        },
    },
    "required": ["code"],
}

PYTHON_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "exit_code": {"type": "integer"},
        "execution_time": {"type": "number"},
        "status": {"type": "string"},
        "backend": {
            "type": "string",
            "description": "Execution backend used to run the code.",
            "enum": ["sandbox", "local"],
        },
    },
    "required": ["stdout", "stderr", "exit_code", "execution_time", "status", "backend"],
}


@dataclass
class LocalExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float
    status: str

    def to_response(self) -> Dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "execution_time": self.execution_time,
            "status": self.status,
            "backend": "local",
        }


class LocalPythonExecutor:
    """Minimal local Python executor with safety checks."""

    def __init__(
        self,
        *,
        timeout: int = 30,
        working_directory: Optional[str] = None,
        allowed_imports: Optional[Iterable[str]] = None,
    ):
        self.timeout = timeout
        self.working_directory = working_directory or os.getcwd()
        self.allowed_imports = set(allowed_imports or [])
        self.dangerous_patterns = [
            "subprocess.",
            "os.system",
            "os.popen",
            "__import__",
            "exec(",
            "eval(",
            "compile(",
            "open(",
            "input(",
            "raw_input(",
        ]

    def is_safe_code(self, code: str) -> Tuple[bool, str]:
        if not code or not code.strip():
            return False, "Empty code provided"

        lowered = code.lower()
        for pattern in self.dangerous_patterns:
            if pattern in lowered:
                return False, f"Potentially dangerous pattern detected: {pattern}"

        if self.allowed_imports:
            imports = self._extract_imports(code)
            for module in imports:
                if module not in self.allowed_imports:
                    return False, f"Import '{module}' is not allowed"

        return True, "Code appears safe"

    def execute(self, code: str) -> LocalExecutionResult:
        start = time.time()
        temp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
                handle.write(code)
                temp_path = handle.name

            process = subprocess.Popen(
                ["python3", temp_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.working_directory,
            )

            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                return LocalExecutionResult(
                    stdout=stdout or "",
                    stderr=f"Code execution timed out after {self.timeout} seconds",
                    exit_code=-1,
                    execution_time=self.timeout,
                    status="timeout",
                )

            exit_code = process.returncode or 0
            status = "success" if exit_code == 0 else "execution_error"
            return LocalExecutionResult(
                stdout=stdout or "",
                stderr=stderr or "",
                exit_code=exit_code,
                execution_time=round(time.time() - start, 3),
                status=status,
            )
        except Exception as exc:
            return LocalExecutionResult(
                stdout="",
                stderr=f"Execution failed: {exc}",
                exit_code=-1,
                execution_time=round(time.time() - start, 3),
                status="system_error",
            )
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @staticmethod
    def _extract_imports(code: str) -> List[str]:
        modules: List[str] = []
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("import "):
                parts = stripped.replace("import", "", 1).strip().split(",")
                modules.extend(part.strip().split(" ")[0] for part in parts if part.strip())
            elif stripped.startswith("from "):
                module = stripped.replace("from", "", 1).strip().split(" ")[0]
                if module:
                    modules.append(module)
        return modules


class PythonToolCallable:
    """Sandbox-first Python execution tool with optional local fallback."""

    def __init__(
        self,
        *,
        sandbox_endpoints: Optional[Iterable[str]] = None,
        sandbox_timeout: int = 50,
        sandbox_attempts: int = 5,
        fallback_enabled: bool = True,
        local_timeout: int = 30,
        allowed_imports: Optional[Iterable[str]] = None,
    ):
        if sandbox_endpoints is None:
            endpoints = self._load_endpoints_from_env()
        else:
            endpoints = list(sandbox_endpoints)
        self._sandbox_endpoints = [endpoint.strip() for endpoint in endpoints if endpoint and endpoint.strip()]
        self._sandbox_timeout = sandbox_timeout
        self._sandbox_attempts = max(1, sandbox_attempts)
        self._fallback_enabled = fallback_enabled
        self._local_executor = LocalPythonExecutor(timeout=local_timeout, allowed_imports=allowed_imports)

    def __call__(self, payload: Dict[str, Any], context: Optional[dict] = None) -> Dict[str, Any]:
        code_raw = payload["code"]
        code = extract_code(code_raw)
        safe_mode = payload.get("safe_mode", True)

        if safe_mode:
            is_safe, message = self._local_executor.is_safe_code(code)
            if not is_safe:
                return {
                    "stdout": "",
                    "stderr": f"Security check failed: {message}",
                    "exit_code": -1,
                    "execution_time": 0.0,
                    "status": "security_error",
                    "backend": "local",
                }

        sandbox_timeout = payload.get("sandbox_timeout") or self._sandbox_timeout

        if self._can_use_sandbox():
            sandbox_result, sandbox_error = self._execute_in_sandbox(code=code, timeout=sandbox_timeout)
            if sandbox_result is not None:
                return sandbox_result

            if self._sandbox_endpoints and not self._fallback_enabled:
                return {
                    "stdout": "",
                    "stderr": sandbox_error or "Sandbox execution failed and local fallback is disabled.",
                    "exit_code": -1,
                    "execution_time": 0.0,
                    "status": "sandbox_failure",
                    "backend": "sandbox",
                }

        local_result = self._local_executor.execute(code)
        return local_result.to_response()

    def _can_use_sandbox(self) -> bool:
        return bool(self._sandbox_endpoints)

    def _execute_in_sandbox(self, *, code: str, timeout: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        last_error: Optional[str] = None
        endpoints = list(self._sandbox_endpoints)
        for attempt in range(self._sandbox_attempts):
            endpoint = random.choice(endpoints)
            try:
                request = RunCodeRequest(code=code, language="python", run_timeout=timeout)  # type: ignore[arg-type]
                response = run_code(
                    request,
                    max_attempts=1,
                    client_timeout=timeout,
                    endpoint=endpoint,
                )
                run_result = getattr(response, "run_result", None)
                stdout = getattr(run_result, "stdout", "") or ""
                stderr = getattr(run_result, "stderr", "") or ""
                execution_time = float(getattr(run_result, "execution_time", 0.0) or 0.0)
                status_raw = getattr(run_result, "status", "") or ""
                status_value = self._normalize_status(status_raw)
                exit_code = getattr(run_result, "return_code", None)
                if exit_code is None:
                    exit_code = 0 if not stderr else 1
                return (
                    {
                        "stdout": str(stdout),
                        "stderr": str(stderr),
                        "exit_code": int(exit_code),
                        "execution_time": execution_time,
                        "status": status_value,
                        "backend": "sandbox",
                    },
                    None,
                )
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = f"[Sandbox error] endpoint={endpoint}: {exc}"
        return None, last_error

    @staticmethod
    def _normalize_status(status: Any) -> str:
        if RunStatus is not None and isinstance(status, RunStatus):
            return getattr(status, "value", str(status)) or "success"
        if hasattr(status, "value"):
            return getattr(status, "value") or "success"
        return str(status or "success")

    @staticmethod
    def _load_endpoints_from_env() -> List[str]:
        for key in ("SANDBOX_FUSION_ENDPOINTS", "SANDBOX_FUSION_ENDPOINT"):
            value = os.getenv(key)
            if value:
                return [item.strip() for item in value.split(",") if item.strip()]
        return []


def create_python_tool_definition(
    *,
    description: str = "Execute Python code using sandbox endpoints with optional local fallback.",
    sandbox_endpoints: Optional[Iterable[str]] = None,
    sandbox_timeout: int = 50,
    sandbox_attempts: int = 5,
    fallback_enabled: bool = True,
    local_timeout: int = 30,
    allowed_imports: Optional[Iterable[str]] = None,
) -> ToolDefinition:
    """Build a registry-ready ToolDefinition for Python execution."""

    def factory() -> PythonToolCallable:
        return PythonToolCallable(
            sandbox_endpoints=sandbox_endpoints,
            sandbox_timeout=sandbox_timeout,
            sandbox_attempts=sandbox_attempts,
            fallback_enabled=fallback_enabled,
            local_timeout=local_timeout,
            allowed_imports=allowed_imports,
        )

    return ToolDefinition(
        name="python",
        description=description,
        input_schema=PYTHON_INPUT_SCHEMA,
        output_schema=PYTHON_OUTPUT_SCHEMA,
        factory=factory,
        tags=("builtin", "execution"),
    )
