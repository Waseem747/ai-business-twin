"""Clearly-labelled simulated connectors used by the retail MVP demonstration.

No external API is called.  Generation is deterministic (seeded) and the
resulting data sources are flagged ``simulated=True`` everywhere in the system.
"""
from __future__ import annotations

import random
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from typing import Any

from app.connectors.base import Connector, Fact, FetchResult

CHANNELS = {"Stores": 0.54, "Online": 0.31, "Wholesale": 0.15}


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    last_day = monthrange(year, month)[1]
    return (
        datetime(year, month, 1, tzinfo=UTC),
        datetime(year, month, last_day, 23, 59, 59, tzinfo=UTC),
    )


def _series(as_of: datetime, count: int = 10) -> list[tuple[datetime, datetime, int]]:
    anchor = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    months: list[tuple[datetime, datetime, int]] = []
    for offset in range(count, 0, -1):
        year = anchor.year
        month = anchor.month - offset
        while month <= 0:
            month += 12
            year -= 1
        start, end = _month_bounds(year, month)
        months.append((start, end, offset))
    return months


# Revenue trajectory (index 0 = ten months ago) and gross margin compressing
# because landed supplier costs rise while discounting deepens.
_REVENUE = [460_000, 472_000, 486_000, 495_000, 508_000, 515_000, 528_000, 536_000, 548_000, 561_000]
_GROSS_MARGIN = [42.0, 41.6, 41.9, 41.2, 40.4, 39.2, 38.0, 36.4, 34.8, 31.2]
_CHANNEL_SHARE = [
    {"Stores": 0.58, "Online": 0.28, "Wholesale": 0.14},
    {"Stores": 0.57, "Online": 0.29, "Wholesale": 0.14},
    {"Stores": 0.56, "Online": 0.30, "Wholesale": 0.14},
    {"Stores": 0.56, "Online": 0.30, "Wholesale": 0.14},
    {"Stores": 0.55, "Online": 0.31, "Wholesale": 0.14},
    {"Stores": 0.54, "Online": 0.32, "Wholesale": 0.14},
    {"Stores": 0.53, "Online": 0.33, "Wholesale": 0.14},
    {"Stores": 0.51, "Online": 0.35, "Wholesale": 0.14},
    {"Stores": 0.49, "Online": 0.37, "Wholesale": 0.14},
    {"Stores": 0.47, "Online": 0.39, "Wholesale": 0.14},
]


def _stable_jitter(period: datetime, channel: str, salt: str, amplitude: float = 0.012) -> float:
    seed = f"{period:%Y-%m}-{channel}-{salt}"
    rng = random.Random(seed)
    return 1 + rng.uniform(-amplitude, amplitude)


class SimulatedPosConnector(Connector):
    kind = "SIMULATED_POS"
    version = "1.0"
    simulated = True

    async def fetch(self, since: datetime | None, cursor: dict[str, Any]) -> FetchResult:
        as_of = datetime.now(UTC)
        facts: list[Fact] = []
        months = _series(as_of, 10)
        raw: dict[str, Any] = {"generator": "northwind-demo-pos-v1", "months": [], "daily": []}

        for index, (start, end, _offset) in enumerate(months):
            revenue = _REVENUE[index]
            shares = _CHANNEL_SHARE[index]
            margins = _GROSS_MARGIN[index]
            month_raw = {"period": start.strftime("%Y-%m"), "revenue": revenue, "gross_margin_pct": margins}
            raw["months"].append(month_raw)
            for channel, share in shares.items():
                channel_revenue = round(revenue * share * _stable_jitter(start, channel, "rev"), 2)
                facts.append(
                    Fact(
                        entity="revenue",
                        metric="revenue",
                        period_start=start,
                        period_end=end,
                        value=channel_revenue,
                        channel=channel,
                        category="sales",
                        payload={
                            "demo": True,
                            "generator": "northwind-demo-pos-v1",
                            "channel": channel,
                            "gross_margin_context": margins,
                        },
                        quality={"simulated": True, "validated": False},
                    )
                )
            units = round(revenue / (71.5 + index * 0.6))
            facts.append(
                Fact(
                    entity="units_sold",
                    metric="units_sold",
                    period_start=start,
                    period_end=end,
                    value=units,
                    unit="units",
                    category="sales",
                    payload={"demo": True, "average_order_value": round(revenue / units, 2)},
                    quality={"simulated": True},
                )
            )
            channel_margins = {
                "Stores": margins + 3.2,
                "Online": margins + 1.1,
                "Wholesale": margins - 6.5,
            }
            for channel, margin in channel_margins.items():
                facts.append(
                    Fact(
                        entity="channel_margin",
                        metric="channel_gross_margin_pct",
                        period_start=start,
                        period_end=end,
                        value=round(margin, 2),
                        unit="pct",
                        channel=channel,
                        category="profitability",
                        payload={"demo": True, "channel": channel},
                        quality={"simulated": True},
                    )
                )

        # Last 30 days of daily sales, useful for freshness and daily reporting.
        today = as_of.date()
        for days_ago in range(30, 0, -1):
            day = today - timedelta(days=days_ago)
            start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            end = start + timedelta(days=1) - timedelta(seconds=1)
            weekday_factor = 1.12 if day.weekday() >= 5 else 1.0
            daily_total = round(561_000 / 30 * weekday_factor * _stable_jitter(start, "all", "day", 0.06), 2)
            raw["daily"].append({"date": day.isoformat(), "revenue": daily_total})
            for channel, share in CHANNELS.items():
                facts.append(
                    Fact(
                        entity="revenue",
                        metric="daily_revenue",
                        period_start=start,
                        period_end=end,
                        value=round(daily_total * share, 2),
                        channel=channel,
                        category="sales_daily",
                        payload={"demo": True, "date": day.isoformat(), "channel": channel},
                        quality={"simulated": True},
                    )
                )
        facts.append(
            Fact(
                entity="discount_depth",
                metric="discount_depth_pct",
                period_start=months[-1][0],
                period_end=months[-1][1],
                value=11.8,
                unit="pct",
                category="commercial",
                payload={"demo": True, "note": "Average promotional discount depth increased from 6.4% in January"},
                quality={"simulated": True},
            )
        )
        return FetchResult(
            facts=facts,
            raw_payload=raw,
            schema={
                "revenue": "float",
                "units_sold": "int",
                "channel_gross_margin_pct": "float",
                "daily_revenue": "float",
                "discount_depth_pct": "float",
            },
            cursor={"last_day": (today - timedelta(days=1)).isoformat()},
            freshness_at=datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=23, minutes=59),
            notes="Simulated POS export - not a real external system",
            simulated=True,
        )


