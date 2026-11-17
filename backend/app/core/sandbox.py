"""Constrained execution of business user Python rules.

Defence in depth:
1. AST allow-list (no imports, no dunder access, no dangerous builtins).
2. A separate Python process (isolated mode) with scrubbed environment.
3. Wall-clock timeout, output limits and POSIX resource limits where available.
4. JSON-only inputs/outputs.

Limitations (documented): this is process isolation, not a hardened VM. For
hostile multi-tenant code, run this executor inside gVisor/Firecracker or a
dedicated sandbox service with no network and a read-only filesystem.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings

SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "pow": pow,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "ZeroDivisionError": ZeroDivisionError,
    "ArithmeticError": ArithmeticError,
}

FORBIDDEN_NAMES = {
    "__builtins__",
    "__import__",
    "open",
    "eval",
    "exec",
    "compile",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "help",
    "print",
    "object",
    "type",
    "super",
    "classmethod",
    "staticmethod",
    "property",
    "memoryview",
}

FORBIDDEN_NODE_TYPES = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.ClassDef,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
)


class SandboxValidationError(ValueError):
    pass


@dataclass
class SandboxResult:
    ok: bool
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    stdout: str = ""
    stderr: str = ""
    trace: dict[str, Any] = field(default_factory=dict)


class _SecurityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        self.violations.append(f"line {node.lineno}: imports are not allowed")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.violations.append(f"line {node.lineno}: imports are not allowed")

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, FORBIDDEN_NODE_TYPES):
            self.violations.append(f"line {getattr(node, 'lineno', '?')}: {type(node).__name__} is not allowed")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in {"format", "format_map", "mro"}:
                self.violations.append(
                    f"line {node.lineno}: attribute '{node.attr}' is not allowed"
                )
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            self.violations.append(f"line {node.lineno}: name '{node.id}' is not allowed")
        super().generic_visit(node)


def validate_rule_code(code: str, function_name: str = "calculate") -> None:
    try:
        tree = ast.parse(textwrap.dedent(code))
    except SyntaxError as exc:
        raise SandboxValidationError(f"Syntax error at line {exc.lineno}: {exc.msg}") from exc
    visitor = _SecurityVisitor()
    visitor.visit(tree)
    if visitor.violations:
        raise SandboxValidationError("; ".join(visitor.violations))
    functions = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    if function_name not in functions:
        raise SandboxValidationError(f"Entry point '{function_name}(inputs)' not found")


_RUNNER_SOURCE = r'''
import json, math, sys

MAX_OUTPUT = 200_000

def _finite(value):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    return value

_SAFE_NAMES = %(safe_names)s
_builtin_source = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
_SAFE_BUILTINS = {name: _builtin_source[name] for name in _SAFE_NAMES if name in _builtin_source}

class _MathProxy:
    def __getattr__(self, name):
        return getattr(math, name)

namespace = {
    "__builtins__": _SAFE_BUILTINS,
    "math": _MathProxy(),
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "exp": math.exp,
}

payload = json.load(sys.stdin)
code = payload["code"]
try:
    exec(compile(code, "<business-rule>", "exec"), namespace)
    fn = namespace.get(payload["function"])
    if not callable(fn):
        raise RuntimeError("Entry point %%s is not callable" %% payload["function"])
    result = fn(payload.get("inputs") or {})
    if not isinstance(result, dict):
        raise RuntimeError("Rule must return a dict, got %%s" %% type(result).__name__)
    encoded = json.dumps({"ok": True, "result": result}, default=_finite, allow_nan=False)
    if len(encoded) > MAX_OUTPUT:
        raise RuntimeError("Rule output exceeds size limit")
    sys.stdout.write(encoded)
except Exception as exc:
    sys.stdout.write(json.dumps({"ok": False, "error": "%%s: %%s" %% (type(exc).__name__, exc)}))
''' % {"safe_names": json.dumps(sorted(SAFE_BUILTINS))}


def run_sandboxed(
    code: str,
    function_name: str = "calculate",
    inputs: dict[str, Any] | None = None,
    timeout_seconds: int | None = None,
) -> SandboxResult:
    import time

    started = time.perf_counter()
    try:
        validate_rule_code(code, function_name)
    except SandboxValidationError as exc:
        return SandboxResult(ok=False, error=str(exc), duration_ms=(time.perf_counter() - started) * 1000)

    timeout = timeout_seconds or settings.sandbox_timeout_seconds
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PYTHONIOENCODING": "utf-8",
        "NO_PROXY": "*",
        "PYTHONNOUSERSITE": "1",
    }
    with tempfile.TemporaryDirectory(prefix="twin-sandbox-") as tmp:
        runner = Path(tmp) / "runner.py"
        runner.write_text(_RUNNER_SOURCE, encoding="utf-8")
        payload = json.dumps({"code": textwrap.dedent(code), "function": function_name, "inputs": inputs or {}})
        kwargs: dict[str, Any] = {}
        if os.name == "posix":
            def _limits() -> None:  # pragma: no cover - POSIX only
                import resource

                resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 1))
                resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
                resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
                resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))

            kwargs["preexec_fn"] = _limits
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", str(runner)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=tmp,
                **kwargs,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                ok=False,
                error=f"Execution timed out after {timeout}s",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        duration = (time.perf_counter() - started) * 1000
        stdout = (completed.stdout or "")[:200_000]
        stderr = (completed.stderr or "")[-4_000:]
        try:
            decoded = json.loads(stdout)
        except json.JSONDecodeError:
            return SandboxResult(
                ok=False,
                error="Sandbox produced no valid JSON output",
                duration_ms=duration,
                stdout=stdout,
                stderr=stderr,
            )
        if not decoded.get("ok"):
            return SandboxResult(
                ok=False,
                error=decoded.get("error", "Rule failed"),
                duration_ms=duration,
                stdout=stdout,
                stderr=stderr,
            )
        return SandboxResult(
            ok=True,
            result=decoded.get("result"),
            duration_ms=duration,
            stdout=stdout,
            stderr=stderr,
            trace={"isolated_process": True, "timeout_seconds": timeout},
        )


def run_tests(code: str, function_name: str, tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for index, test in enumerate(tests):
        outcome = run_sandboxed(code, function_name, test.get("inputs", {}))
        expected = test.get("expected", {})
        passed = outcome.ok and all(
            abs(float(outcome.result.get(key, 0)) - float(value)) <= 0.01
            if isinstance(value, (int, float))
            else outcome.result.get(key) == value
            for key, value in expected.items()
        )
        results.append(
            {
                "name": test.get("name", f"test_{index + 1}"),
                "passed": passed,
                "expected": expected,
                "actual": outcome.result,
                "error": outcome.error,
            }
        )
    return results
