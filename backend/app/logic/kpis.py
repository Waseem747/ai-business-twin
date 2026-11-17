"""Deterministic KPI library.

These functions contain no LLM calls and no I/O.  They are used to build the
digital twin snapshot and to independently recompute figures during audit.
Missing inputs return ``None`` rather than being treated as zero.
"""
from __future__ import annotations

import math
from typing import Any


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def gross_profit(revenue: float | None, cogs: float | None) -> float | None:
    if revenue is None or cogs is None:
        return None
    return revenue - cogs


def gross_margin_pct(revenue: float | None, cogs: float | None) -> float | None:
    gross = gross_profit(revenue, cogs)
    ratio = _div(gross, revenue)
    return round(ratio * 100, 2) if ratio is not None else None


def operating_expenses(marketing: float | None, payroll: float | None, occupancy: float | None, other: float | None) -> float | None:
    components = [marketing, payroll, occupancy, other]
    if any(component is None for component in components):
        return None
    return float(sum(components))  # type: ignore[arg-type]


def net_profit(revenue: float | None, cogs: float | None, opex: float | None) -> float | None:
    gross = gross_profit(revenue, cogs)
    if gross is None or opex is None:
        return None
    return gross - opex


def net_margin_pct(revenue: float | None, net: float | None) -> float | None:
    ratio = _div(net, revenue)
    return round(ratio * 100, 2) if ratio is not None else None


def revenue_growth_pct(current: float | None, prior: float | None) -> float | None:
    ratio = _div((current or 0) - (prior or 0), prior)
    return round(ratio * 100, 2) if ratio is not None else None


def cash_runway_months(cash: float | None, monthly_opex: float | None) -> float | None:
    ratio = _div(cash, monthly_opex)
    return round(ratio, 1) if ratio is not None else None


def inventory_turnover(cogs_annualised: float | None, average_inventory: float | None) -> float | None:
    ratio = _div(cogs_annualised, average_inventory)
    return round(ratio, 2) if ratio is not None else None


def inventory_days(turnover: float | None) -> float | None:
    if not turnover or turnover <= 0:
        return None
    return round(365 / turnover, 1)


def days_sales_outstanding(receivables: float | None, revenue: float | None, days: int = 30) -> float | None:
    ratio = _div(receivables, revenue)
    return round(ratio * days, 1) if ratio is not None else None


def marketing_roas(attributed_revenue: float | None, marketing_spend: float | None) -> float | None:
    ratio = _div(attributed_revenue, marketing_spend)
    return round(ratio, 2) if ratio is not None else None


def customer_acquisition_cost(marketing_spend: float | None, new_customers: float | None) -> float | None:
    ratio = _div(marketing_spend, new_customers)
    return round(ratio, 2) if ratio is not None else None


def customer_lifetime_value(
    avg_order_value: float | None, purchase_frequency: float | None, gross_margin_pct: float | None, churn_rate: float | None
) -> float | None:
    if None in (avg_order_value, purchase_frequency, gross_margin_pct, churn_rate) or not churn_rate:
        return None
    monthly_margin = avg_order_value * purchase_frequency * (gross_margin_pct / 100)  # type: ignore[operator]
    return round(monthly_margin / (churn_rate / 100), 2)


def budget_variance(budgeted: float | None, actual: float | None) -> dict[str, Any]:
    if budgeted is None or actual is None:
        return {"variance": None, "variance_pct": None, "status": "UNKNOWN"}
    variance = actual - budgeted
    variance_pct = (variance / budgeted * 100) if budgeted else None
    if variance_pct is None:
        status = "UNKNOWN"
    elif variance_pct > 10:
        status = "OVER_BUDGET"
    elif variance_pct < -5:
        status = "UNDER_BUDGET"
    else:
        status = "ON_TRACK"
    return {
        "variance": round(variance, 2),
        "variance_pct": round(variance_pct, 2) if variance_pct is not None else None,
        "status": status,
    }


def reorder_point(avg_daily_units: float | None, lead_time_days: float | None, safety_days: float = 5) -> float | None:
    if avg_daily_units is None or lead_time_days is None:
        return None
    return round(avg_daily_units * (lead_time_days + safety_days), 0)


def health_score(metrics: dict[str, Any]) -> dict[str, Any]:
    """Transparent weighted health score. Every factor is returned to the UI."""

    def scaled(value: float | None, floor: float, target: float) -> float:
        if value is None:
            return 50.0
        return max(0.0, min(100.0, (value - floor) / (target - floor) * 100))

    gm = metrics.get("gross_margin_pct")
    nm = metrics.get("net_margin_pct")
    runway = metrics.get("cash_runway_months")
    growth = metrics.get("revenue_growth_pct")
    inv_days = metrics.get("inventory_days")

    factors = [
        {"key": "gross_margin", "label": "Gross margin", "weight": 0.30, "score": round(scaled(gm, 18, 42), 1), "value": gm},
        {"key": "net_margin", "label": "Net margin", "weight": 0.20, "score": round(scaled(nm, -2, 10), 1), "value": nm},
        {"key": "liquidity", "label": "Cash runway", "weight": 0.20, "score": round(scaled(runway, 0, 6), 1), "value": runway},
        {"key": "growth", "label": "Revenue growth", "weight": 0.15, "score": round(scaled(growth, -8, 6), 1), "value": growth},
        {
            "key": "inventory",
            "label": "Inventory efficiency",
            "weight": 0.15,
            "score": round(100 - scaled(inv_days, 30, 80), 1) if inv_days is not None else 50.0,
            "value": inv_days,
        },
    ]
    total = sum(factor["score"] * factor["weight"] for factor in factors)
    grade = "A" if total >= 85 else "B" if total >= 72 else "C" if total >= 60 else "D" if total >= 45 else "F"
    return {"score": round(total, 1), "grade": grade, "factors": factors}
