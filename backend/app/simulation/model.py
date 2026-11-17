"""Deterministic business simulation model.

The model is intentionally transparent: every relationship is an explicit
assumption, configurable per business.  It never calls an LLM and never writes
to production observations or metrics.  Results are always labelled SIMULATED.
"""
from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

BASE_ASSUMPTIONS: dict[str, Any] = {
    "price_volume_elasticity": -0.8,
    "marketing_response_elasticity": 0.22,
    "discount_volume_response": 0.6,
    "baseline_monthly_growth_pct": 0.8,
    "annual_opex_inflation_pct": 3.6,
    "cost_per_hire_annual": 62_000,
    "hire_revenue_full_ramp_monthly": 7_000,
    "hire_ramp_months": 6,
    "revenue_impact_ramp_months": 6,
    "inventory_holding_cost_pct_monthly": 1.2,
    "minimum_cash_balance": 250_000,
    "wholesale_price_locked": True,
    "note": "Explicit modelling assumptions. Not a forecast guarantee. LLMs do not calculate these outcomes.",
}

DEFAULT_PARAMETERS: dict[str, Any] = {
    "price_change_pct": 0.0,
    "marketing_change_pct": 0.0,
    "cogs_change_pct": 0.0,
    "discount_change_pp": 0.0,
    "headcount_change": 0,
    "inventory_change_pct": 0.0,
    "revenue_impact_pct": 0.0,
    "other_opex_change_pct": 0.0,
    "one_off_cost": 0.0,
}


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _base_context(baseline: dict[str, Any], assumptions: dict[str, Any]) -> dict[str, Any]:
    revenue = float(baseline.get("revenue") or 0)
    cogs = float(baseline.get("cogs") or (revenue * 0.65))
    cash = float(baseline.get("cash_balance") or 0)
    inventory = float(baseline.get("inventory_value") or 0)
    opex_components = {
        "marketing": float(baseline.get("marketing_spend") or 0),
        "payroll": float(baseline.get("payroll") or 0),
        "occupancy": float(baseline.get("occupancy") or 0),
        "other": float(baseline.get("other_opex") or 0),
    }
    retail_share = 0.85
    channels = baseline.get("channels") or []
    if channels:
        total = sum(float(channel.get("revenue") or 0) for channel in channels)
        retail = sum(
            float(channel.get("revenue") or 0)
            for channel in channels
            if channel.get("channel") in {"Stores", "Online"}
        )
        if total:
            retail_share = retail / total
    return {
        "revenue": revenue,
        "cogs": cogs,
        "cash": cash,
        "inventory": inventory,
        "opex": opex_components,
        "retail_share": retail_share,
        "gross_margin_pct": _safe_ratio(revenue - cogs, revenue) * 100,
        "growth": assumptions["baseline_monthly_growth_pct"] / 100,
        "opex_inflation": (1 + assumptions["annual_opex_inflation_pct"] / 100) ** (1 / 12) - 1,
    }


