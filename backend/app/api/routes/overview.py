"""Overview, business events and system metadata."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import BusinessDep, DBSession
from app.api.serializers import agent_out, alert_out, decision_out, dt, notification_out, source_out, workflow_out
from app.config import settings
from app.core.security import CurrentUser
from app.domain.models import (
    Agent,
    Alert,
    Approval,
    BusinessEvent,
    DataSource,
    Decision,
    MetricSnapshot,
    Notification,
    WorkflowRun,
)
from app.services.ingestion import ingestion_service
from app.services.twin_state import ensure_snapshot
from app.workflows.checkpointer import checkpoint_is_durable

router = APIRouter(prefix="/api", tags=["Overview"])


@router.get("/overview")
async def overview(business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    snapshot = await ensure_snapshot(db, business, max_age_minutes=60)
    await db.commit()
    alerts = (
        await db.execute(select(Alert).where(Alert.business_id == business.id).order_by(desc(Alert.last_seen)).limit(50))
    ).scalars().all()
    decisions = (
        await db.execute(select(Decision).where(Decision.business_id == business.id).order_by(desc(Decision.created_at)).limit(20))
    ).scalars().all()
    approvals = (
        await db.execute(
            select(Approval)
            .where(Approval.business_id == business.id, Approval.status == "PENDING")
            .order_by(desc(Approval.created_at))
        )
    ).scalars().all()
    agents = (
        await db.execute(select(Agent).where(Agent.business_id == business.id).order_by(Agent.name))
    ).scalars().all()
    workflows = (
        await db.execute(
            select(WorkflowRun).where(WorkflowRun.business_id == business.id).order_by(desc(WorkflowRun.started_at)).limit(12)
        )
    ).scalars().all()
    sources = (
        await db.execute(select(DataSource).where(DataSource.business_id == business.id))
    ).scalars().all()
    source_health = {item["id"]: item for item in await ingestion_service.source_health(db, business.id)}
    events = (
        await db.execute(
            select(BusinessEvent).where(BusinessEvent.business_id == business.id).order_by(desc(BusinessEvent.created_at)).limit(20)
        )
    ).scalars().all()
    notifications = (
        await db.execute(
            select(Notification).where(Notification.business_id == business.id).order_by(desc(Notification.created_at)).limit(10)
        )
    ).scalars().all()
    open_alerts = [alert for alert in alerts if alert.status != "RESOLVED"]
    pending_decisions = [decision for decision in decisions if decision.status in {"AWAITING_APPROVAL", "AUDITED", "APPROVED", "DRAFT"}]
    decisions_by_id = {decision.id: decision for decision in decisions}

    return {
        "business": {
            "id": business.id,
            "name": business.name,
            "industry": business.industry,
            "currency": business.currency,
            "is_demo": business.is_demo,
            "description": business.description,
        },
        "user": {"name": user.full_name, "role": user.role, "email": user.email, "title": user.title},
        "system": {
            "environment": settings.app_env,
            "llm_provider": settings.llm_provider,
            "model": settings.llm_model if settings.llm_provider == "openai" else settings.ollama_model if settings.llm_provider == "ollama" else "deterministic-template",
            "demo_mode": business.is_demo,
            "checkpoint_durable": checkpoint_is_durable(),
            "human_approval_threshold": settings.human_approval_threshold_usd,
        },
        "snapshot": {
            "id": snapshot.id,
            "as_of": dt(snapshot.as_of),
            "health_score": snapshot.health_score,
            "latest": snapshot.payload.get("latest"),
            "kpis": snapshot.payload.get("kpis"),
            "health": snapshot.payload.get("health"),
            "trends": snapshot.payload.get("trends"),
            "daily_revenue": snapshot.payload.get("daily_revenue"),
            "channels": snapshot.payload.get("channels"),
            "summary": snapshot.payload.get("summary"),
            "data_quality": snapshot.payload.get("data_quality"),
            "drivers": snapshot.payload.get("drivers"),
            "intelligence": snapshot.payload.get("intelligence"),
            "custom_logic": snapshot.payload.get("custom_logic"),
            "lineage": snapshot.payload.get("lineage"),
        },
        "alerts": [alert_out(alert) for alert in alerts],
        "alert_summary": {
            "open": len(open_alerts),
            "critical": sum(1 for alert in open_alerts if alert.severity == "CRITICAL"),
            "high": sum(1 for alert in open_alerts if alert.severity == "HIGH"),
            "acknowledged": sum(1 for alert in open_alerts if alert.status == "ACKNOWLEDGED"),
        },
        "decisions": [decision_out(decision) for decision in decisions],
        "decision_summary": {
            "total": len(decisions),
            "pending": len(pending_decisions),
            "awaiting_approval": sum(1 for decision in decisions if decision.status == "AWAITING_APPROVAL"),
            "executed": sum(1 for decision in decisions if decision.status in {"EXECUTED", "VERIFIED"}),
        },
        "approvals": [
            {
                "id": approval.id,
                "decision_id": approval.decision_id,
                "decision_title": decisions_by_id.get(approval.decision_id).title if decisions_by_id.get(approval.decision_id) else None,
                "status": approval.status,
                "requested_at": dt(approval.requested_at),
                "expected_financial_impact": decisions_by_id.get(approval.decision_id).expected_financial_impact if decisions_by_id.get(approval.decision_id) else None,
                "policy": approval.policy,
            }
            for approval in approvals
        ],
        "agents": [agent_out(agent) for agent in agents],
        "workflows": [workflow_out(run) for run in workflows],
        "sources": [source_out(source, source_health.get(source.id)) for source in sources],
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "title": event.title,
                "detail": event.detail,
                "severity": event.severity,
                "actor": event.actor,
                "related_type": event.related_type,
                "related_id": event.related_id,
                "created_at": dt(event.created_at),
            }
            for event in events
        ],
        "notifications": [notification_out(item) for item in notifications],
    }


@router.get("/business")
async def business_info(business: BusinessDep) -> dict:
    return {
        "id": business.id,
        "name": business.name,
        "industry": business.industry,
        "currency": business.currency,
        "is_demo": business.is_demo,
        "description": business.description,
    }


@router.get("/events")
async def events(business: BusinessDep, db: DBSession, limit: int = 50) -> list[dict]:
    rows = (
        await db.execute(
            select(BusinessEvent)
            .where(BusinessEvent.business_id == business.id)
            .order_by(desc(BusinessEvent.created_at))
            .limit(min(limit, 200))
        )
    ).scalars().all()
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "title": event.title,
            "detail": event.detail,
            "severity": event.severity,
            "actor": event.actor,
            "related_type": event.related_type,
            "related_id": event.related_id,
            "created_at": dt(event.created_at),
        }
        for event in rows
    ]


@router.get("/system")
async def system_info(user: CurrentUser) -> dict:
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model if settings.llm_provider == "openai" else settings.ollama_model if settings.llm_provider == "ollama" else "deterministic-template",
        "checkpoint_durable": checkpoint_is_durable(),
        "scheduler_enabled": settings.scheduler_enabled,
        "human_approval_threshold": settings.human_approval_threshold_usd,
        "max_audit_rounds": settings.max_audit_rounds,
        "timezone": settings.timezone,
    }
