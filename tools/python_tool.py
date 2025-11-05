"""Python execution tool wired to the registry."""

from __future__ import annotations

import os
import random
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dr_inference.python_client import Python_client

from tool_core import ToolDefinition

try:
    from sandbox_fusion import RunCodeRequest, RunStatus, run_code  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    RunCodeRequest = None  # type: ignore
    RunStatus = None  # type: ignore
    run_code = None  # type: ignore

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
    },
    "required": ["stdout", "stderr", "exit_code", "execution_time", "status"],
}


class PythonToolCallable:
    """Callable wrapper around `Python_client`."""

    def __init__(
        self,
        *,
        client_config: Optional[Dict[str, Any]] = None,
        sandbox_endpoints: Optional[Iterable[str]] = None,
        sandbox_timeout: int = 50,
        sandbox_attempts: int = 5,
        fallback_enabled: bool = True,
    ):
        self._client = Python_client(**(client_config or {}))
        endpoints = list(sandbox_endpoints or self._load_endpoints_from_env())
        self._sandbox_endpoints = [endpoint.strip() for endpoint in endpoints if endpoint and endpoint.strip()]
        self._sandbox_timeout = sandbox_timeout
        self._sandbox_attempts = max(1, sandbox_attempts)
        self._fallback_enabled = fallback_enabled

    def __call__(self, payload: Dict[str, Any], context: Optional[dict] = None) -> Dict[str, Any]:
        safe_mode = payload.get("safe_mode", True)
        code = payload["code"]

        if safe_mode:
            is_safe, message = self._client.is_safe_code(code)
            if not is_safe:
                return self._error_result(
                    stderr=f"Security check failed: {message}",
                    status="security_error",
                    exit_code=-1,
                )

        sandbox_timeout = payload.get("sandbox_timeout") or self._sandbox_timeout
        sandbox_result: Optional[Dict[str, Any]] = None
        sandbox_error: Optional[str] = None

        if self._sandbox_endpoints and run_code is not None and RunCodeRequest is not None:
            sandbox_result, sandbox_error = self._execute_with_sandbox(
                code=code,
                timeout=sandbox_timeout,
            )
            if sandbox_result is not None:
                return sandbox_result

        if self._sandbox_endpoints and not self._fallback_enabled:
            return self._error_result(
                stderr=sandbox_error or "Sandbox execution failed and local fallback is disabled.",
                status="sandbox_failure",
                exit_code=-1,
            )

        local_result = self._client.execute(code, safe_mode=False)
        return self._normalize_client_result(local_result)

    def _execute_with_sandbox(self, *, code: str, timeout: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        last_error: Optional[str] = None
        for attempt in range(self._sandbox_attempts):
            endpoint = random.choice(self._sandbox_endpoints)
            try:
                request = RunCodeRequest(code=code, language="python", run_timeout=timeout)  # type: ignore[arg-type]
                code_result = run_code(
                    request,
                    max_attempts=1,
                    client_timeout=timeout,
                    endpoint=endpoint,
                )
                run_result = getattr(code_result, "run_result", None)
                stdout = getattr(run_result, "stdout", "") or ""
                stderr = getattr(run_result, "stderr", "") or ""
                execution_time = float(getattr(run_result, "execution_time", 0.0) or 0.0)
                status_value = getattr(run_result, "status", "") or ""
                if RunStatus is not None and isinstance(status_value, RunStatus):
                    status_value = getattr(status_value, "value", str(status_value))
                exit_code = getattr(run_result, "return_code", None)
                if exit_code is None:
                    exit_code = 0 if not stderr else 1
                return {
                    "stdout": str(stdout),
                    "stderr": str(stderr),
                    "exit_code": int(exit_code),
                    "execution_time": execution_time,
                    "status": str(status_value or "success"),
                }
            except Exception as exc:  # pragma: no cover - depends on sandbox
                last_error = f"[Sandbox error] endpoint={endpoint}: {exc}"
        return None, last_error

    def _normalize_client_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "stdout": str(result.get("stdout", "")),
            "stderr": str(result.get("stderr", "")),
            "exit_code": int(result.get("exit_code", 0)),
            "execution_time": float(result.get("execution_time", 0.0)),
            "status": str(result.get("status", "")),
        }

    @staticmethod
    def _error_result(*, stderr: str, status: str, exit_code: int) -> Dict[str, Any]:
        return {
            "stdout": "",
            "stderr": stderr,
            "exit_code": exit_code,
            "execution_time": 0.0,
            "status": status,
        }

    @staticmethod
    def _load_endpoints_from_env() -> List[str]:
        env_value = os.getenv("SANDBOX_FUSION_ENDPOINTS") or os.getenv("SANDBOX_FUSION_ENDPOINT")
        if not env_value:
            return []
        return [item.strip() for item in env_value.split(",")]


def create_python_tool_definition(
    *,
    description: str = "Execute Python code using sandbox endpoints with optional local fallback.",
    client_config: Optional[Dict[str, Any]] = None,
    sandbox_endpoints: Optional[Iterable[str]] = None,
    sandbox_timeout: int = 50,
    sandbox_attempts: int = 5,
    fallback_enabled: bool = True,
) -> ToolDefinition:
    """Build a registry-ready ToolDefinition for Python execution."""

    def factory() -> PythonToolCallable:
        return PythonToolCallable(
            client_config=client_config,
            sandbox_endpoints=sandbox_endpoints,
            sandbox_timeout=sandbox_timeout,
            sandbox_attempts=sandbox_attempts,
            fallback_enabled=fallback_enabled,
        )

    return ToolDefinition(
        name="python",
        description=description,
        input_schema=PYTHON_INPUT_SCHEMA,
        output_schema=PYTHON_OUTPUT_SCHEMA,
        factory=factory,
        tags=("builtin", "execution"),
    )