def _run_projection(
    baseline: dict[str, Any],
    parameters: dict[str, Any],
    assumptions: dict[str, Any],
    horizon_months: int,
) -> dict[str, Any]:
    params = {**DEFAULT_PARAMETERS, **(parameters or {})}
    ctx = _base_context(baseline, assumptions)
    base_revenue = ctx["revenue"]
    base_cogs = ctx["cogs"]
    base_cash = ctx["cash"]
    base_inventory = ctx["inventory"]
    base_opex = ctx["opex"]

    retail_share = ctx["retail_share"]
    elasticity = assumptions["price_volume_elasticity"]
    marketing_elasticity = assumptions["marketing_response_elasticity"]
    discount_response = assumptions["discount_volume_response"]
    base_discount = float(baseline.get("discount_depth_pct") or 8.0)

    price_delta = float(params["price_change_pct"]) / 100
    marketing_delta = float(params["marketing_change_pct"]) / 100
    cogs_delta = float(params["cogs_change_pct"]) / 100
    discount_delta = float(params["discount_change_pp"])
    headcount = int(params["headcount_change"])
    inventory_delta = float(params["inventory_change_pct"]) / 100
    revenue_impact = float(params["revenue_impact_pct"]) / 100
    other_opex_change = float(params["other_opex_change_pct"]) / 100
    one_off = float(params["one_off_cost"])

    # Explicit transfer functions -------------------------------------------------
    retail_price_factor = 1 + price_delta
    price_volume_factor = 1 + retail_share * price_delta * elasticity
    price_revenue_factor = 1 + retail_share * (retail_price_factor * price_volume_factor - 1)
    new_discount = max(0.0, min(30.0, base_discount + discount_delta))
    discount_net_price_factor = _safe_ratio(1 - new_discount / 100, 1 - base_discount / 100, 1.0)
    discount_volume_factor = 1 + discount_response * (discount_delta / 100)
    discount_revenue_factor = retail_share * (discount_net_price_factor * discount_volume_factor) + (1 - retail_share)
    marketing_revenue_lift = (
        marketing_elasticity * math.log1p(max(marketing_delta, -0.95)) if marketing_delta != 0 else 0.0
    )
    marketing_revenue_factor = 1 + marketing_revenue_lift
    volume_factor = max(0.05, retail_share * (price_volume_factor * discount_volume_factor) + (1 - retail_share))
    scenario_cogs_factor = (1 + cogs_delta) * volume_factor

    monthly: list[dict[str, Any]] = []
    base_monthly: list[dict[str, Any]] = []
    cumulative_scenario = 0.0
    cumulative_base = 0.0
    scenario_cash = base_cash
    base_cash_track = base_cash
    inventory_investment = 0.0
    if inventory_delta:
        inventory_investment = base_inventory * inventory_delta
    for month in range(1, horizon_months + 1):
        growth = (1 + ctx["growth"]) ** (month - 1)
        opex_inflation = (1 + ctx["opex_inflation"]) ** (month - 1)

        base_rev = base_revenue * growth
        base_cost = base_cogs * growth
        base_marketing = base_opex["marketing"] * opex_inflation
        base_other_opex = (base_opex["payroll"] + base_opex["occupancy"] + base_opex["other"]) * opex_inflation
        base_total_opex = base_marketing + base_other_opex
        base_net = base_rev - base_cost - base_total_opex
        cumulative_base += base_net
        base_cash_track += base_net

        scenario_rev = (
            base_rev
            * price_revenue_factor
            * discount_revenue_factor
            * marketing_revenue_factor
            * (1 + revenue_impact * min(1.0, month / max(1, assumptions["revenue_impact_ramp_months"])))
        )
        scenario_cost = base_cost * scenario_cogs_factor
        scenario_marketing = base_marketing * (1 + marketing_delta)
        hire_ramp = min(1.0, month / max(1, assumptions["hire_ramp_months"]))
        hire_cost = headcount * assumptions["cost_per_hire_annual"] / 12
        hire_revenue = headcount * assumptions["hire_revenue_full_ramp_monthly"] * hire_ramp
        other_opex = base_other_opex * (1 + other_opex_change)
        scenario_opex = scenario_marketing + other_opex + hire_cost
        scenario_rev += hire_revenue
        holding_cost = (
            base_inventory * (1 + inventory_delta) * assumptions["inventory_holding_cost_pct_monthly"] / 100
            - base_inventory * assumptions["inventory_holding_cost_pct_monthly"] / 100
        )
        scenario_net = scenario_rev - scenario_cost - scenario_opex - holding_cost
        cash_flow = scenario_net
        if month == 1:
            cash_flow -= one_off + inventory_investment
        scenario_cash += cash_flow
        cumulative_scenario += scenario_net

        monthly.append(
            {
                "month": month,
                "revenue": round(scenario_rev, 2),
                "cogs": round(scenario_cost, 2),
                "gross_profit": round(scenario_rev - scenario_cost, 2),
                "gross_margin_pct": round(_safe_ratio(scenario_rev - scenario_cost, scenario_rev) * 100, 2),
                "operating_expenses": round(scenario_opex + holding_cost, 2),
                "net_profit": round(scenario_net, 2),
                "cash_balance": round(scenario_cash, 2),
                "inventory_value": round(base_inventory * (1 + inventory_delta), 2),
            }
        )
        base_monthly.append(
            {
                "month": month,
                "revenue": round(base_rev, 2),
                "cogs": round(base_cost, 2),
                "gross_profit": round(base_rev - base_cost, 2),
                "gross_margin_pct": round(_safe_ratio(base_rev - base_cost, base_rev) * 100, 2),
                "operating_expenses": round(base_total_opex, 2),
                "net_profit": round(base_net, 2),
                "cash_balance": round(base_cash_track, 2),
                "inventory_value": round(base_inventory, 2),
            }
        )

    last = monthly[-1]
    base_last = base_monthly[-1]
    gross_profit_scenario = sum(month["gross_profit"] for month in monthly)
    gross_profit_base = sum(month["gross_profit"] for month in base_monthly)
    revenue_scenario = sum(month["revenue"] for month in monthly)
    revenue_base = sum(month["revenue"] for month in base_monthly)
    investment = abs(one_off) + max(0.0, (base_opex["marketing"] * marketing_delta) * horizon_months) + max(0.0, inventory_investment)
    incremental_net = cumulative_scenario - cumulative_base

    constraints = []
    if last["gross_margin_pct"] < 20:
        constraints.append(
            {
                "rule": "minimum_gross_margin",
                "threshold": 20,
                "actual": last["gross_margin_pct"],
                "status": "BREACHED",
                "message": "Projected gross margin falls below the 20% policy floor.",
            }
        )
    if min(month["cash_balance"] for month in monthly) < assumptions["minimum_cash_balance"]:
        constraints.append(
            {
                "rule": "minimum_cash_balance",
                "threshold": assumptions["minimum_cash_balance"],
                "actual": round(min(month["cash_balance"] for month in monthly), 2),
                "status": "BREACHED",
                "message": "Projected cash dips below the minimum operating cash policy.",
            }
        )
    if abs(float(params["price_change_pct"])) > 10:
        constraints.append(
            {
                "rule": "price_change_limit",
                "threshold": 10,
                "actual": params["price_change_pct"],
                "status": "BREACHED",
                "message": "Price change exceeds the tested +/-10% simulation range.",
            }
        )
    if float(params["marketing_change_pct"]) > 100:
        constraints.append(
            {
                "rule": "marketing_change_limit",
                "threshold": 100,
                "actual": params["marketing_change_pct"],
                "status": "BREACHED",
                "message": "Marketing increase exceeds the 100% tested range.",
            }
        )
    if not constraints:
        constraints.append(
            {
                "rule": "policy_constraints",
                "status": "PASSED",
                "message": "All configured scenario constraints passed.",
            }
        )

    roi = (
        round(incremental_net / investment * 100, 1)
        if investment > 0
        else None
    )
    break_even = None
    running = -one_off - inventory_investment
    cumulative_gap = 0.0
    for month in monthly:
        gap = month["net_profit"] - base_monthly[month["month"] - 1]["net_profit"]
        cumulative_gap += gap
        if cumulative_gap > abs(one_off) + max(0.0, inventory_investment) and break_even is None:
            break_even = month["month"]
        running += gap
    if break_even is None and cumulative_gap > 0:
        break_even = horizon_months

    return {
        "parameters": params,
        "monthly": monthly,
        "baseline_monthly": base_monthly,
        "summary": {
            "revenue_12m": round(revenue_scenario, 2),
            "baseline_revenue_12m": round(revenue_base, 2),
            "revenue_delta": round(revenue_scenario - revenue_base, 2),
            "revenue_delta_pct": round(_safe_ratio(revenue_scenario - revenue_base, revenue_base) * 100, 2),
            "gross_profit_12m": round(gross_profit_scenario, 2),
            "baseline_gross_profit_12m": round(gross_profit_base, 2),
            "gross_profit_delta": round(gross_profit_scenario - gross_profit_base, 2),
            "net_profit_12m": round(cumulative_scenario, 2),
            "baseline_net_profit_12m": round(cumulative_base, 2),
            "net_profit_delta": round(incremental_net, 2),
            "exit_gross_margin_pct": last["gross_margin_pct"],
            "baseline_exit_gross_margin_pct": base_last["gross_margin_pct"],
            "exit_cash_balance": last["cash_balance"],
            "baseline_exit_cash_balance": base_last["cash_balance"],
            "minimum_cash": round(min(month["cash_balance"] for month in monthly), 2),
            "investment_required": round(investment, 2),
            "roi_pct": roi,
            "break_even_month": break_even,
            "gross_margin_pct": last["gross_margin_pct"],
            "net_margin_pct": round(_safe_ratio(last["net_profit"], last["revenue"]) * 100, 2),
            "constraints": constraints,
            "cash_runway_months": round(
                last["cash_balance"] / max(1.0, last["operating_expenses"]), 1
            ),
        },
        "assumptions_used": assumptions,
        "model": "deterministic-retail-v1",
    }


