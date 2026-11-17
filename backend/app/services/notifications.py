"""Notification service. In-app notifications are always persisted.

Email is only marked SENT after SMTP accepts it. If SMTP is not configured,
the notification remains IN_APP and no delivery is claimed.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.utils import utcnow
from app.domain.models import Notification


class NotificationService:
    async def send(
        self,
        session: AsyncSession,
        *,
        business_id: str,
        subject: str,
        body: str,
        channel: str = "IN_APP",
        recipient: str = "",
        related_type: str = "",
        related_id: str = "",
    ) -> Notification:
        notification = Notification(
            business_id=business_id,
            channel=channel,
            recipient=recipient or settings.notification_email_to or "Management dashboard",
            subject=subject,
            body=body,
            status="RECORDED",
            related_type=related_type,
            related_id=related_id,
        )
        session.add(notification)
        await session.flush()
        if channel == "EMAIL":
            if not settings.smtp_host or not settings.notification_email_to:
                notification.status = "NOT_CONFIGURED"
                notification.error = "SMTP is not configured; notification retained in dashboard."
            else:
                try:
                    await asyncio.to_thread(self._send_email_sync, subject, body)
                    notification.status = "SENT"
                    notification.sent_at = utcnow()
                except Exception as exc:  # noqa: BLE001
                    notification.status = "FAILED"
                    notification.error = f"{type(exc).__name__}: {exc}"
            await session.flush()
        return notification

    def _send_email_sync(self, subject: str, body: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_user or "business-twin@localhost"
        message["To"] = settings.notification_email_to
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)

    async def recent(self, session: AsyncSession, business_id: str, limit: int = 30) -> list[Notification]:
        from sqlalchemy import desc, select

        result = await session.execute(
            select(Notification)
            .where(Notification.business_id == business_id)
            .order_by(desc(Notification.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())


notification_service = NotificationService()
