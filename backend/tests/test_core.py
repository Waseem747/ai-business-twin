"""Core safety and deterministic calculation tests."""
from __future__ import annotations

import pytest

from app.core.sandbox import SandboxValidationError, run_sandboxed, validate_rule_code
from app.core.secrets import decrypt_secret, encrypt_secret, key_hint
from app.logic import kpis
from app.logic.expressions import FormulaError, evaluate_formula


SAFE_RULE = """
def calculate(inputs):
    revenue = inputs.get("revenue")
    cost = inputs.get("cost_of_goods_sold")
    if revenue is None or cost is None or revenue <= 0:
        return {"gross_margin": None}
    return {"gross_margin": round((revenue - cost) / revenue * 100, 2)}
"""


def test_sandbox_executes_safe_rule():
    result = run_sandboxed(SAFE_RULE, "calculate", {"revenue": 500000, "cost_of_goods_sold": 325000})
    assert result.ok, result.error
    assert result.result["gross_margin"] == 35.0


def test_sandbox_blocks_imports():
    with pytest.raises(SandboxValidationError):
        validate_rule_code("import os\ndef calculate(inputs):\n    return {'x': 1}\n")


def test_sandbox_blocks_file_access_and_dunder():
    with pytest.raises(SandboxValidationError):
        validate_rule_code("def calculate(inputs):\n    return open('secret.txt')\n")
    with pytest.raises(SandboxValidationError):
        validate_rule_code("def calculate(inputs):\n    return inputs.__class__\n")


def test_sandbox_timeout():
    result = run_sandboxed("def calculate(inputs):\n    while True:\n        pass\n", "calculate", {}, timeout_seconds=1)
    assert not result.ok
    assert "timed out" in (result.error or "").lower()


def test_null_inputs_are_not_zero():
    result = run_sandboxed(SAFE_RULE, "calculate", {"revenue": 1000})
    assert result.ok
    assert result.result["gross_margin"] is None


def test_kpi_calculations_and_guards():
    assert kpis.gross_margin_pct(500000, 325000) == 35.0
    assert kpis.gross_margin_pct(0, 1000) is None
    assert kpis.net_profit(500000, 325000, 145000) == 30000
    assert kpis.cash_runway_months(900000, 150000) == 6.0
    assert kpis.customer_acquisition_cost(60000, 0) is None
    score = kpis.health_score(
        {
            "gross_margin_pct": 31.05,
            "net_margin_pct": 0.93,
            "cash_runway_months": 3.7,
            "revenue_growth_pct": 2.4,
            "inventory_days": 48.8,
        }
    )
    assert 0 <= score["score"] <= 100
    assert len(score["factors"]) == 5


def test_formula_engine():
    assert evaluate_formula("revenue - cost", {"revenue": 100, "cost": 60}) == 40
    assert evaluate_formula("round((revenue-cost)/revenue*100, 1)", {"revenue": 500000, "cost": 325000}) == 35.0
    assert evaluate_formula("max(0, revenue - cost) if revenue > 0 else 0", {"revenue": 10, "cost": 20}) == 0
    with pytest.raises(FormulaError):
        evaluate_formula("missing_variable * 2", {})
    with pytest.raises(FormulaError):
        evaluate_formula("revenue / 0", {"revenue": 10})
    with pytest.raises(FormulaError):
        evaluate_formula("__import__('os')", {})


def test_credential_encryption_roundtrip_and_mask():
    ciphertext, nonce = encrypt_secret("sk-live-secret-token-1234")
    assert "sk-live" not in ciphertext
    assert decrypt_secret(ciphertext, nonce) == "sk-live-secret-token-1234"
    assert key_hint("sk-live-secret-token-1234") == "••••1234"
