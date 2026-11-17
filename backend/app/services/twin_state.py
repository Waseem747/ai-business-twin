"""Digital twin state builder.

Reads validated observations, aggregates monthly actuals, runs deterministic
KPI functions and persists an immutable snapshot.  Every published number
carries evidence references back to the observations that produced it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.utils import utcnow
from app.domain.models import Business, BusinessMetric, DataSource, MetricSnapshot, Observation
from app.logic import kpis
from app.services.ingestion import ingestion_service

MONTHLY_METRICS = {
    "revenue",
    "cogs",
    "marketing_spend",
    "payroll",
    "occupancy",
    "other_opex",
    "cash_balance",
    "inventory_value",
    "receivables",
    "new_customers",
    "active_customers",
    "churned_customers",
    "units_sold",
    "supplier_cost_index",
}
BALANCE_METRICS = {"cash_balance", "inventory_value", "receivables", "active_customers"}


def _month_key(value: datetime) -> str:
    return value.strftime("%Y-%m")


def _month_label(value: datetime) -> str:
    return value.strftime("%b %Y")


def _change_pct(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return round((current - prior) / abs(prior) * 100, 2)


async def build_snapshot(
    session: AsyncSession,
    business: Business,
    *,
    as_of: datetime | None = None,
    persist: bool = True,
    created_by: str = "business-logic-engine",
) -> MetricSnapshot:
    as_of = as_of or utcnow()
    observations = (
        await session.execute(
            select(Observation)
            .where(Observation.business_id == business.id, Observation.period_start <= as_of)
            .order_by(Observation.period_start)
        )
    ).scalars().all()
    sources = (
        await session.execute(select(DataSource).where(DataSource.business_id == business.id))
    ).scalars().all()
    source_names = {source.id: source.name for source in sources}

    monthly = [obs for obs in observations if obs.metric in MONTHLY_METRICS]
    grouped: dict[str, dict[str, list[Observation]]] = defaultdict(lambda: defaultdict(list))
    for obs in monthly:
        if not obs.period_start:
            continue
        grouped[_month_key(obs.period_start)][obs.metric].append(obs)

    periods: list[dict[str, Any]] = []
    evidence_by_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
    completeness: list[float] = []

    for period_key in sorted(grouped):
        bucket = grouped[period_key]
        values: dict[str, float | None] = {}
        for metric in MONTHLY_METRICS:
            rows = bucket.get(metric, [])
            if not rows:
                values[metric] = None
            elif metric in BALANCE_METRICS:
                latest = max(rows, key=lambda row: row.period_end or row.period_start or utcnow())
                values[metric] = latest.value
            else:
                values[metric] = sum(row.value for row in rows)
        required = ["revenue", "cogs", "marketing_spend", "payroll", "occupancy", "other_opex"]
        completeness.append(sum(1 for key in required if values.get(key) is not None) / len(required))

        revenue, cogs = values["revenue"], values["cogs"]
        gross_profit = kpis.gross_profit(revenue, cogs)
        gross_margin = kpis.gross_margin_pct(revenue, cogs)
        opex = kpis.operating_expenses(
            values["marketing_spend"], values["payroll"], values["occupancy"], values["other_opex"]
        )
        net = kpis.net_profit(revenue, cogs, opex)
        inventory = values["inventory_value"]
        inventory_turnover = (
            kpis.inventory_turnover(cogs * 12, inventory) if cogs is not None and inventory else None
        )
        inventory_days = kpis.inventory_days(inventory_turnover)
        dso = kpis.days_sales_outstanding(values["receivables"], revenue, 30)
        runway = kpis.cash_runway_months(values["cash_balance"], opex)
        marketing_ratio = (
            round(revenue / values["marketing_spend"], 2)
            if revenue is not None and values["marketing_spend"]
            else None
        )
        active_customers = values["active_customers"]
        churned = values["churned_customers"]
        churn_rate = (
            round(churned / active_customers * 100, 2)
            if churned is not None and active_customers
            else None
        )
        start = min(row.period_start for row in bucket.get("revenue", []) if row.period_start) if bucket.get("revenue") else None
        period = {
            "period": period_key,
            "label": _month_label(start) if start else period_key,
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "gross_margin_pct": gross_margin,
            "marketing_spend": values["marketing_spend"],
            "payroll": values["payroll"],
            "occupancy": values["occupancy"],
            "other_opex": values["other_opex"],
            "operating_expenses": opex,
            "net_profit": net,
            "net_margin_pct": kpis.net_margin_pct(revenue, net),
            "cash_balance": values["cash_balance"],
            "cash_runway_months": runway,
            "inventory_value": inventory,
            "inventory_days": inventory_days,
            "receivables": values["receivables"],
            "dso_days": dso,
            "units_sold": values["units_sold"],
            "new_customers": values["new_customers"],
            "active_customers": active_customers,
            "churned_customers": churned,
            "churn_rate_pct": churn_rate,
            "marketing_ratio": marketing_ratio,
            "supplier_cost_index": values["supplier_cost_index"],
            "complete": all(values.get(key) is not None for key in required),
        }
        periods.append(period)
        for metric, rows in bucket.items():
            for row in rows[-2:]:
                evidence_by_metric[metric].append(
                    {
                        "observation_id": row.id,
                        "metric": row.metric,
                        "value": row.value,
                        "period": row.period_start.isoformat() if row.period_start else None,
                        "source": source_names.get(row.data_source_id, row.data_source_id),
                        "simulated": bool((row.quality or {}).get("simulated")),
                    }
                )

    periods = [p for p in periods if p["revenue"] is not None]
    if not periods:
        raise ValueError("No validated revenue observations are available to build a business state")

    latest = periods[-1]
    prior = periods[-2] if len(periods) > 1 else None
    three_month_avg = None
    if len(periods) >= 3:
        three_month_avg = round(sum(p["gross_margin_pct"] or 0 for p in periods[-3:]) / 3, 2)

    latest_metrics = {
        "gross_margin_pct": latest["gross_margin_pct"],
        "net_margin_pct": latest["net_margin_pct"],
        "cash_runway_months": latest["cash_runway_months"],
        "revenue_growth_pct": kpis.revenue_growth_pct(latest["revenue"], prior["revenue"] if prior else None),
        "inventory_days": latest["inventory_days"],
    }
    health = kpis.health_score(latest_metrics)

    channel_rows = [
        obs
        for obs in observations
        if obs.metric == "revenue"
        and obs.period_start
        and _month_key(obs.period_start) == latest["period"]
    ]
    channels: dict[str, float] = defaultdict(float)
    for row in channel_rows:
        channels[row.channel or "Unassigned"] += row.value
    channel_total = sum(channels.values()) or 1
    channel_mix = [
        {"channel": channel, "revenue": round(value, 2), "share_pct": round(value / channel_total * 100, 2)}
        for channel, value in sorted(channels.items(), key=lambda item: item[1], reverse=True)
    ]

    trend_keys = ["revenue", "gross_margin_pct", "gross_profit", "net_profit", "net_margin_pct", "cash_balance", "inventory_value", "operating_expenses"]
    trends = {
        key: [{"period": p["label"], "value": p[key]} for p in periods if p.get(key) is not None]
        for key in trend_keys
    }
    trends["channels"] = []
    for period in periods[-6:]:
        for channel in ("Stores", "Online", "Wholesale"):
            rows = [
                obs
                for obs in observations
                if obs.metric == "revenue"
                and obs.channel == channel
                and obs.period_start
                and _month_key(obs.period_start) == period["period"]
            ]
            if rows:
                trends["channels"].append(
                    {"period": period["label"], "channel": channel, "value": round(sum(r.value for r in rows), 2)}
                )

    daily_rows = [
        obs
        for obs in observations
        if obs.metric == "daily_revenue" and obs.period_start and (as_of - obs.period_start).days <= 45
    ]
    daily: dict[str, float] = defaultdict(float)
    for row in daily_rows:
        if row.period_start:
            daily[row.period_start.date().isoformat()] += row.value
    daily_series = [{"date": day, "value": round(value, 2)} for day, value in sorted(daily.items())][-30:]

    discounts = [
        obs
        for obs in observations
        if obs.metric in {"discount_depth_pct", "supplier_price_notice_pct", "stockout_risk_skus"}
        and obs.period_start
        and _month_key(obs.period_start) == latest["period"]
    ]
    drivers = {
        obs.metric: {
            "value": obs.value,
            "unit": obs.unit,
            "note": (obs.payload or {}).get("note") or (obs.payload or {}).get("supplier") or "",
            "source": source_names.get(obs.data_source_id, ""),
        }
        for obs in discounts
    }

    kpi_tiles = [
        {
            "key": "revenue",
            "label": "Revenue",
            "value": latest["revenue"],
            "unit": "USD",
            "change_pct": kpis.revenue_growth_pct(latest["revenue"], prior["revenue"] if prior else None),
            "good_direction": "up",
            "period": latest["label"],
        },
        {
            "key": "gross_margin",
            "label": "Gross margin",
            "value": latest["gross_margin_pct"],
            "unit": "pct",
            "change_pp": round((latest["gross_margin_pct"] or 0) - (prior["gross_margin_pct"] or 0), 2) if prior else None,
            "good_direction": "up",
            "period": latest["label"],
        },
        {
            "key": "net_profit",
            "label": "Net profit",
            "value": latest["net_profit"],
            "unit": "USD",
            "change_pct": _change_pct(latest["net_profit"], prior["net_profit"] if prior else None),
            "good_direction": "up",
            "period": latest["label"],
        },
        {
            "key": "cash_balance",
            "label": "Cash balance",
            "value": latest["cash_balance"],
            "unit": "USD",
            "change_pct": _change_pct(latest["cash_balance"], prior["cash_balance"] if prior else None),
            "good_direction": "up",
            "period": latest["label"],
        },
        {
            "key": "cash_runway",
            "label": "Cash runway",
            "value": latest["cash_runway_months"],
            "unit": "months",
            "change_pct": _change_pct(latest["cash_runway_months"], prior["cash_runway_months"] if prior else None),
            "good_direction": "up",
            "period": latest["label"],
        },
        {
            "key": "health_score",
            "label": "Business health",
            "value": health["score"],
            "unit": "score",
            "change_pct": None,
            "good_direction": "up",
            "period": latest["label"],
        },
    ]

    source_health = await ingestion_service.source_health(session, business.id)
    stale_sources = [source for source in source_health if source["stale"]]
    completeness_score = round(sum(completeness) / len(completeness) * 100, 1) if completeness else 0.0

    margin_delta = (
        round((latest["gross_margin_pct"] or 0) - (prior["gross_margin_pct"] or 0), 2) if prior else None
    )
    summary = (
        f"{business.name} generated ${latest['revenue']:,.0f} in {latest['label']} at a "
        f"{latest['gross_margin_pct']:.1f}% gross margin"
        f"{f', {margin_delta:+.1f}pp versus {prior['label']}' if margin_delta is not None else ''}. "
        f"Net profit was ${latest['net_profit']:,.0f} and cash runway "
        f"{latest['cash_runway_months']:.1f} months. Health score {health['score']}/100 ({health['grade']})."
    )

    payload = {
        "as_of": as_of.isoformat(),
        "business": {"id": business.id, "name": business.name, "currency": business.currency, "industry": business.industry},
        "periods": periods,
        "latest": latest,
        "prior": prior,
        "three_month_avg_gross_margin": three_month_avg,
        "kpis": kpi_tiles,
        "health": health,
        "channels": channel_mix,
        "trends": trends,
        "daily_revenue": daily_series,
        "drivers": drivers,
        "summary": summary,
        "data_quality": {
            "completeness_pct": completeness_score,
            "sources": source_health,
            "stale_sources": [source["name"] for source in stale_sources],
            "observations": len(observations),
            "cash_observation_used": bool(latest["cash_balance"] is not None),
        },
        "lineage": {
            "engine": "deterministic-kpi-v1",
            "input_refs": {metric: refs[:6] for metric, refs in evidence_by_metric.items()},
            "simulated_demo_data": any(source["simulated"] for source in source_health),
        },
    }

    snapshot = MetricSnapshot(
        business_id=business.id,
        as_of=as_of,
        snapshot_type="ACTUAL",
        health_score=health["score"],
        payload=payload,
        evidence={"input_refs": payload["lineage"]["input_refs"], "data_quality": payload["data_quality"]},
        created_by=created_by,
    )
    if persist:
        session.add(snapshot)
        await session.flush()
        metric_defs = [
            ("revenue", "Revenue", "USD"),
            ("gross_profit", "Gross profit", "USD"),
            ("gross_margin_pct", "Gross margin", "pct"),
            ("operating_expenses", "Operating expenses", "USD"),
            ("net_profit", "Net profit", "USD"),
            ("net_margin_pct", "Net margin", "pct"),
            ("cash_balance", "Cash balance", "USD"),
            ("cash_runway_months", "Cash runway", "months"),
            ("inventory_value", "Inventory value", "USD"),
            ("inventory_days", "Inventory days", "days"),
            ("dso_days", "Days sales outstanding", "days"),
            ("active_customers", "Active customers", "count"),
            ("new_customers", "New customers", "count"),
            ("churn_rate_pct", "Customer churn", "pct"),
        ]
        for key, label, unit in metric_defs:
            value = latest.get(key)
            session.add(
                BusinessMetric(
                    business_id=business.id,
                    snapshot_id=snapshot.id,
                    key=key,
                    label=label,
                    value=value,
                    unit=unit,
                    category="CALCULATED",
                    period_start=None,
                    period_end=None,
                    evidence={"period": latest["label"], "inputs": payload["lineage"]["input_refs"].get(key, [])[:4]},
                )
            )
        await session.flush()
    return snapshot


async def latest_snapshot(session: AsyncSession, business_id: str) -> MetricSnapshot | None:
    result = await session.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.business_id == business_id)
        .order_by(desc(MetricSnapshot.as_of))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def ensure_snapshot(
    session: AsyncSession, business: Business, *, max_age_minutes: int = 30
) -> MetricSnapshot:
    snapshot = await latest_snapshot(session, business.id)
    if snapshot and snapshot.as_of and snapshot.payload.get("periods"):
        age = (utcnow() - snapshot.as_of).total_seconds() / 60
        latest_obs = (
            await session.execute(
                select(Observation.recorded_at)
                .where(Observation.business_id == business.id)
                .order_by(desc(Observation.recorded_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if age <= max_age_minutes and (not latest_obs or latest_obs <= snapshot.as_of):
            return snapshot
    return await build_snapshot(session, business)
