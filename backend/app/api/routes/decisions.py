"""Decision Center and approval endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from app.api.deps import BusinessDep, DBSession
from app.api.schemas import ApprovalDecision
from app.api.serializers import action_out, approval_out, decision_out, dt, simulation_out
from app.core.security import CurrentUser
from app.domain.models import (
    ActionVerification,
    Approval,
    BusinessAction,
    Decision,
    DecisionReview,
    Simulation,
    WorkflowRun,
)
from app.services.approvals import approval_service
from app.workflows.runner import workflow_runner

router = APIRouter(prefix="/api", tags=["Decision Center"])


@router.get("/decisions")
async def list_decisions(
    business: BusinessDep, db: DBSession, user: CurrentUser, status: str | None = None, limit: int = 50
) -> list[dict]:
    query = select(Decision).where(Decision.business_id == business.id)
    if status:
        query = query.where(Decision.status == status)
    decisions = (
        await db.execute(query.order_by(desc(Decision.created_at)).limit(min(limit, 100)))
    ).scalars().all()
    approvals = (
        await db.execute(
            select(Approval).where(Approval.decision_id.in_([decision.id for decision in decisions]))
        )
    ).scalars().all() if decisions else []
    latest_approval: dict[str, Approval] = {}
    for approval in approvals:
        if approval.decision_id not in latest_approval or approval.created_at > latest_approval[approval.decision_id].created_at:
            latest_approval[approval.decision_id] = approval
    return [decision_out(decision, approval=latest_approval.get(decision.id)) for decision in decisions]


@router.get("/decisions/{decision_id}")
async def get_decision(decision_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    decision = await db.get(Decision, decision_id)
    if not decision or decision.business_id != business.id:
        raise HTTPException(status_code=404, detail="Decision not found")
    reviews = (
        await db.execute(
            select(DecisionReview).where(DecisionReview.decision_id == decision.id).order_by(DecisionReview.created_at)
        )
    ).scalars().all()
    approvals = (
        await db.execute(
            select(Approval).where(Approval.decision_id == decision.id).order_by(desc(Approval.created_at))
        )
    ).scalars().all()
    simulation = await db.get(Simulation, decision.simulation_id) if decision.simulation_id else None
    action = (
        await db.execute(
            select(BusinessAction).where(BusinessAction.decision_id == decision.id).order_by(desc(BusinessAction.created_at)).limit(1)
        )
    ).scalar_one_or_none()
    verification = None
    if action:
        verification = (
            await db.execute(
                select(ActionVerification).where(ActionVerification.action_id == action.id).order_by(desc(ActionVerification.created_at)).limit(1)
            )
        ).scalar_one_or_none()
    payload = decision_out(decision, reviews=reviews, approval=approvals[0] if approvals else None)
    payload["approvals"] = [approval_out(item, decision) for item in approvals]
    payload["simulation"] = simulation_out(simulation) if simulation else None
    payload["action"] = (
        action_out(
            action,
            {
                "status": verification.status,
                "expected": verification.expected,
                "actual": verification.actual,
                "differences": verification.differences,
                "business_impact": verification.business_impact,
                "notes": verification.notes,
                "verified_at": dt(verification.created_at),
            }
            if verification
            else None,
        )
        if action
        else None
    )
    return payload


@router.get("/actions")
async def list_actions(business: BusinessDep, db: DBSession, user: CurrentUser, limit: int = 30) -> list[dict]:
    actions = (
        await db.execute(
            select(BusinessAction).where(BusinessAction.business_id == business.id).order_by(desc(BusinessAction.created_at)).limit(min(limit, 100))
        )
    ).scalars().all()
    verifications = (
        await db.execute(
            select(ActionVerification).where(ActionVerification.action_id.in_([action.id for action in actions]))
        )
    ).scalars().all() if actions else []
    latest = {}
    for verification in verifications:
        if verification.action_id not in latest:
            latest[verification.action_id] = verification
    return [
        action_out(
            action,
            {
                "status": latest[action.id].status,
                "business_impact": latest[action.id].business_impact,
                "differences": latest[action.id].differences,
                "notes": latest[action.id].notes,
            }
            if action.id in latest
            else None,
        )
        for action in actions
    ]


@router.get("/approvals")
async def list_approvals(business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    approvals = (
        await db.execute(
            select(Approval).where(Approval.business_id == business.id).order_by(desc(Approval.created_at)).limit(100)
        )
    ).scalars().all()
    decisions = (
        await db.execute(select(Decision).where(Decision.business_id == business.id))
    ).scalars().all()
    by_id = {decision.id: decision for decision in decisions}
    return {
        "pending": [
            approval_out(approval, by_id.get(approval.decision_id))
            for approval in approvals
            if approval.status == "PENDING"
        ],
        "history": [
            approval_out(approval, by_id.get(approval.decision_id))
            for approval in approvals
            if approval.status != "PENDING"
        ],
    }


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str, payload: ApprovalDecision, business: BusinessDep, db: DBSession, user: CurrentUser
) -> dict:
    if user.role not in {"ADMIN", "APPROVER"}:
        raise HTTPException(status_code=403, detail="Only an APPROVER or ADMIN can authorise decisions")
    approval = await approval_service.get(db, approval_id, business.id)
    if approval.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Approval already {approval.status}")
    await approval_service.decide(db, approval, user, approved=payload.approved, comment=payload.comment)
    decision = await db.get(Decision, approval.decision_id)
    run_id = decision.workflow_run_id if decision else None
    run = await db.get(WorkflowRun, run_id) if run_id else None
    await db.commit()

    resumed = False
    resume_error = None
    if run and run.status in {"WAITING_APPROVAL", "WAITING_HUMAN_REVIEW", "RUNNING"}:
        try:
            await workflow_runner.resume(
                run.id,
                {"approved": payload.approved, "actor": user.email, "comment": payload.comment},
            )
            resumed = True
        except Exception as exc:  # noqa: BLE001
            resume_error = f"{type(exc).__name__}: {exc}"
    return {
        "approval": approval_out(approval, decision),
        "workflow": {"id": run.id, "status": run.status, "resumed": resumed} if run else None,
        "resume_error": resume_error,
        "message": (
            "Approval recorded and workflow resumed."
            if resumed
            else "Approval recorded. No waiting workflow was found to resume."
        ),
    }


@router.get("/audit-logs")
async def audit_logs(business: BusinessDep, db: DBSession, user: CurrentUser, limit: int = 100) -> list[dict]:
    if user.role not in {"ADMIN", "ANALYST", "APPROVER"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    from app.domain.models import AuditLog

    rows = (
        await db.execute(
            select(AuditLog)
            .where((AuditLog.business_id == business.id) | (AuditLog.tenant_id == user.tenant_id))
            .order_by(desc(AuditLog.created_at))
            .limit(min(limit, 300))
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "actor": row.actor,
            "actor_type": row.actor_type,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "before": row.before,
            "after": row.after,
            "detail": row.detail,
            "created_at": dt(row.created_at),
        }
        for row in rows
    ]