def simulate(
    baseline: dict[str, Any],
    parameters: dict[str, Any] | None = None,
    *,
    assumption_overrides: dict[str, Any] | None = None,
    horizon_months: int = 12,
) -> dict[str, Any]:
    assumptions = copy.deepcopy(BASE_ASSUMPTIONS)
    assumptions.update(assumption_overrides or {})
    result = _run_projection(baseline, parameters or {}, assumptions, horizon_months)
    return result


def _favorability_shift(assumptions: dict[str, Any], favorable: bool) -> dict[str, Any]:
    shifted = copy.deepcopy(assumptions)
    elasticity = shifted["price_volume_elasticity"]
    # A price increase is favourable when demand is less elastic.
    if favorable:
        shifted["price_volume_elasticity"] = elasticity * 0.65
        shifted["marketing_response_elasticity"] = shifted["marketing_response_elasticity"] * 1.3
        shifted["discount_volume_response"] = shifted["discount_volume_response"] * 0.7
    else:
        shifted["price_volume_elasticity"] = elasticity * 1.35
        shifted["marketing_response_elasticity"] = shifted["marketing_response_elasticity"] * 0.7
        shifted["discount_volume_response"] = shifted["discount_volume_response"] * 1.3
    return shifted


def run_scenarios(
    baseline: dict[str, Any],
    parameters: dict[str, Any],
    *,
    horizon_months: int = 12,
) -> dict[str, Any]:
    base = simulate(baseline, parameters, horizon_months=horizon_months)
    best_params = copy.deepcopy(parameters)
    worst_params = copy.deepcopy(parameters)
    cogs_change = float(parameters.get("cogs_change_pct") or 0)
    if cogs_change < 0:
        best_params["cogs_change_pct"] = cogs_change * 1.25
        worst_params["cogs_change_pct"] = cogs_change * 0.6
    elif cogs_change > 0:
        best_params["cogs_change_pct"] = cogs_change * 0.6
        worst_params["cogs_change_pct"] = cogs_change * 1.25
    one_off = float(parameters.get("one_off_cost") or 0)
    best_params["one_off_cost"] = one_off * 0.9
    worst_params["one_off_cost"] = one_off * 1.15
    best = simulate(
        baseline,
        best_params,
        assumption_overrides=_favorability_shift(BASE_ASSUMPTIONS, True),
        horizon_months=horizon_months,
    )
    worst = simulate(
        baseline,
        worst_params,
        assumption_overrides=_favorability_shift(BASE_ASSUMPTIONS, False),
        horizon_months=horizon_months,
    )
    return {
        "base": base,
        "best_case": best,
        "worst_case": worst,
        "alternatives": [
            {
                "name": "Worst case",
                "key": "worst",
                "net_profit_12m": worst["summary"]["net_profit_12m"],
                "net_profit_delta": worst["summary"]["net_profit_delta"],
                "exit_gross_margin_pct": worst["summary"]["exit_gross_margin_pct"],
                "exit_cash_balance": worst["summary"]["exit_cash_balance"],
                "assumptions": worst["assumptions_used"],
                "parameters": worst["parameters"],
            },
            {
                "name": "Base case",
                "key": "base",
                "net_profit_12m": base["summary"]["net_profit_12m"],
                "net_profit_delta": base["summary"]["net_profit_delta"],
                "exit_gross_margin_pct": base["summary"]["exit_gross_margin_pct"],
                "exit_cash_balance": base["summary"]["exit_cash_balance"],
                "assumptions": base["assumptions_used"],
                "parameters": base["parameters"],
            },
            {
                "name": "Best case",
                "key": "best",
                "net_profit_12m": best["summary"]["net_profit_12m"],
                "net_profit_delta": best["summary"]["net_profit_delta"],
                "exit_gross_margin_pct": best["summary"]["exit_gross_margin_pct"],
                "exit_cash_balance": best["summary"]["exit_cash_balance"],
                "assumptions": best["assumptions_used"],
                "parameters": best["parameters"],
            },
        ],
    }


