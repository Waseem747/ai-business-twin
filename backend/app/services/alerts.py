"""Incident-grade alert service with deduplication, acknowledgement and escalation."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import fingerprint, utcnow
from app.domain.enums import AlertStatus
from app.domain.models import Alert, AlertEvent, BusinessEvent
from app.services.notifications import notification_service

SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


class AlertService:
    async def upsert(
        self,
        session: AsyncSession,
        *,
        business_id: str,
        dedup_key: str,
        title: str,
        detail: str,
        severity: str,
        area: str,
        evidence: dict[str, Any],
        actor: str = "monitoring-service",
    ) -> tuple[Alert, bool, bool]:
        """Return (alert, created, escalated). Repeated unresolved alerts are deduplicated."""
        fp = fingerprint("alert", business_id, dedup_key)
        existing = (
            await session.execute(select(Alert).where(Alert.fingerprint == fp))
        ).scalar_one_or_none()
        now = utcnow()
        if existing and existing.status == AlertStatus.RESOLVED:
            # A resolved incident does not suppress a new occurrence.
            fp = fingerprint("alert", business_id, dedup_key, existing.id, now.isoformat())
            existing = None
        if existing:
            existing.last_seen = now
            existing.occurrences += 1
            existing.evidence = evidence
            existing.detail = detail
            if SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(existing.severity, 0):
                existing.severity = severity
            escalated = False
            if (
                existing.status == AlertStatus.OPEN
                and existing.occurrences >= 3
                and existing.escalation_level < 2
                and now - existing.first_seen > timedelta(hours=12)
            ):
                existing.escalation_level += 1
                escalated = True
                session.add(
                    AlertEvent(
                        alert_id=existing.id,
                        kind="ESCALATED",
                        message=f"Unresolved after {existing.occurrences} occurrences; escalated to level {existing.escalation_level}.",
                        actor=actor,
                    )
                )
            await session.flush()
            return existing, False, escalated

        alert = Alert(
            business_id=business_id,
            fingerprint=fp,
            dedup_key=dedup_key,
            severity=severity,
            status=AlertStatus.OPEN,
            title=title,
            detail=detail,
            area=area,
            evidence=evidence,
            first_seen=now,
            last_seen=now,
        )
        session.add(alert)
        await session.flush()
        session.add(AlertEvent(alert_id=alert.id, kind="OPENED", message=detail, actor=actor))
        session.add(
            BusinessEvent(
                business_id=business_id,
                event_type="ALERT",
                title=title,
                detail=detail,
                severity=severity,
                actor=actor,
                related_type="alert",
                related_id=alert.id,
            )
        )
        await notification_service.send(
            session,
            business_id=business_id,
            subject=f"[{severity}] {title}",
            body=detail,
            channel="EMAIL" if levels_at_least(severity, "HIGH") else "IN_APP",
            related_type="alert",
            related_id=alert.id,
        )
        await session.flush()
        return alert, True, False

    async def acknowledge(self, session: AsyncSession, alert: Alert, actor: str, note: str = "") -> Alert:
        if alert.status == AlertStatus.RESOLVED:
            return alert
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = actor
        alert.acknowledged_at = utcnow()
        session.add(AlertEvent(alert_id=alert.id, kind="ACKNOWLEDGED", message=note or "Acknowledged", actor=actor))
        await session.flush()
        return alert

    async def resolve(self, session: AsyncSession, alert: Alert, actor: str, note: str = "") -> Alert:
        alert.status = AlertStatus.RESOLVED
        alert.resolved_by = actor
        alert.resolved_at = utcnow()
        alert.resolution_note = note
        session.add(AlertEvent(alert_id=alert.id, kind="RESOLVED", message=note or "Resolved", actor=actor))
        session.add(
            BusinessEvent(
                business_id=alert.business_id,
                event_type="ALERT_RESOLVED",
                title=f"Resolved: {alert.title}",
                detail=note,
                severity="INFO",
                actor=actor,
                related_type="alert",
                related_id=alert.id,
            )
        )
        await session.flush()
        return alert

    async def list(self, session: AsyncSession, business_id: str, status: str | None = None, limit: int = 100) -> list[Alert]:
        query = select(Alert).where(Alert.business_id == business_id)
        if status:
            query = query.where(Alert.status == status)
        result = await session.execute(query.order_by(desc(Alert.last_seen)).limit(limit))
        return list(result.scalars().all())

    async def get(self, session: AsyncSession, alert_id: str, business_id: str) -> Alert | None:
        alert = await session.get(Alert, alert_id)
        return alert if alert and alert.business_id == business_id else None

    def incident_summary(self, alerts: list[Alert]) -> dict[str, Any]:
        open_alerts = [alert for alert in alerts if alert.status != AlertStatus.RESOLVED]
        return {
            "open": len(open_alerts),
            "critical": sum(1 for alert in open_alerts if alert.severity == "CRITICAL"),
            "high": sum(1 for alert in open_alerts if alert.severity == "HIGH"),
            "acknowledged": sum(1 for alert in open_alerts if alert.status == AlertStatus.ACKNOWLEDGED),
            "oldest_open": min((alert.first_seen for alert in open_alerts), default=None).isoformat()
            if open_alerts
            else None,
        }


def levels_at_least(severity: str, threshold: str) -> bool:
    return SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(threshold, 0)


alert_service = AlertService()
