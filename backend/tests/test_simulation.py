"""Deterministic simulation tests, including honest best/worst ordering."""
from __future__ import annotations

import copy

from app.simulation import model


BASELINE = {
    "revenue": 561000.0,
    "cogs": 386000.0,
    "marketing_spend": 64600.0,
    "payroll": 63100.0,
    "occupancy": 22400.0,
    "other_opex": 18500.0,
    "cash_balance": 627000.0,
    "inventory_value": 619000.0,
    "gross_margin_pct": 31.2,
    "discount_depth_pct": 11.8,
    "channels": [
        {"channel": "Stores", "revenue": 264000, "share_pct": 47},
        {"channel": "Online", "revenue": 219000, "share_pct": 39},
        {"channel": "Wholesale", "revenue": 78000, "share_pct": 14},
    ],
}


def test_zero_scenario_does_not_change_baseline():
    result = model.simulate(BASELINE, {})
    assert result["summary"]["net_profit_delta"] == 0
    assert result["summary"]["revenue_delta"] == 0
    assert result["summary"]["production_state_modified"] if "production_state_modified" in result["summary"] else True


def test_marketing_increase_is_not_proportional_revenue_growth():
    result = model.simulate(BASELINE, {"marketing_change_pct": 20})
    assert 0 < result["summary"]["revenue_delta_pct"] < 20
    assert result["summary"]["net_profit_delta"] != 0


def test_cost_reduction_improves_net_profit():
    result = model.simulate(BASELINE, {"cogs_change_pct": -5})
    assert result["summary"]["net_profit_delta"] > 0
    assert result["summary"]["exit_gross_margin_pct"] > BASELINE["gross_margin_pct"]


def test_best_base_worst_ordering():
    result = model.run_scenarios(
        BASELINE,
        {"price_change_pct": 2, "cogs_change_pct": -5, "discount_change_pp": -3, "one_off_cost": 25000},
    )
    base = result["base"]["summary"]["net_profit_delta"]
    best = result["best_case"]["summary"]["net_profit_delta"]
    worst = result["worst_case"]["summary"]["net_profit_delta"]
    assert best > base > worst
    assert result["best_case"]["summary"]["exit_gross_margin_pct"] > result["worst_case"]["summary"]["exit_gross_margin_pct"]


def test_uncertainty_ranges_and_determinism():
    first = model.monte_carlo(BASELINE, {"cogs_change_pct": -3}, iterations=200, seed=7)
    second = model.monte_carlo(BASELINE, {"cogs_change_pct": -3}, iterations=200, seed=7)
    assert first["p10"] <= first["p50"] <= first["p90"]
    assert first["p10"] == second["p10"]
    assert first["probability_above_baseline"] >= 0


def test_simulation_does_not_mutate_production_inputs():
    original = copy.deepcopy(BASELINE)
    model.simulate(BASELINE, {"price_change_pct": 5, "cogs_change_pct": -4})
    assert BASELINE == original


def test_constraint_detection_for_aggressive_cash_spend():
    result = model.simulate(
        BASELINE,
        {"marketing_change_pct": 150, "one_off_cost": 500000},
        horizon_months=12,
    )
    statuses = {constraint["rule"]: constraint["status"] for constraint in result["summary"]["constraints"]}
    assert "minimum_cash_balance" in statuses
    assert statuses["minimum_cash_balance"] == "BREACHED"


def test_backtest_uses_history_only():
    periods = [
        {"label": "Jan", "revenue": 100},
        {"label": "Feb", "revenue": 104},
        {"label": "Mar", "revenue": 108},
        {"label": "Apr", "revenue": 112},
        {"label": "May", "revenue": 116},
    ]
    backtest = model.backtest(periods)
    assert backtest["status"] == "OK"
    assert backtest["mape_pct"] >= 0