def sensitivity_analysis(
    baseline: dict[str, Any], parameters: dict[str, Any], *, horizon_months: int = 12
) -> dict[str, Any]:
    base = simulate(baseline, parameters, horizon_months=horizon_months)["summary"]["net_profit_12m"]
    dimensions = [
        {"key": "price_volatility", "label": "Price elasticity \u00b125%", "assumption": "price_volume_elasticity", "factor": 1.25},
        {"key": "marketing_response", "label": "Marketing response \u00b125%", "assumption": "marketing_response_elasticity", "factor": 1.25},
        {"key": "discount_response", "label": "Discount response \u00b125%", "assumption": "discount_volume_response", "factor": 1.25},
        {"key": "cost_overrun", "label": "Supplier cost outcome", "assumption": "__cogs__", "factor": 1.25},
        {"key": "execution_delay", "label": "Benefit realisation 3-month delay", "assumption": "__delay__", "factor": 1.0},
    ]
    results = []
    for dimension in dimensions:
        low = high = base
        if dimension["assumption"] == "__cogs__":
            low_params = {**parameters, "cogs_change_pct": float(parameters.get("cogs_change_pct", 0)) * 0.5}
            high_params = {**parameters, "cogs_change_pct": float(parameters.get("cogs_change_pct", 0)) * 1.5}
            low = simulate(baseline, low_params, horizon_months=horizon_months)["summary"]["net_profit_12m"]
            high = simulate(baseline, high_params, horizon_months=horizon_months)["summary"]["net_profit_12m"]
        elif dimension["assumption"] == "__delay__":
            # Delaying any benefit by a quarter reduces the 12-month net benefit.
            low = round(base - (simulate(baseline, parameters, horizon_months=horizon_months)["summary"]["net_profit_delta"] * 0.25), 2)
            high = base
        else:
            assumption = BASE_ASSUMPTIONS[dimension["assumption"]]
            low_override = {dimension["assumption"]: assumption * dimension["factor"]}
            high_override = {dimension["assumption"]: assumption / dimension["factor"]}
            low = simulate(baseline, parameters, assumption_overrides=low_override, horizon_months=horizon_months)["summary"]["net_profit_12m"]
            high = simulate(baseline, parameters, assumption_overrides=high_override, horizon_months=horizon_months)["summary"]["net_profit_12m"]
        results.append(
            {
                "key": dimension["key"],
                "label": dimension["label"],
                "low_net_profit_12m": round(min(low, high), 2),
                "high_net_profit_12m": round(max(low, high), 2),
                "delta_low": round(min(low, high) - base, 2),
                "delta_high": round(max(low, high) - base, 2),
                "base_net_profit_12m": base,
            }
        )
    results.sort(key=lambda item: abs(item["delta_high"] - item["delta_low"]), reverse=True)
    return {"base_net_profit_12m": base, "dimensions": results}


