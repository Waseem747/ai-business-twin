"""Deterministic anomaly detection and root-cause investigation.

Findings distinguish confirmed facts, statistical anomalies, potential risks,
hypotheses and missing information.  LLM interpretation happens later and may
not alter the numbers or evidence captured here.
"""
from __future__ import annotations

import math
import statistics
from typing import Any

MARGIN_TARGET = 38.0
MIN_CASH = 250_000.0


def _pct_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior) * 100


def _finding(
    key: str,
    kind: str,
    severity: str,
    title: str,
    detail: str,
    area: str,
    evidence: dict[str, Any],
    confidence: float,
) -> dict[str, Any]:
    return {
        "id": key,
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "area": area,
        "evidence": evidence,
        "confidence": round(confidence, 2),
    }


def detect_anomalies(snapshot_payload: dict[str, Any]) -> dict[str, Any]:
    latest = snapshot_payload.get("latest") or {}
    prior = snapshot_payload.get("prior") or {}
    periods = snapshot_payload.get("periods") or []
    drivers = snapshot_payload.get("drivers") or {}
    quality = snapshot_payload.get("data_quality") or {}
    findings: list[dict[str, Any]] = []

    gm = latest.get("gross_margin_pct")
    prior_gm = prior.get("gross_margin_pct")
    gm_delta = round(gm - prior_gm, 2) if gm is not None and prior_gm is not None else None
    revenue = latest.get("revenue")
    cogs = latest.get("cogs")
    cogs_ratio = round(cogs / revenue * 100, 2) if revenue and cogs is not None else None
    prior_cogs_ratio = round(prior["cogs"] / prior["revenue"] * 100, 2) if prior.get("revenue") and prior.get("cogs") else None
    net_profit = latest.get("net_profit")
    net_margin = latest.get("net_margin_pct")
    runway = latest.get("cash_runway_months")
    inventory_days = latest.get("inventory_days")

    if gm_delta is not None and gm_delta <= -2:
        severity = "CRITICAL" if gm_delta <= -3 else "HIGH"
        findings.append(
            _finding(
                "gross_margin_decline",
                "CONFIRMED_FACT",
                severity,
                f"Gross margin fell {abs(gm_delta):.1f}pp month on month",
                f"Gross margin declined from {prior_gm:.2f}% in {prior.get('label')} to {gm:.2f}% in {latest.get('label')}. "
                f"This is a measured change from validated observations, not an estimate.",
                "profitability",
                {
                    "period": latest.get("label"),
                    "metrics": [
                        {"key": "gross_margin_pct", "value": gm, "comparison": prior_gm, "unit": "pct"},
                        {"key": "cogs_ratio_pct", "value": cogs_ratio, "comparison": prior_cogs_ratio, "unit": "pct"},
                        {"key": "revenue", "value": revenue, "unit": "USD"},
                        {"key": "cogs", "value": cogs, "unit": "USD"},
                    ],
                    "sources": [source["name"] for source in quality.get("sources", [])],
                },
                0.98,
            )
        )

    if gm is not None and gm < MARGIN_TARGET:
        findings.append(
            _finding(
                "gross_margin_below_target",
                "CONFIRMED_FACT",
                "HIGH" if gm < MARGIN_TARGET - 3 else "MEDIUM",
                f"Gross margin below the {MARGIN_TARGET:.0f}% operating target",
                f"The latest gross margin of {gm:.2f}% is {MARGIN_TARGET - gm:.2f}pp below the configured target. "
                "Target variance is calculated deterministically.",
                "profitability",
                {"metrics": [{"key": "gross_margin_pct", "value": gm}, {"key": "target_pct", "value": MARGIN_TARGET}]},
                0.99,
            )
        )

    if len(periods) >= 6 and gm is not None:
        history = [period["gross_margin_pct"] for period in periods[-7:-1] if period.get("gross_margin_pct") is not None]
        if len(history) >= 4:
            mean = statistics.mean(history)
            stdev = statistics.pstdev(history)
            if stdev > 0:
                z_score = (gm - mean) / stdev
                if z_score <= -1.8:
                    findings.append(
                        _finding(
                            "gross_margin_statistical_anomaly",
                            "STATISTICAL_ANOMALY",
                            "HIGH",
                            f"Gross margin is {abs(z_score):.1f} standard deviations below its recent mean",
                            f"The latest margin of {gm:.2f}% is {z_score:.2f} sigma from the trailing six-month mean of {mean:.2f}% "
                            f"(population standard deviation {stdev:.2f}). This is a statistical detection, not proof of cause.",
                            "profitability",
                            {
                                "z_score": round(z_score, 2),
                                "mean": round(mean, 2),
                                "stdev": round(stdev, 2),
                                "sample_months": len(history),
                            },
                            0.9,
                        )
                    )

    if cogs_ratio is not None and prior_cogs_ratio is not None and cogs_ratio - prior_cogs_ratio >= 1.5:
        findings.append(
            _finding(
                "cogs_ratio_rise",
                "CONFIRMED_FACT",
                "HIGH",
                f"Cost of goods sold rose to {cogs_ratio:.1f}% of revenue",
                f"COGS intensity increased {cogs_ratio - prior_cogs_ratio:.2f}pp versus the prior month. "
                "This is a measured ratio change and a direct arithmetic driver of gross margin compression; it does not by itself prove why costs rose.",
                "cost_of_sales",
                {
                    "metrics": [
                        {"key": "cogs_ratio_pct", "value": cogs_ratio, "comparison": prior_cogs_ratio},
                        {"key": "cogs", "value": cogs},
                        {"key": "revenue", "value": revenue},
                    ]
                },
                0.97,
            )
        )

    supplier = drivers.get("supplier_cost_index") or {}
    if supplier.get("value") and supplier["value"] > 105:
        findings.append(
            _finding(
                "supplier_cost_pressure",
                "HYPOTHESIS",
                "HIGH" if supplier["value"] > 112 else "MEDIUM",
                "Supplier cost escalation is a plausible driver",
                f"The supplier cost index is {supplier['value']:.1f} (base 100). This is consistent with landed cost pressure, "
                "but correlation is not proof; supplier contract and invoice-level review is required.",
                "procurement",
                {"supplier_cost_index": supplier["value"], "note": supplier.get("note", "")},
                0.62,
            )
        )

    discount = drivers.get("discount_depth_pct") or {}
    if discount.get("value") and discount["value"] >= 9:
        findings.append(
            _finding(
                "discount_depth",
                "POTENTIAL_RISK",
                "HIGH" if discount["value"] >= 11 else "MEDIUM",
                f"Promotional discount depth is {discount['value']:.1f}%",
                "Elevated discounting can compress realised price and gross margin. The relationship must be tested against channel-level price and volume data before attributing the margin decline to discounting.",
                "commercial",
                {"discount_depth_pct": discount["value"], "note": discount.get("note", "")},
                0.7,
            )
        )

    channel_mix = snapshot_payload.get("channels") or []
    if channel_mix:
        dominant = channel_mix[0]
        wholesale = next((channel for channel in channel_mix if channel.get("channel") == "Wholesale"), None)
        if wholesale and wholesale.get("share_pct", 0) >= 12:
            findings.append(
                _finding(
                    "channel_mix",
                    "HYPOTHESIS",
                    "MEDIUM",
                    "Channel mix may be diluting margin",
                    f"Wholesale represents {wholesale['share_pct']:.1f}% of revenue while the largest channel ({dominant['channel']}) is {dominant['share_pct']:.1f}%. "
                    "Channel margin observations show wholesale earns a lower gross margin; mix attribution requires a controlled decomposition.",
                    "commercial",
                    {"channels": channel_mix},
                    0.55,
                )
            )

    if net_margin is not None and net_margin < 3:
        findings.append(
            _finding(
                "thin_net_margin",
                "POTENTIAL_RISK",
                "HIGH" if net_margin < 0 else "MEDIUM",
                f"Net margin is only {net_margin:.2f}%",
                f"Net profit of ${net_profit:,.0f} leaves little buffer for supplier or demand shocks. "
                "The figure is calculated from validated revenue, COGS and operating expenses.",
                "profitability",
                {"metrics": [{"key": "net_profit", "value": net_profit}, {"key": "net_margin_pct", "value": net_margin}]},
                0.95,
            )
        )

    if runway is not None and runway < 5:
        findings.append(
            _finding(
                "cash_runway",
                "POTENTIAL_RISK",
                "CRITICAL" if runway < 2 else "HIGH" if runway < 3.5 else "MEDIUM",
                f"Cash runway is {runway:.1f} months",
                f"Cash balance of ${latest.get('cash_balance', 0):,.0f} covers approximately {runway:.1f} months of operating expenses. "
                f"The treasury policy floor is ${MIN_CASH:,.0f}.",
                "liquidity",
                {"metrics": [{"key": "cash_balance", "value": latest.get("cash_balance")}, {"key": "cash_runway_months", "value": runway}]},
                0.96,
            )
        )

    stockout = drivers.get("stockout_risk_skus") or {}
    if stockout.get("value") or (inventory_days is not None and inventory_days > 55):
        findings.append(
            _finding(
                "inventory_risk",
                "POTENTIAL_RISK",
                "MEDIUM",
                "Inventory efficiency and availability need attention",
                f"Days of inventory is {inventory_days:.1f}" + (f" and {int(stockout['value'])} SKUs are below the reorder point." if stockout.get("value") else "."),
                "operations",
                {"inventory_days": inventory_days, "stockout_risk_skus": stockout.get("value")},
                0.8,
            )
        )

    churn = latest.get("churn_rate_pct")
    prior_churn = prior.get("churn_rate_pct")
    if churn is not None and prior_churn is not None and churn - prior_churn >= 0.15:
        findings.append(
            _finding(
                "customer_churn",
                "CONFIRMED_FACT",
                "MEDIUM",
                f"Customer churn increased to {churn:.2f}%",
                f"Churn rose {churn - prior_churn:.2f}pp versus the prior month. This is a measured change in customer status data.",
                "customers",
                {"churn_rate_pct": churn, "prior_churn_rate_pct": prior_churn},
                0.9,
            )
        )

    revenue_change = _pct_change(revenue, prior.get("revenue"))
    if revenue_change is not None and revenue_change <= -5:
        findings.append(
            _finding(
                "revenue_decline",
                "CONFIRMED_FACT",
                "CRITICAL" if revenue_change <= -10 else "HIGH",
                f"Revenue declined {abs(revenue_change):.1f}%",
                f"Revenue moved from ${prior.get('revenue'):,.0f} to ${revenue:,.0f}.",
                "revenue",
                {"revenue": revenue, "prior_revenue": prior.get("revenue"), "change_pct": round(revenue_change, 2)},
                0.98,
            )
        )

    opex = latest.get("operating_expenses")
    prior_opex = prior.get("operating_expenses")
    if opex and prior_opex and opex > prior_opex * 1.08:
        findings.append(
            _finding(
                "opex_growth",
                "CONFIRMED_FACT",
                "MEDIUM",
                "Operating expenses grew faster than 8% month on month",
                f"Operating expenses increased from ${prior_opex:,.0f} to ${opex:,.0f}.",
                "expenses",
                {"operating_expenses": opex, "prior_operating_expenses": prior_opex},
                0.95,
            )
        )

    completeness = quality.get("completeness_pct")
    if completeness is not None and completeness < 95:
        findings.append(
            _finding(
                "data_completeness",
                "MISSING_INFORMATION",
                "MEDIUM" if completeness >= 85 else "HIGH",
                f"Business data completeness is {completeness:.1f}%",
                "One or more required monthly metrics are missing. Missing values are not treated as zero and may affect the reliability of conclusions.",
                "data_quality",
                {"completeness_pct": completeness, "missing": quality.get("stale_sources", [])},
                0.99,
            )
        )
    if quality.get("stale_sources"):
        findings.append(
            _finding(
                "stale_sources",
                "MISSING_INFORMATION",
                "HIGH",
                "Stale data sources detected",
                "The following sources exceed the freshness threshold: " + ", ".join(quality["stale_sources"]),
                "data_quality",
                {"stale_sources": quality["stale_sources"]},
                0.99,
            )
        )

    severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
    findings.sort(key=lambda item: severity_rank.get(item["severity"], 0), reverse=True)
    root_causes = [
        finding
        for finding in findings
        if finding["kind"] in {"HYPOTHESIS", "STATISTICAL_ANOMALY", "POTENTIAL_RISK"}
        and finding["area"] in {"procurement", "commercial", "cost_of_sales"}
    ]
    confirmed = [finding for finding in findings if finding["kind"] == "CONFIRMED_FACT"]
    primary = next((finding for finding in findings if finding["id"] == "gross_margin_decline"), findings[0] if findings else None)
    issue = None
    if primary:
        issue = {
            "key": primary["id"],
            "title": primary["title"],
            "severity": primary["severity"],
            "area": primary["area"],
            "summary": primary["detail"],
            "evidence": [finding["evidence"] for finding in findings if finding["severity"] in {"HIGH", "CRITICAL"}][:6],
            "findings": findings,
            "confirmed_facts": [finding["id"] for finding in confirmed],
            "hypotheses": [finding["id"] for finding in root_causes],
        }
    deterministic_summary = (
        f"Detected {len(confirmed)} confirmed issue(s), {len(root_causes)} hypothesis/risk item(s) "
        f"and {sum(1 for f in findings if f['kind'] == 'MISSING_INFORMATION')} data-quality item(s). "
        f"Highest severity: {findings[0]['severity'] if findings else 'NONE'}."
    )
    return {
        "findings": findings,
        "issue": issue,
        "summary": deterministic_summary,
        "counts": {
            "confirmed_facts": len(confirmed),
            "statistical_anomalies": sum(1 for finding in findings if finding["kind"] == "STATISTICAL_ANOMALY"),
            "potential_risks": sum(1 for finding in findings if finding["kind"] == "POTENTIAL_RISK"),
            "hypotheses": sum(1 for finding in findings if finding["kind"] == "HYPOTHESIS"),
            "missing_information": sum(1 for finding in findings if finding["kind"] == "MISSING_INFORMATION"),
        },
    }
