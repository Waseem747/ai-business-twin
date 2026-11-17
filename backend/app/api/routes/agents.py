"""Agent activity, workflow execution and orchestration routes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from app.api.deps import BusinessDep, DBSession
from app.api.schemas import WorkflowRunRequest
from app.api.serializers import agent_out, dt, workflow_out
from app.core.audit import write_audit
from app.core.security import CurrentUser, Role as RoleEnum
from app.domain.models import Agent, AgentExecution, Alert, WorkflowRun, WorkflowStep
from app.workflows.runner import workflow_runner

router = APIRouter(prefix="/api", tags=["Agents & Workflows"])

WRITE_ROLES = {"ADMIN", "ANALYST", "APPROVER"}


@router.get("/agents")
async def list_agents(business: BusinessDep, db: DBSession, user: CurrentUser) -> list[dict]:
    agents = (
        await db.execute(select(Agent).where(Agent.business_id == business.id).order_by(Agent.name))
    ).scalars().all()
    return [agent_out(agent) for agent in agents]


@router.get("/agents/executions")
async def agent_executions(
    business: BusinessDep,
    db: DBSession,
    user: CurrentUser,
    agent_key: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
) -> list[dict]:
    query = select(AgentExecution).where(AgentExecution.business_id == business.id)
    if agent_key:
        query = query.where(AgentExecution.agent_key == agent_key)
    rows = (await db.execute(query.order_by(desc(AgentExecution.created_at)).limit(limit))).scalars().all()
    return [
        {
            "id": row.id,
            "agent_key": row.agent_key,
            "workflow_run_id": row.workflow_run_id,
            "status": row.status,
            "summary": row.summary,
            "input_summary": row.input_summary,
            "output_summary": row.output_summary,
            "evidence": row.evidence,
            "duration_ms": row.duration_ms,
            "error": row.error,
            "model_provider": row.model_provider,
            "created_at": dt(row.created_at),
        }
        for row in rows
    ]


@router.get("/workflows")
async def list_workflows(
    business: BusinessDep,
    db: DBSession,
    user: CurrentUser,
    workflow: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict]:
    query = select(WorkflowRun).where(WorkflowRun.business_id == business.id)
    if workflow:
        query = query.where(WorkflowRun.workflow == workflow)
    rows = (await db.execute(query.order_by(desc(WorkflowRun.started_at)).limit(limit))).scalars().all()
    return [workflow_out(row) for row in rows]


@router.get("/workflows/{run_id}")
async def get_workflow(run_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    run = await db.get(WorkflowRun, run_id)
    if not run or run.business_id != business.id:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    steps = (
        await db.execute(
            select(WorkflowStep).where(WorkflowStep.run_id == run.id).order_by(WorkflowStep.created_at)
        )
    ).scalars().all()
    return workflow_out(run, steps, include_state=True)


@router.post("/workflows/{workflow}/run")
async def run_workflow(
    workflow: str, payload: WorkflowRunRequest, business: BusinessDep, db: DBSession, user: CurrentUser
) -> dict:
    if user.role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions to start workflows")
    if workflow not in {"daily_bi", "decision_execution"}:
        raise HTTPException(status_code=400, detail="Use the dedicated simulation or Excel conversion endpoints for this workflow")
    if workflow == "decision_execution" and payload.alert_id:
        alert = await db.get(Alert, payload.alert_id)
        if not alert or alert.business_id != business.id:
            raise HTTPException(status_code=404, detail="Alert not found")
    active = (
        await db.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.business_id == business.id,
                WorkflowRun.workflow == workflow,
                WorkflowRun.status.in_(["RUNNING", "WAITING_APPROVAL", "WAITING_HUMAN_REVIEW"]),
            )
            .order_by(desc(WorkflowRun.started_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"A {workflow.replace('_', ' ')} workflow is already active ({active.status}). Complete or resume it before starting another.",
        )
    inputs = {}
    if workflow == "decision_execution":
        inputs = {"alert_id": payload.alert_id, "issue": payload.issue}
    run = await workflow_runner.start(
        db,
        business=business,
        workflow=workflow,
        inputs=inputs,
        actor=user.email,
        trigger="MANUAL",
    )
    await write_audit(
        db,
        tenant_id=business.tenant_id,
        business_id=business.id,
        actor=user.email,
        action="WORKFLOW_STARTED",
        entity_type="workflow_run",
        entity_id=run.id,
        after={"workflow": workflow, "inputs": inputs},
    )
    await db.commit()
    return workflow_out(run)


@router.get("/role-policy")
async def role_policy(user: CurrentUser) -> dict:
    return {
        "roles": sorted(RoleEnum.ALL),
        "your_role": user.role,
        "permissions": {
            "view": sorted(RoleEnum.ALL),
            "run_workflows": sorted(WRITE_ROLES),
            "approve": ["ADMIN", "APPROVER"],
            "edit_logic": ["ADMIN", "ANALYST"],
            "activate_logic": ["ADMIN", "APPROVER"],
        },
    }