def monte_carlo(
    baseline: dict[str, Any],
    parameters: dict[str, Any],
    *,
    iterations: int = 2000,
    horizon_months: int = 12,
    seed: int = 42,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    base_result = simulate(baseline, parameters, horizon_months=horizon_months)
    baseline_net = base_result["summary"]["baseline_net_profit_12m"]
    scenario_net = base_result["summary"]["net_profit_12m"]
    cogs_change = float(parameters.get("cogs_change_pct", 0))
    outcomes: list[float] = []
    margins: list[float] = []
    for _ in range(iterations):
        overrides = {
            "price_volume_elasticity": float(rng.normal(BASE_ASSUMPTIONS["price_volume_elasticity"], 0.18)),
            "marketing_response_elasticity": float(
                max(0.02, rng.normal(BASE_ASSUMPTIONS["marketing_response_elasticity"], 0.06))
            ),
            "discount_volume_response": float(max(0.1, rng.normal(BASE_ASSUMPTIONS["discount_volume_response"], 0.12))),
        }
        sampled_params = {
            **parameters,
            "cogs_change_pct": cogs_change + float(rng.normal(0, 1.2)),
        }
        result = simulate(
            baseline,
            sampled_params,
            assumption_overrides=overrides,
            horizon_months=horizon_months,
        )
        outcomes.append(result["summary"]["net_profit_12m"])
        margins.append(result["summary"]["exit_gross_margin_pct"])
    array = np.array(outcomes)
    hist, edges = np.histogram(array, bins=24)
    return {
        "iterations": iterations,
        "seed": seed,
        "mean_net_profit_12m": round(float(array.mean()), 2),
        "p10": round(float(np.percentile(array, 10)), 2),
        "p50": round(float(np.percentile(array, 50)), 2),
        "p90": round(float(np.percentile(array, 90)), 2),
        "std_dev": round(float(array.std()), 2),
        "probability_above_baseline": round(float((array > baseline_net).mean() * 100), 1),
        "probability_positive": round(float((array > 0).mean() * 100), 1),
        "exit_margin_p10": round(float(np.percentile(margins, 10)), 2),
        "exit_margin_p90": round(float(np.percentile(margins, 90)), 2),
        "histogram": [
            {"bucket_start": round(float(edges[index]), 0), "bucket_end": round(float(edges[index + 1]), 0), "count": int(count)}
            for index, count in enumerate(hist)
        ],
        "base_net_profit_12m": scenario_net,
        "baseline_net_profit_12m": baseline_net,
        "disclaimer": "Monte Carlo output is a modelled range, not a forecast guarantee. Assumption distributions are documented and configurable.",
    }


def backtest(periods: list[dict[str, Any]]) -> dict[str, Any]:
    """Naive-baseline revenue backtest.

    This validates the baseline growth assumption only. It is not a
    counterfactual test of interventions, which would require controlled
    experiments.
    """
    points = [p for p in periods if p.get("revenue")]
    if len(points) < 4:
        return {"status": "INSUFFICIENT_HISTORY", "note": "At least four months are required for backtesting."}
    errors = []
    series = []
    for index in range(3, len(points)):
        history = points[index - 3 : index]
        growth_rates = [
            _safe_ratio(history[i]["revenue"] - history[i - 1]["revenue"], history[i - 1]["revenue"])
            for i in range(1, len(history))
        ]
        avg_growth = sum(growth_rates) / len(growth_rates)
        predicted = history[-1]["revenue"] * (1 + avg_growth)
        actual = points[index]["revenue"]
        error = abs(predicted - actual) / actual * 100 if actual else 0
        errors.append(error)
        series.append(
            {
                "period": points[index]["label"],
                "predicted": round(predicted, 2),
                "actual": round(actual, 2),
                "error_pct": round(error, 2),
            }
        )
    mape = sum(errors) / len(errors)
    return {
        "status": "OK",
        "method": "naive_growth_extrapolation",
        "mape_pct": round(mape, 2),
        "samples": len(series),
        "series": series,
        "note": "Validates the baseline revenue assumption only; not evidence that an intervention caused an outcome.",
    }
