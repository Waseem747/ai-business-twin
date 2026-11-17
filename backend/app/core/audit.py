"""Immutable audit logging helper. Rows are insert-only by design."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import AuditLog


async def write_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_type: str = "USER",
    business_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    detail: str = "",
    ip: str = "",
    request_id: str = "",
) -> AuditLog:
    entry = AuditLog(
        tenant_id=tenant_id,
        business_id=business_id,
        actor=actor,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        detail=detail,
        ip=ip,
        request_id=request_id,
    )
    session.add(entry)
    return entry
