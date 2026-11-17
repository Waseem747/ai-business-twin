"""Approved action execution with idempotency and an immutable audit trail.

Only the simulated ERP target is wired in this MVP. For any other target the
service fails explicitly; it never pretends an external API succeeded.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.errors import ConflictError, PermissionDenied, ValidationError
from app.core.utils import fingerprint, utcnow
from app.domain.models import (
    Approval,
    Business,
    BusinessAction,
    BusinessEvent,
    Decision,
    MockExternalRecord,
    User,
)

REQUIRED_PARAMS: dict[str, list[str]] = {
    "SUPPLIER_CONTRACT_REVIEW": ["supplier"],
    "PROMOTION_POLICY_UPDATE": ["target_discount_depth_pct"],
    "PRICE_UPDATE": ["price_change_pct"],
    "PROCUREMENT_ALLOCATION_UPDATE": ["supplier"],
    "BUDGET_UPDATE": ["category", "reduction_pct"],
    "INVENTORY_REALLOCATION": ["inventory_reduction_pct"],
}


class ActionService:
    async def execute(
        self,
        session: AsyncSession,
        business: Business,
        decision: Decision,
        *,
        actor: str = "action-execution-agent",
        system_actor: bool = True,
    ) -> BusinessAction:
        if decision.business_id != business.id:
            raise PermissionDenied("Decision belongs to another business")
        if decision.status not in {"APPROVED", "AWAITING_EXECUTION"}:
            raise ConflictError(f"Decision is not approved for execution (status {decision.status})")
        if decision.requires_approval:
            approval = (
                await session.execute(
                    select(Approval)
                    .where(Approval.decision_id == decision.id)
                    .order_by(Approval.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not approval or approval.status != "APPROVED":
                raise PermissionDenied("Human approval is required before any action can be executed")
        if not system_actor and actor.endswith("-agent"):
            raise PermissionDenied("Agent identity cannot self-authorise system actions")

        chosen = decision.chosen or {}
        action_type = chosen.get("action_type") or "UNKNOWN"
        parameters = dict(chosen.get("action_parameters") or {})
        missing = [key for key in REQUIRED_PARAMS.get(action_type, []) if parameters.get(key) is None]
        if missing:
            raise ValidationError(f"Missing required action parameters: {', '.join(missing)}")
        idempotency_key = fingerprint("action", decision.id, action_type)
        existing = (
            await session.execute(
                select(BusinessAction).where(BusinessAction.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        target_system = "simulated_erp"
        action = BusinessAction(
            business_id=business.id,
            decision_id=decision.id,
            action_type=action_type,
            target_system=target_system,
            idempotency_key=idempotency_key,
            status="EXECUTING",
            parameters=parameters,
            expected_outcome=chosen.get("expected_outcome") or {},
            simulated=True,
        )
        session.add(action)
        await session.flush()
        decision.status = "EXECUTING"
        await session.flush()

        try:
            if target_system != "simulated_erp":
                raise ValidationError(f"No live integration configured for target system '{target_system}'")
            # This writes to the local integration simulator only. It is not an
            # external production system and is labelled simulated everywhere.
            record_key = f"{action_type.lower()}-{decision.id}"
            result = (
                await session.execute(
                    select(MockExternalRecord).where(
                        MockExternalRecord.system == target_system,
                        MockExternalRecord.entity == "operations_request",
                        MockExternalRecord.record_key == record_key,
                    )
                )
            ).scalar_one_or_none()
            external_id = f"mock_erp_{action.id[-10:]}"
            data = {
                "external_id": external_id,
                "status": "ACTIVE",
                "action_type": action_type,
                "decision_id": decision.id,
                "parameters": parameters,
                "expected_outcome": chosen.get("expected_outcome") or {},
                "simulated": True,
                "applied_at": utcnow().isoformat(),
                "note": "Local simulated ERP request; no real external API was called.",
            }
            if result:
                result.data = {**result.data, **data}
            else:
                session.add(
                    MockExternalRecord(
                        system=target_system,
                        entity="operations_request",
                        record_key=record_key,
                        data=data,
                    )
                )
            action.status = "EXECUTED"
            action.external_id = external_id
            action.result = {"record_key": record_key, "system": target_system, "response": data}
            action.executed_at = utcnow()
            await session.flush()
            session.add(
                BusinessEvent(
                    business_id=business.id,
                    event_type="ACTION_EXECUTED",
                    title=f"Action executed: {action_type}",
                    detail=f"Simulated ERP request {external_id} created for decision '{decision.title}'. No real external system was called.",
                    severity="INFO",
                    actor=actor,
                    related_type="business_action",
                    related_id=action.id,
                    payload={"simulated": True, "idempotency_key": idempotency_key},
                )
            )
            await write_audit(
                session,
                tenant_id=business.tenant_id,
                business_id=business.id,
                actor=actor,
                actor_type="AGENT",
                action="ACTION_EXECUTED",
                entity_type="business_action",
                entity_id=action.id,
                after={"status": action.status, "parameters": parameters, "external_id": external_id},
                detail="Simulated ERP action executed with idempotency protection.",
            )
            await session.flush()
            return action
        except Exception as exc:  # noqa: BLE001
            action.status = "FAILED"
            action.error = f"{type(exc).__name__}: {exc}"
            action.executed_at = utcnow()
            decision.status = "FAILED"
            await session.flush()
            raise


action_service = ActionService()
