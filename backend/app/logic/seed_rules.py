"""Seed business-rule definitions.

Each rule is deterministic, tested and executed in the sandbox.  These are
platform defaults; tenants can version or replace them without touching core
agent code.
"""
from __future__ import annotations

from typing import Any

SEED_RULES: list[dict[str, Any]] = [
    {
        "key": "gross_margin",
        "name": "Gross Margin",
        "description": "Calculates gross margin percentage from revenue and cost of goods sold. Returns null when revenue is non-positive.",
        "category": "profitability",
        "frequency": "DAILY",
        "input_schema": {"revenue": "number", "cost_of_goods_sold": "number"},
        "output_schema": {"gross_profit": "number", "gross_margin": "number|null"},
        "code": '''def calculate(inputs):
    """Gross margin with an explicit no-revenue guard."""
    revenue = inputs.get("revenue")
    cost = inputs.get("cost_of_goods_sold")

    if revenue is None or cost is None:
        return {"gross_profit": None, "gross_margin": None}

    if revenue <= 0:
        return {"gross_profit": None, "gross_margin": None}

    gross_profit = revenue - cost
    margin = (gross_profit / revenue) * 100

    return {
        "gross_profit": round(gross_profit, 2),
        "gross_margin": round(margin, 2)
    }
''',
        "tests": [
            {"name": "healthy_margin", "inputs": {"revenue": 500000, "cost_of_goods_sold": 325000}, "expected": {"gross_profit": 175000, "gross_margin": 35.0}},
            {"name": "zero_revenue_guard", "inputs": {"revenue": 0, "cost_of_goods_sold": 1000}, "expected": {"gross_profit": None, "gross_margin": None}},
            {"name": "missing_input", "inputs": {"revenue": 1000}, "expected": {"gross_profit": None, "gross_margin": None}},
        ],
    },
    {
        "key": "net_profit_margin",
        "name": "Net Profit Margin",
        "description": "Net profit after marketing, payroll, occupancy and other operating expenses.",
        "category": "profitability",
        "frequency": "DAILY",
        "input_schema": {
            "revenue": "number",
            "cost_of_goods_sold": "number",
            "marketing": "number",
            "payroll": "number",
            "occupancy": "number",
            "other_opex": "number",
        },
        "output_schema": {"operating_expenses": "number", "net_profit": "number", "net_margin": "number|null"},
        "code": '''def calculate(inputs):
    """Net profit margin. Missing expense components are not assumed to be zero."""
    required = ["revenue", "cost_of_goods_sold", "marketing", "payroll", "occupancy", "other_opex"]
    if any(inputs.get(key) is None for key in required):
        return {"operating_expenses": None, "net_profit": None, "net_margin": None}

    revenue = inputs["revenue"]
    opex = inputs["marketing"] + inputs["payroll"] + inputs["occupancy"] + inputs["other_opex"]
    net = revenue - inputs["cost_of_goods_sold"] - opex

    if revenue <= 0:
        return {"operating_expenses": round(opex, 2), "net_profit": round(net, 2), "net_margin": None}

    return {
        "operating_expenses": round(opex, 2),
        "net_profit": round(net, 2),
        "net_margin": round(net / revenue * 100, 2)
    }
''',
        "tests": [
            {
                "name": "standard_month",
                "inputs": {"revenue": 500000, "cost_of_goods_sold": 325000, "marketing": 60000, "payroll": 50000, "occupancy": 20000, "other_opex": 15000},
                "expected": {"operating_expenses": 145000, "net_profit": 30000, "net_margin": 6.0},
            },
            {
                "name": "missing_marketing_is_not_zero",
                "inputs": {"revenue": 500000, "cost_of_goods_sold": 325000, "payroll": 50000, "occupancy": 20000, "other_opex": 15000},
                "expected": {"net_profit": None, "net_margin": None},
            },
        ],
    },
    {
        "key": "cash_runway_months",
        "name": "Cash Runway",
        "description": "Months of operating expenses covered by available cash.",
        "category": "liquidity",
        "frequency": "DAILY",
        "input_schema": {"cash_balance": "number", "monthly_operating_expenses": "number"},
        "output_schema": {"runway_months": "number|null", "status": "string"},
        "code": '''def calculate(inputs):
    cash = inputs.get("cash_balance")
    opex = inputs.get("monthly_operating_expenses")

    if cash is None or opex is None or opex <= 0:
        return {"runway_months": None, "status": "UNKNOWN"}

    runway = cash / opex
    if runway < 2:
        status = "CRITICAL"
    elif runway < 4:
        status = "WARNING"
    else:
        status = "HEALTHY"

    return {"runway_months": round(runway, 1), "status": status}
''',
        "tests": [
            {"name": "healthy", "inputs": {"cash_balance": 900000, "monthly_operating_expenses": 150000}, "expected": {"runway_months": 6.0, "status": "HEALTHY"}},
            {"name": "critical", "inputs": {"cash_balance": 200000, "monthly_operating_expenses": 150000}, "expected": {"runway_months": 1.3, "status": "CRITICAL"}},
        ],
    },
    {
        "key": "inventory_turnover",
        "name": "Inventory Turnover & Days",
        "description": "Annualised inventory turnover and days of inventory.",
        "category": "operations",
        "frequency": "DAILY",
        "input_schema": {"cogs_annualised": "number", "average_inventory": "number"},
        "output_schema": {"turnover": "number|null", "days": "number|null"},
        "code": '''def calculate(inputs):
    cogs = inputs.get("cogs_annualised")
    inventory = inputs.get("average_inventory")

    if cogs is None or inventory is None or inventory <= 0:
        return {"turnover": None, "days": None}

    turnover = cogs / inventory
    return {"turnover": round(turnover, 2), "days": round(365 / turnover, 1)}
''',
        "tests": [
            {"name": "standard", "inputs": {"cogs_annualised": 3900000, "average_inventory": 500000}, "expected": {"turnover": 7.8, "days": 46.8}},
        ],
    },
    {
        "key": "days_sales_outstanding",
        "name": "Days Sales Outstanding",
        "description": "Average collection period for trade receivables.",
        "category": "working_capital",
        "frequency": "DAILY",
        "input_schema": {"receivables": "number", "revenue": "number", "days_in_period": "number"},
        "output_schema": {"dso_days": "number|null"},
        "code": '''def calculate(inputs):
    receivables = inputs.get("receivables")
    revenue = inputs.get("revenue")
    days = inputs.get("days_in_period", 30)

    if receivables is None or revenue is None or revenue <= 0:
        return {"dso_days": None}

    return {"dso_days": round(receivables / revenue * days, 1)}
''',
        "tests": [
            {"name": "standard", "inputs": {"receivables": 90000, "revenue": 500000, "days_in_period": 30}, "expected": {"dso_days": 5.4}},
        ],
    },
    {
        "key": "marketing_roas",
        "name": "Marketing ROAS",
        "description": "Attributed revenue returned per dollar of marketing spend.",
        "category": "commercial",
        "frequency": "DAILY",
        "input_schema": {"attributed_revenue": "number", "marketing_spend": "number"},
        "output_schema": {"roas": "number|null", "verdict": "string"},
        "code": '''def calculate(inputs):
    revenue = inputs.get("attributed_revenue")
    spend = inputs.get("marketing_spend")

    if revenue is None or spend is None or spend <= 0:
        return {"roas": None, "verdict": "UNKNOWN"}

    roas = revenue / spend
    if roas < 2:
        verdict = "UNDERPERFORMING"
    elif roas < 4:
        verdict = "ACCEPTABLE"
    else:
        verdict = "STRONG"

    return {"roas": round(roas, 2), "verdict": verdict}
''',
        "tests": [
            {"name": "strong", "inputs": {"attributed_revenue": 1200000, "marketing_spend": 220000}, "expected": {"roas": 5.45, "verdict": "STRONG"}},
        ],
    },
    {
        "key": "customer_acquisition_cost",
        "name": "Customer Acquisition Cost",
        "description": "Marketing spend per newly acquired customer.",
        "category": "commercial",
        "frequency": "WEEKLY",
        "input_schema": {"marketing_spend": "number", "new_customers": "number"},
        "output_schema": {"cac": "number|null"},
        "code": '''def calculate(inputs):
    spend = inputs.get("marketing_spend")
    new_customers = inputs.get("new_customers")

    if spend is None or new_customers is None or new_customers <= 0:
        return {"cac": None}

    return {"cac": round(spend / new_customers, 2)}
''',
        "tests": [
            {"name": "standard", "inputs": {"marketing_spend": 60000, "new_customers": 400}, "expected": {"cac": 150.0}},
        ],
    },
    {
        "key": "customer_lifetime_value",
        "name": "Customer Lifetime Value",
        "description": "Margin-based CLV using churn rate.",
        "category": "commercial",
        "frequency": "WEEKLY",
        "input_schema": {"avg_order_value": "number", "purchase_frequency": "number", "gross_margin_pct": "number", "churn_rate_pct": "number"},
        "output_schema": {"clv": "number|null", "payback_months": "number|null"},
        "code": '''def calculate(inputs):
    aov = inputs.get("avg_order_value")
    frequency = inputs.get("purchase_frequency")
    margin = inputs.get("gross_margin_pct")
    churn = inputs.get("churn_rate_pct")

    if aov is None or frequency is None or margin is None or not churn:
        return {"clv": None, "payback_months": None}

    monthly_margin = aov * frequency * (margin / 100)
    clv = monthly_margin / (churn / 100)
    return {"clv": round(clv, 2), "payback_months": None}
''',
        "tests": [
            {"name": "standard", "inputs": {"avg_order_value": 120, "purchase_frequency": 1.5, "gross_margin_pct": 35, "churn_rate_pct": 4}, "expected": {"clv": 1575.0, "payback_months": None}},
        ],
    },
    {
        "key": "budget_variance",
        "name": "Budget Variance",
        "description": "Actual versus budgeted spend with a variance classification.",
        "category": "finance",
        "frequency": "MONTHLY",
        "input_schema": {"budgeted": "number", "actual": "number"},
        "output_schema": {"variance": "number", "variance_pct": "number|null", "status": "string"},
        "code": '''def calculate(inputs):
    budgeted = inputs.get("budgeted")
    actual = inputs.get("actual")

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
        "status": status
    }
''',
        "tests": [
            {"name": "over_budget", "inputs": {"budgeted": 100000, "actual": 116000}, "expected": {"variance": 16000, "variance_pct": 16.0, "status": "OVER_BUDGET"}},
        ],
    },
    {
        "key": "reorder_point",
        "name": "Reorder Point",
        "description": "Units required to cover lead time plus safety stock.",
        "category": "operations",
        "frequency": "DAILY",
        "input_schema": {"avg_daily_units": "number", "lead_time_days": "number", "safety_days": "number"},
        "output_schema": {"reorder_point_units": "number|null"},
        "code": '''def calculate(inputs):
    daily_units = inputs.get("avg_daily_units")
    lead_time = inputs.get("lead_time_days")
    safety_days = inputs.get("safety_days", 5)

    if daily_units is None or lead_time is None:
        return {"reorder_point_units": None}

    return {"reorder_point_units": round(daily_units * (lead_time + safety_days), 0)}
''',
        "tests": [
            {"name": "standard", "inputs": {"avg_daily_units": 40, "lead_time_days": 14, "safety_days": 5}, "expected": {"reorder_point_units": 760.0}},
        ],
    },
    {
        "key": "contribution_margin",
        "name": "Contribution Margin",
        "description": "Contribution per unit and total after variable costs.",
        "category": "profitability",
        "frequency": "DAILY",
        "input_schema": {"unit_price": "number", "variable_cost": "number", "units": "number"},
        "output_schema": {"contribution_per_unit": "number|null", "total_contribution": "number|null", "contribution_margin_pct": "number|null"},
        "code": '''def calculate(inputs):
    price = inputs.get("unit_price")
    variable_cost = inputs.get("variable_cost")
    units = inputs.get("units")

    if price is None or variable_cost is None or units is None:
        return {"contribution_per_unit": None, "total_contribution": None, "contribution_margin_pct": None}

    contribution = price - variable_cost
    return {
        "contribution_per_unit": round(contribution, 2),
        "total_contribution": round(contribution * units, 2),
        "contribution_margin_pct": round(contribution / price * 100, 2) if price else None
    }
''',
        "tests": [
            {"name": "standard", "inputs": {"unit_price": 25, "variable_cost": 16, "units": 10000}, "expected": {"contribution_per_unit": 9.0, "total_contribution": 90000.0, "contribution_margin_pct": 36.0}},
        ],
    },
]
