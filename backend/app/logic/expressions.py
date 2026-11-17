"""Safe formula evaluation for deterministic business rules.

Supports arithmetic, comparisons, ternary expressions and a small allow-list
of functions.  Variable names resolve against the supplied inputs only.
"""
from __future__ import annotations

import ast
import math
import operator
from typing import Any

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}


class FormulaError(ValueError):
    pass


def _round(value: float, digits: int = 0) -> float:
    return round(value, int(digits))


def _if(condition: Any, when_true: Any, when_false: Any) -> Any:
    return when_true if condition else when_false


FUNCTIONS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": _round,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "exp": math.exp,
    "if_": _if,
    "clamp": lambda value, low, high: max(low, min(high, value)),
}


def _eval(node: ast.AST, variables: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool, str)) or node.value is None:
            return node.value
        raise FormulaError("Unsupported constant")
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        if node.id in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.id]
        raise FormulaError(f"Unknown variable '{node.id}'")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval(node.left, variables)
        right = _eval(node.right, variables)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise FormulaError("Division by zero")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand, variables))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, variables)
        for op, comparator in zip(node.ops, node.comparators):
            if type(op) not in _CMP_OPS:
                raise FormulaError("Unsupported comparison")
            right = _eval(comparator, variables)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        values = [_eval(value, variables) for value in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.IfExp):
        return _eval(node.body, variables) if _eval(node.test, variables) else _eval(node.orelse, variables)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise FormulaError("Function not allowed")
        if node.keywords:
            raise FormulaError("Keyword arguments are not allowed")
        return FUNCTIONS[node.func.id](*[_eval(arg, variables) for arg in node.args])
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(element, variables) for element in node.elts]
    raise FormulaError(f"Unsupported syntax: {type(node).__name__}")


def evaluate_formula(expression: str, variables: dict[str, Any]) -> float | int | bool | str | None:
    expression = expression.strip()
    if expression.startswith("="):
        expression = expression[1:]
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Invalid formula: {exc.msg}") from exc
    try:
        result = _eval(tree, variables)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise FormulaError(str(exc)) from exc
    return result


def explain_formula(expression: str) -> list[str]:
    """List variable references for lineage display."""
    tree = ast.parse(expression.lstrip("="), mode="eval")
    return sorted({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)})
