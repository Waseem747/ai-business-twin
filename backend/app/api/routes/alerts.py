"""Alert, incident and notification routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from app.api.deps import BusinessDep, DBSession
from app.api.schemas import AlertAction
from app.api.serializers import alert_out, dt, notification_out
from app.core.security import CurrentUser
from app.domain.models import Alert, AlertEvent, BusinessEvent, Notification, WorkflowRun
from app.services.alerts import alert_service
from app.services.notifications import notification_service
from app.workflows.runner import workflow_runner

router = APIRouter(prefix="/api", tags=["Alerts & Incidents"])


@router.get("/alerts")
async def list_alerts(
    business: BusinessDep, db: DBSession, user: CurrentUser, status: str | None = None, limit: int = 100
) -> dict:
    alerts = await alert_service.list(db, business.id, status=status, limit=limit)
    summary = alert_service.incident_summary(
        (await db.execute(select(Alert).where(Alert.business_id == business.id))).scalars().all()
    )
    return {"alerts": [alert_out(alert) for alert in alerts], "summary": summary}


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    alert = await alert_service.get(db, alert_id, business.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    events = (
        await db.execute(
            select(AlertEvent).where(AlertEvent.alert_id == alert.id).order_by(AlertEvent.created_at)
        )
    ).scalars().all()
    payload = alert_out(alert)
    payload["events"] = [
        {"id": event.id, "kind": event.kind, "message": event.message, "actor": event.actor, "created_at": dt(event.created_at)}
        for event in events
    ]
    return payload


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge(alert_id: str, payload: AlertAction, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    alert = await alert_service.get(db, alert_id, business.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await alert_service.acknowledge(db, alert, user.email, payload.note)
    await db.commit()
    return alert_out(alert)


@router.post("/alerts/{alert_id}/resolve")
async def resolve(alert_id: str, payload: AlertAction, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    alert = await alert_service.get(db, alert_id, business.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await alert_service.resolve(db, alert, user.email, payload.note)
    await db.commit()
    return alert_out(alert)


@router.post("/alerts/{alert_id}/escalate")
async def escalate(alert_id: str, payload: AlertAction, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    alert = await alert_service.get(db, alert_id, business.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.escalation_level = min(3, (alert.escalation_level or 0) + 1)
    db.add(
        AlertEvent(
            alert_id=alert.id,
            kind="ESCALATED",
            message=payload.note or f"Escalated to level {alert.escalation_level}",
            actor=user.email,
        )
    )
    await db.commit()
    return alert_out(alert)


@router.post("/alerts/{alert_id}/investigate")
async def investigate(alert_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    if user.role not in {"ADMIN", "ANALYST", "APPROVER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    alert = await alert_service.get(db, alert_id, business.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    active = (
        await db.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.business_id == business.id,
                WorkflowRun.workflow == "decision_execution",
                WorkflowRun.status.in_(["RUNNING", "WAITING_APPROVAL", "WAITING_HUMAN_REVIEW"]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active:
        return {"workflow": {"id": active.id, "status": active.status}, "existing": True}
    run = await workflow_runner.start(
        db,
        business=business,
        workflow="decision_execution",
        inputs={"alert_id": alert.id},
        actor=user.email,
        trigger="ALERT",
    )
    await db.commit()
    return {"workflow": {"id": run.id, "status": run.status}, "existing": False}


@router.get("/notifications")
async def notifications(business: BusinessDep, db: DBSession, user: CurrentUser, limit: int = 30) -> list[dict]:
    rows = await notification_service.recent(db, business.id, limit)
    return [notification_out(row) for row in rows]
