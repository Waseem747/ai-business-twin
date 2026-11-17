"""Human approval workflow records and policy checks."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.errors import ConflictError, NotFoundError
from app.core.utils import utcnow
from app.domain.models import Approval, Business, BusinessEvent, Decision, User


class ApprovalService:
    async def request(
        self,
        session: AsyncSession,
        business: Business,
        decision: Decision,
        *,
        policy_type: str = "DECISION_APPROVAL",
        conditions: list[str] | None = None,
        requested_by: str = "decision-workflow",
    ) -> Approval:
        existing = (
            await session.execute(
                select(Approval)
                .where(Approval.decision_id == decision.id)
                .order_by(desc(Approval.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        approval = Approval(
            decision_id=decision.id,
            business_id=business.id,
            status="PENDING",
            policy={
                "type": policy_type,
                "expected_financial_impact": decision.expected_financial_impact,
                "risk_level": decision.risk_level,
                "reversibility": decision.reversibility,
                "conditions": conditions or [],
                "threshold_usd": 5000,
                "requested_by": requested_by,
            },
            expires_at=utcnow() + timedelta(hours=48),
        )
        session.add(approval)
        decision.status = "AWAITING_APPROVAL"
        await session.flush()
        session.add(
            BusinessEvent(
                business_id=business.id,
                event_type="APPROVAL_REQUESTED",
                title=f"Approval requested: {decision.title}",
                detail="Human authorisation is required before execution.",
                severity="HIGH",
                actor=requested_by,
                related_type="approval",
                related_id=approval.id,
            )
        )
        await session.flush()
        return approval

    async def decide(
        self,
        session: AsyncSession,
        approval: Approval,
        user: User,
        *,
        approved: bool,
        comment: str = "",
    ) -> Approval:
        if approval.status != "PENDING":
            raise ConflictError(f"Approval is already {approval.status}")
        if approval.expires_at and approval.expires_at < utcnow():
            approval.status = "EXPIRED"
            await session.flush()
            raise ConflictError("Approval request has expired")
        approval.status = "APPROVED" if approved else "REJECTED"
        approval.decided_at = utcnow()
        approval.decided_by = f"{user.full_name} <{user.email}>"
        approval.comment = comment
        decision = await session.get(Decision, approval.decision_id)
        if decision:
            decision.status = "APPROVED" if approved else "REJECTED"
        await session.flush()
        session.add(
            BusinessEvent(
                business_id=approval.business_id,
                event_type="APPROVAL_DECIDED",
                title=f"Decision {'approved' if approved else 'rejected'} by {user.full_name}",
                detail=comment,
                severity="INFO" if approved else "MEDIUM",
                actor=user.email,
                related_type="approval",
                related_id=approval.id,
            )
        )
        await write_audit(
            session,
            tenant_id=user.tenant_id,
            business_id=approval.business_id,
            actor=user.email,
            action="APPROVAL_DECIDED",
            entity_type="approval",
            entity_id=approval.id,
            before={"status": "PENDING"},
            after={"status": approval.status, "comment": comment},
        )
        await session.flush()
        return approval

    async def get(self, session: AsyncSession, approval_id: str, business_id: str) -> Approval:
        approval = await session.get(Approval, approval_id)
        if not approval or approval.business_id != business_id:
            raise NotFoundError("Approval not found")
        return approval

    async def pending(self, session: AsyncSession, business_id: str) -> list[Approval]:
        result = await session.execute(
            select(Approval)
            .where(Approval.business_id == business_id, Approval.status == "PENDING")
            .order_by(desc(Approval.created_at))
        )
        return list(result.scalars().all())


approval_service = ApprovalService()
