"""Data acquisition service: fetch → raw lineage → validate → deduplicate → store."""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.base import Connector, Fact
from app.connectors.csv_excel import TabularConnector
from app.connectors.google_sheets import GoogleSheetsConnector
from app.connectors.rest import GraphQLConnector, RestConnector
from app.connectors.simulated import SimulatedErpConnector, SimulatedPosConnector
from app.connectors.sql_database import SqlDatabaseConnector
from app.core.utils import fingerprint, new_id, utcnow
from app.domain.models import BusinessEvent, DataSource, IngestionRun, Observation

CONNECTORS: dict[str, type[Connector]] = {
    "SIMULATED_POS": SimulatedPosConnector,
    "SIMULATED_ERP": SimulatedErpConnector,
    "REST": RestConnector,
    "GRAPHQL": GraphQLConnector,
    "SQL_DATABASE": SqlDatabaseConnector,
    "DATABASE": SqlDatabaseConnector,
    "GOOGLE_SHEETS": GoogleSheetsConnector,
    "CSV": TabularConnector,
    "EXCEL": TabularConnector,
    "TABULAR": TabularConnector,
}

REQUIRED_FACTS = {"revenue", "cogs", "marketing_spend", "cash_balance"}


def validate_fact(fact: Fact) -> tuple[bool, str | None]:
    if fact.value is None:
        return False, "value_missing"
    if not math.isfinite(float(fact.value)):
        return False, "value_not_finite"
    if fact.metric in {"revenue", "daily_revenue", "cogs", "marketing_spend", "payroll", "occupancy", "other_opex"} and fact.value < 0:
        return False, "negative_amount"
    if fact.metric in {"new_customers", "active_customers", "units_sold"} and fact.value < 0:
        return False, "negative_count"
    if fact.period_start and fact.period_start > datetime.now(UTC):
        return False, "future_period"
    if fact.period_start is None:
        return False, "period_missing"
    if not fact.metric:
        return False, "metric_missing"
    if not fact.entity:
        return False, "entity_missing"
    return True, None


def dedup_key(source_id: str, fact: Fact) -> str:
    period = fact.period_start.date().isoformat() if fact.period_start else "none"
    return fingerprint(source_id, fact.entity, fact.metric, period, fact.channel, fact.unit)


