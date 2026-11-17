"""Independent verification that an action produced the expected operational state."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Business, BusinessAction, BusinessEvent, Decision, MockExternalRecord
from app.domain.models import ActionVerification
from app.core.utils import utcnow


class VerificationService:
    async def verify(
        self, session: AsyncSession, business: Business, action: BusinessAction, decision: Decision
    ) -> dict[str, Any]:
        expected = {
            "action_type": action.action_type,
            "decision_id": decision.id,
            **{key: value for key, value in (action.parameters or {}).items()},
        }
        record_key = (action.result or {}).get("record_key")
        record = None
        if record_key:
            record = (
                await session.execute(
                    select(MockExternalRecord).where(
                        MockExternalRecord.system == action.target_system,
                        MockExternalRecord.entity == "operations_request",
                        MockExternalRecord.record_key == record_key,
                    )
                )
            ).scalar_one_or_none()
        differences: list[dict[str, Any]] = []
        actual: dict[str, Any] = {}
        if not record:
            status = "FAILED"
            notes = "The simulated external record could not be retrieved; execution is unverified."
        else:
            data = record.data or {}
            actual = {
                "external_id": data.get("external_id"),
                "status": data.get("status"),
                "action_type": data.get("action_type"),
                "parameters": data.get("parameters"),
                "simulated": data.get("simulated"),
            }
            for key in ("action_type", "status"):
                if actual.get(key) != expected.get(key) and not (key == "status" and actual.get("status") == "ACTIVE"):
                    differences.append({"field": key, "expected": expected.get(key), "actual": actual.get(key)})
            expected_params = action.parameters or {}
            actual_params = data.get("parameters") or {}
            for key, value in expected_params.items():
                if actual_params.get(key) != value:
                    differences.append({"field": f"parameters.{key}", "expected": value, "actual": actual_params.get(key)})
            if actual.get("simulated") is not True:
                differences.append({"field": "simulated", "expected": True, "actual": actual.get("simulated")})
            if actual.get("external_id") != action.external_id:
                differences.append({"field": "external_id", "expected": action.external_id, "actual": actual.get("external_id")})
            status = "VERIFIED" if not differences else "PARTIALLY_VERIFIED"
            notes = (
                "Operational state matches the approved request. Business impact remains pending measured post-action performance."
                if not differences
                else f"{len(differences)} difference(s) found between expected and actual operational state."
            )

        business_impact = {
            "status": "PENDING_OBSERVATION",
            "projected": (decision.chosen or {}).get("expected_outcome") or {},
            "measured": None,
            "note": (
                "The action was executed against the local simulated ERP. The 12-month financial projection cannot be "
                "treated as a measured result. A follow-up observation window is required before business impact is claimed."
            ),
        }
        verification = ActionVerification(
            action_id=action.id,
            status=status,
            expected=expected,
            actual=actual,
            differences=differences,
            business_impact=business_impact,
            notes=notes,
        )
        session.add(verification)
        action.verified_at = utcnow()
        action.status = status
        decision.status = "VERIFIED" if status == "VERIFIED" else "FAILED"
        session.add(
            BusinessEvent(
                business_id=business.id,
                event_type="ACTION_VERIFIED",
                title=f"Execution verified: {action.action_type}",
                detail=notes,
                severity="INFO" if status == "VERIFIED" else "HIGH",
                actor="execution-verification-agent",
                related_type="business_action",
                related_id=action.id,
                payload={"differences": differences, "business_impact": business_impact},
            )
        )
        await session.flush()
        return {
            "verification_id": verification.id,
            "status": status,
            "differences": differences,
            "actual": actual,
            "business_impact": business_impact,
            "notes": notes,
        }


verification_service = VerificationService()
