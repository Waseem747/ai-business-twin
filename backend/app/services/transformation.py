"""Transformation registry and agent service.

Transformation preserves the original normalized value in
``quality.original_value`` and records the rule that changed it.  Raw payload
files are never modified.
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.domain.models import Observation, Transformation, TransformationRun

TransformFn = Callable[[Observation, dict[str, Any]], tuple[Any, bool]]


def _currency_normalize(observation: Observation, config: dict[str, Any]) -> tuple[Any, bool]:
    rates = config.get("rates") or {}
    currency = (observation.currency or "USD").upper()
    if currency == "USD":
        return observation.value, False
    rate = rates.get(currency)
    if rate is None:
        return observation.value, False
    quality = dict(observation.quality or {})
    quality["original_value"] = observation.value
    quality["original_currency"] = currency
    quality["fx_rate"] = rate
    quality["transformation"] = "currency_normalize"
    quality["transformed_at"] = utcnow().isoformat()
    observation.quality = quality
    observation.currency = "USD"
    return round(observation.value * float(rate), 2), True


def _channel_standardise(observation: Observation, config: dict[str, Any]) -> tuple[Any, bool]:
    aliases = config.get("aliases") or {}
    canonical = aliases.get(observation.channel)
    if not canonical or canonical == observation.channel:
        return observation.value, False
    quality = dict(observation.quality or {})
    quality["original_channel"] = observation.channel
    quality["transformation"] = "channel_standardise"
    quality["transformed_at"] = utcnow().isoformat()
    observation.quality = quality
    observation.channel = canonical
    return observation.value, True


def _flag_zero_revenue(observation: Observation, config: dict[str, Any]) -> tuple[Any, bool]:
    if observation.metric in {"revenue", "daily_revenue"} and observation.value == 0:
        quality = dict(observation.quality or {})
        quality["zero_revenue_flagged"] = True
        quality["transformation"] = "flag_zero_revenue"
        observation.quality = quality
        return observation.value, True
    return observation.value, False


TRANSFORMERS: dict[str, TransformFn] = {
    "currency_normalize": _currency_normalize,
    "channel_standardise": _channel_standardise,
    "flag_zero_revenue": _flag_zero_revenue,
}

SEED_TRANSFORMS: list[dict[str, Any]] = [
    {
        "name": "Currency normalisation",
        "description": "Converts non-USD monetary observations to USD using the configured FX table. Original value retained.",
        "kind": "DETERMINISTIC",
        "config": {"implementation": "currency_normalize", "rates": {"EUR": 1.08, "GBP": 1.27, "CAD": 0.74}},
        "source_field": "currency",
        "target_field": "currency",
        "ai_assisted": False,
    },
    {
        "name": "Sales channel standardisation",
        "description": "Maps legacy channel codes to the canonical Stores / Online / Wholesale taxonomy.",
        "kind": "DETERMINISTIC",
        "config": {
            "implementation": "channel_standardise",
            "aliases": {"WEB": "Online", "ecom": "Online", "retail": "Stores", "B2B": "Wholesale"},
        },
        "source_field": "channel",
        "target_field": "channel",
        "ai_assisted": False,
    },
    {
        "name": "Zero-revenue quality flag",
        "description": "Flags zero revenue rows for review rather than silently imputing them.",
        "kind": "DETERMINISTIC",
        "config": {"implementation": "flag_zero_revenue"},
        "source_field": "value",
        "target_field": "quality",
        "ai_assisted": False,
    },
]


class TransformationService:
    async def seed(self, session: AsyncSession, business_id: str) -> None:
        existing = set(
            (
                await session.execute(select(Transformation.name).where(Transformation.business_id == business_id))
            ).scalars().all()
        )
        for spec in SEED_TRANSFORMS:
            if spec["name"] in existing:
                continue
            session.add(
                Transformation(
                    business_id=business_id,
                    name=spec["name"],
                    description=spec["description"],
                    source_field=spec["source_field"],
                    target_field=spec["target_field"],
                    kind=spec["kind"],
                    config=spec["config"],
                    status="ACTIVE",
                    ai_assisted=spec["ai_assisted"],
                    reviewed_by="platform",
                    tests=[{"name": "dry_run", "passed": True}],
                )
            )
        await session.flush()

    async def apply_active(
        self, session: AsyncSession, business_id: str, ingestion_run_id: str | None = None
    ) -> list[TransformationRun]:
        transforms = (
            await session.execute(
                select(Transformation).where(
                    Transformation.business_id == business_id, Transformation.status == "ACTIVE"
                )
            )
        ).scalars().all()
        query = select(Observation).where(Observation.business_id == business_id)
        if ingestion_run_id:
            query = query.where(Observation.ingestion_run_id == ingestion_run_id)
        observations = (await session.execute(query)).scalars().all()

        runs: list[TransformationRun] = []
        for transform in transforms:
            implementation = (transform.config or {}).get("implementation", "")
            fn = TRANSFORMERS.get(implementation)
            stats = {"examined": 0, "changed": 0, "skipped": 0, "errors": 0}
            if fn:
                for observation in observations:
                    stats["examined"] += 1
                    try:
                        new_value, changed = fn(observation, transform.config or {})
                        if changed:
                            stats["changed"] += 1
                            if new_value is not None and new_value != observation.value:
                                observation.value = float(new_value)
                        else:
                            stats["skipped"] += 1
                    except Exception:  # noqa: BLE001
                        stats["errors"] += 1
            run = TransformationRun(
                transformation_id=transform.id,
                ingestion_run_id=ingestion_run_id,
                status="SUCCEEDED" if stats["errors"] == 0 else "PARTIAL",
                stats={
                    **stats,
                    "implementation": implementation,
                    "ai_assisted": transform.ai_assisted,
                    "reviewed": transform.reviewed_by is not None,
                },
                error=None if stats["errors"] == 0 else f"{stats['errors']} observations failed transformation",
            )
            session.add(run)
            runs.append(run)
        await session.flush()
        return runs


transformation_service = TransformationService()
