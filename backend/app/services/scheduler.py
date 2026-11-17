"""APScheduler jobs: daily intelligence cycle and data-freshness monitoring."""
from __future__ import annotations

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import desc, select

from app.config import settings
from app.core.utils import utcnow
from app.db import session_scope
from app.domain.models import Business, DataSource, WorkflowRun
from app.services.alerts import alert_service
from app.services.ingestion import ingestion_service
from app.workflows.runner import workflow_runner

logger = logging.getLogger("business_twin.scheduler")
scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))


async def _businesses():
    async with session_scope() as session:
        return (await session.execute(select(Business))).scalars().all()


async def daily_business_cycle() -> None:
    async with session_scope() as session:
        businesses = (await session.execute(select(Business))).scalars().all()
        for business in businesses:
            active = (
                await session.execute(
                    select(WorkflowRun).where(
                        WorkflowRun.business_id == business.id,
                        WorkflowRun.workflow == "daily_bi",
                        WorkflowRun.status.in_(["RUNNING", "WAITING_APPROVAL", "WAITING_HUMAN_REVIEW"]),
                        WorkflowRun.started_at > utcnow() - timedelta(hours=3),
                    )
                )
            ).scalar_one_or_none()
            if active:
                logger.info("Skipping daily cycle for %s; run %s is already active", business.name, active.id)
                continue
            run = await workflow_runner.start(
                session,
                business=business,
                workflow="daily_bi",
                inputs={},
                actor="scheduler",
                trigger="SCHEDULE",
            )
            logger.info("Started daily business intelligence run %s for %s", run.id, business.name)


async def freshness_scan() -> None:
    async with session_scope() as session:
        businesses = (await session.execute(select(Business))).scalars().all()
        for business in businesses:
            health = await ingestion_service.source_health(session, business.id)
            for source in health:
                if not source["stale"]:
                    continue
                await alert_service.upsert(
                    session,
                    business_id=business.id,
                    dedup_key=f"stale_source:{source['id']}",
                    title=f"Stale data source: {source['name']}",
                    detail=(
                        f"Source freshness is {source['age_hours']} hours old; policy threshold is "
                        f"{settings.data_stale_after_hours} hours. Missing data is never treated as zero."
                    ),
                    severity="HIGH",
                    area="data_quality",
                    evidence={"source_id": source["id"], "freshness_at": source["freshness_at"], "age_hours": source["age_hours"]},
                    actor="data-freshness-monitor",
                )
        await session.commit()


def start_scheduler() -> None:
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled by configuration")
        return
    if scheduler.running:
        return
    scheduler.add_job(
        daily_business_cycle,
        "cron",
        hour=settings.daily_report_cron_hour,
        minute=settings.daily_report_cron_minute,
        id="daily_business_cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        freshness_scan,
        "interval",
        minutes=30,
        id="freshness_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: daily cycle %02d:%02d %s; freshness scan every 30 minutes",
        settings.daily_report_cron_hour,
        settings.daily_report_cron_minute,
        settings.timezone,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