class SimulatedErpConnector(Connector):
    kind = "SIMULATED_ERP"
    version = "1.0"
    simulated = True

    async def fetch(self, since: datetime | None, cursor: dict[str, Any]) -> FetchResult:
        as_of = datetime.now(UTC)
        months = _series(as_of, 10)
        facts: list[Fact] = []
        raw: dict[str, Any] = {"generator": "northwind-demo-erp-v1", "months": []}

        for index, (start, end, _offset) in enumerate(months):
            revenue = _REVENUE[index]
            margin = _GROSS_MARGIN[index]
            cogs = round(revenue * (1 - margin / 100), 2)
            marketing = round(revenue * (0.108 + index * 0.0008), 2)
            payroll = round(55_000 + index * 900, 2)
            occupancy = 22_400
            other_opex = round(14_000 + index * 500, 2)
            cash = round(780_000 - index * 17_000 - (5000 if index > 6 else 0), 2)
            inventory = round(520_000 + index * 11_000, 2)
            receivables = round(66_000 + index * 2_900, 2)
            new_customers = round(392 - index * 3.6)
            active_customers = round(9_620 - index * 34)
            churned = round(active_customers * (0.031 + index * 0.0015))
            supplier_index = round(100 + index * 1.9 + (3.2 if index >= 7 else 0), 2)
            raw["months"].append(
                {
                    "period": start.strftime("%Y-%m"),
                    "revenue": revenue,
                    "cogs": cogs,
                    "cash": cash,
                    "inventory": inventory,
                }
            )
            base = {"demo": True, "generator": "northwind-demo-erp-v1"}
            for entity, metric, value, unit, category in [
                ("cogs", "cogs", cogs, "USD", "cost_of_sales"),
                ("expense", "marketing_spend", marketing, "USD", "operating_expense"),
                ("expense", "payroll", payroll, "USD", "operating_expense"),
                ("expense", "occupancy", occupancy, "USD", "operating_expense"),
                ("expense", "other_opex", other_opex, "USD", "operating_expense"),
                ("cash", "cash_balance", cash, "USD", "balance"),
                ("inventory", "inventory_value", inventory, "USD", "balance"),
                ("receivables", "receivables", receivables, "USD", "balance"),
                ("customers", "new_customers", new_customers, "count", "customer"),
                ("customers", "active_customers", active_customers, "count", "customer"),
                ("customers", "churned_customers", churned, "count", "customer"),
                ("supplier", "supplier_cost_index", supplier_index, "index", "procurement"),
            ]:
                facts.append(
                    Fact(
                        entity=entity,
                        metric=metric,
                        period_start=start,
                        period_end=end,
                        value=float(value),
                        unit=unit,
                        category=category,
                        payload={**base, "period": start.strftime("%Y-%m")},
                        quality={"simulated": True},
                    )
                )
        facts.append(
            Fact(
                entity="supplier",
                metric="supplier_price_notice_pct",
                period_start=months[-1][0],
                period_end=months[-1][1],
                value=6.5,
                unit="pct",
                category="procurement",
                payload={
                    "demo": True,
                    "supplier": "Atlas Home Goods",
                    "effective_note": "Price notice effective two months ago; contract renewal in 45 days",
                },
                quality={"simulated": True},
            )
        )
        facts.append(
            Fact(
                entity="inventory",
                metric="stockout_risk_skus",
                period_start=months[-1][0],
                period_end=months[-1][1],
                value=17,
                unit="count",
                category="operations",
                payload={"demo": True, "note": "17 SKUs below reorder point"},
                quality={"simulated": True},
            )
        )
        return FetchResult(
            facts=facts,
            raw_payload=raw,
            schema={
                "cogs": "float",
                "marketing_spend": "float",
                "payroll": "float",
                "occupancy": "float",
                "other_opex": "float",
                "cash_balance": "float",
                "inventory_value": "float",
                "receivables": "float",
                "new_customers": "int",
                "active_customers": "int",
                "churned_customers": "int",
                "supplier_cost_index": "float",
            },
            cursor={"last_period": months[-1][0].strftime("%Y-%m")},
            freshness_at=datetime.now(UTC) - timedelta(hours=3),
            notes="Simulated ERP export - not a real external system",
            simulated=True,
        )