class IngestionService:
    async def sync_source(
        self,
        session: AsyncSession,
        source: DataSource,
        *,
        trigger: str = "MANUAL",
        actor: str = "data-acquisition-agent",
    ) -> IngestionRun:
        connector_cls = CONNECTORS.get(source.kind)
        run = IngestionRun(
            business_id=source.business_id,
            data_source_id=source.id,
            trigger=trigger,
            status="RUNNING",
            raw_payload_ref="",
        )
        session.add(run)
        await session.flush()
        source.status = "SYNCING"
        await session.flush()

        if not connector_cls:
            run.status = "FAILED"
            run.error = f"No connector registered for kind {source.kind}"
            run.finished_at = utcnow()
            source.status = "ERROR"
            source.last_error = run.error
            await session.flush()
            return run

        connector = connector_cls(source.config)
        try:
            result = await connector.fetch(source.last_sync_at, source.sync_cursor or {})
        except Exception as exc:  # noqa: BLE001 - failure must be persisted
            run.status = "FAILED"
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = utcnow()
            source.status = "ERROR"
            source.last_error = run.error
            await session.flush()
            return run

        # Store the raw payload before validation/normalisation. It is never overwritten.
        raw_dir = settings.storage_path / "raw" / source.id
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_file = raw_dir / f"{run.id}.json"
        raw_file.write_text(json.dumps(result.raw_payload, indent=2, default=str), encoding="utf-8")
        run.raw_payload_ref = str(raw_file)

        rejections: list[dict[str, Any]] = []
        valid: list[Fact] = []
        for index, fact in enumerate(result.facts):
            ok, reason = validate_fact(fact)
            if ok:
                valid.append(fact)
            else:
                rejections.append(
                    {
                        "index": index,
                        "metric": fact.metric,
                        "reason": reason,
                        "value": fact.value,
                        "period": fact.period_start.isoformat() if fact.period_start else None,
                    }
                )

        keys = [dedup_key(source.id, fact) for fact in valid]
        existing: set[str] = set()
        if keys:
            rows = await session.execute(
                select(Observation.dedup_key).where(Observation.dedup_key.in_(keys))
            )
            existing = set(rows.scalars().all())

        ingested = 0
        duplicates = 0
        seen: set[str] = set()
        for fact, key in zip(valid, keys):
            if key in existing or key in seen:
                duplicates += 1
                continue
            seen.add(key)
            observation = Observation(
                business_id=source.business_id,
                data_source_id=source.id,
                ingestion_run_id=run.id,
                entity=fact.entity,
                period_start=fact.period_start,
                period_end=fact.period_end,
                channel=fact.channel,
                category=fact.category,
                metric=fact.metric,
                value=float(fact.value),
                unit=fact.unit,
                currency=fact.currency,
                quality={**fact.quality, "validated": True, "validation_run": run.id, "simulated": source.simulated},
                payload=fact.payload,
                dedup_key=key,
                recorded_at=utcnow(),
            )
            session.add(observation)
            ingested += 1

        run.status = "SUCCEEDED"
        run.finished_at = utcnow()
        run.records_read = len(result.facts)
        run.records_ingested = ingested
        run.records_rejected = len(rejections)
        run.duplicates_blocked = duplicates
        run.freshness_at = result.freshness_at
        run.schema_snapshot = {
            **result.schema,
            "connector": connector.describe(),
            "rejection_rules": ["finite_value", "non_negative_amounts", "no_future_periods"],
        }
        run.lineage = {
            "source_id": source.id,
            "source_name": source.name,
            "connector": connector.describe(),
            "simulated": source.simulated,
            "raw_payload_ref": str(raw_file),
            "fetched_at": utcnow().isoformat(),
            "records": {"read": len(result.facts), "valid": len(valid), "ingested": ingested, "rejected": len(rejections), "duplicates": duplicates},
            "rejections": rejections[:25],
            "notes": result.notes,
            "cursor": result.cursor,
            "transformation_rule_version": "ingestion-v1",
        }
        source.status = "CONNECTED"
        source.last_sync_at = utcnow()
        source.freshness_at = result.freshness_at
        source.sync_cursor = result.cursor
        source.records_total = (source.records_total or 0) + ingested
        source.last_error = None
        await session.flush()

        session.add(
            BusinessEvent(
                business_id=source.business_id,
                event_type="DATA_SYNC",
                title=f"{source.name} synchronised",
                detail=f"{ingested} facts ingested, {duplicates} duplicates blocked, {len(rejections)} rejected. Simulated source: {source.simulated}.",
                severity="INFO" if not rejections else "LOW",
                actor=actor,
                related_type="ingestion_run",
                related_id=run.id,
                payload={"lineage": run.lineage},
            )
        )
        await session.flush()
        return run

    async def latest_ingestion(
        self, session: AsyncSession, business_id: str, source_id: str | None = None
    ) -> IngestionRun | None:
        query = select(IngestionRun).where(IngestionRun.business_id == business_id)
        if source_id:
            query = query.where(IngestionRun.data_source_id == source_id)
        result = await session.execute(query.order_by(IngestionRun.started_at.desc()).limit(1))
        return result.scalar_one_or_none()

    async def source_health(self, session: AsyncSession, business_id: str) -> list[dict[str, Any]]:
        sources = (
            await session.execute(select(DataSource).where(DataSource.business_id == business_id))
        ).scalars().all()
        now = utcnow()
        health = []
        for source in sources:
            age_hours = (
                round((now - source.freshness_at).total_seconds() / 3600, 1) if source.freshness_at else None
            )
            health.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "kind": source.kind,
                    "system": source.system,
                    "status": source.status,
                    "simulated": source.simulated,
                    "freshness_at": source.freshness_at.isoformat() if source.freshness_at else None,
                    "age_hours": age_hours,
                    "stale": age_hours is None or age_hours > settings.data_stale_after_hours,
                    "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
                    "last_error": source.last_error,
                    "records_total": source.records_total,
                }
            )
        return health

    async def observation_count(self, session: AsyncSession, business_id: str) -> int:
        return (
            await session.execute(
                select(func.count()).select_from(Observation).where(Observation.business_id == business_id)
            )
        ).scalar_one()


ingestion_service = IngestionService()
