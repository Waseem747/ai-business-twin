"""LangGraph workflow definitions A-D.

Workflow A: Daily Business Intelligence
Workflow B: Decision and Execution (with audit loop + human approval interrupt)
Workflow C: Business Simulation
Workflow D: Excel Logic Conversion (with human approval interrupt)
"""
from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt
from sqlalchemy import select

from app.agents.workers import (
    action_agent,
    auditor_agent,
    bi_agent,
    business_logic_agent,
    data_acquisition_agent,
    decision_agent,
    reporting_agent,
    simulation_agent,
    transformation_agent,
    verification_agent,
)
from app.config import settings
from app.core.errors import ConflictError, TwinError
from app.core.utils import utcnow
from app.db import session_scope
from app.domain.models import (
    Alert,
    Approval,
    Business,
    BusinessEvent,
    Decision,
    IngestionRun,
    MetricSnapshot,
    Report,
    Simulation,
    WorkflowStep,
    ExcelConversion,
)
from app.excel.service import excel_service
from app.services.alerts import alert_service
from app.services.anomalies import detect_anomalies
from app.services.approvals import approval_service
from app.services.notifications import notification_service
from app.services.twin_state import ensure_snapshot
from app.workflows.state import WorkflowState

TERMINAL_REJECTED = "REJECTED"


async def _log_step(
    session: Any,
    state: WorkflowState,
    node: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    status: str = "SUCCEEDED",
    started: float | None = None,
) -> None:
    session.add(
        WorkflowStep(
            run_id=state["run_id"],
            node=node,
            status=status,
            summary=summary[:1000],
            payload=payload or {},
            started_at=utcnow() if started is None else None,
            finished_at=utcnow(),
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# Workflow A: Daily Business Intelligence
# ---------------------------------------------------------------------------
async def a_acquire(state: WorkflowState) -> dict[str, Any]:
    start = time.perf_counter()
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        result = await data_acquisition_agent.run(
            session, business, trigger=state.get("trigger", "SCHEDULE"), workflow_run_id=state["run_id"]
        )
        await _log_step(session, state, "acquisition", f"Synchronised {result['sources']} source(s).", result)
        return {
            "ingestion_run_ids": [run["id"] for run in result["runs"]],
            "ingestion_summary": result,
            "completed_nodes": ["acquisition"],
        }


async def a_validate(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        runs = (
            await session.execute(select(IngestionRun).where(IngestionRun.id.in_(state.get("ingestion_run_ids", []))))
        ).scalars().all()
        succeeded = [run for run in runs if run.status == "SUCCEEDED"]
        rejected = sum(run.records_rejected for run in runs)
        ingested = sum(run.records_ingested for run in runs)
        missing = [
            run.data_source_id for run in runs if run.status != "SUCCEEDED"
        ]
        if not succeeded:
            raise TwinError("No data ingestion succeeded; business state cannot be validated")
        summary = {
            "sources_succeeded": len(succeeded),
            "sources_failed": len(missing),
            "records_ingested": ingested,
            "records_rejected": rejected,
            "freshness_at": max((run.freshness_at for run in runs if run.freshness_at), default=None).isoformat()
            if any(run.freshness_at for run in runs)
            else None,
            "validation_rules": ["finite_values", "non_negative_amounts", "deduplication", "future_period_block"],
        }
        await _log_step(
            session,
            state,
            "validation",
            f"{ingested} facts validated; {rejected} rejected; {len(missing)} source(s) failed.",
            summary,
            status="SUCCEEDED" if not missing else "PARTIAL",
        )
        return {"validation_summary": summary, "completed_nodes": ["validation"]}


async def a_transform(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        result = await transformation_agent.run(
            session, business, state.get("ingestion_run_ids"), workflow_run_id=state["run_id"]
        )
        await _log_step(session, state, "transformation", f"Applied {result['transformations']} transformation(s).", result)
        return {"transformation_summary": result, "completed_nodes": ["transformation"]}


async def a_logic(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        result = await business_logic_agent.run(session, business, workflow_run_id=state["run_id"])
        await _log_step(session, state, "business_logic", "Executed approved rules and built the digital twin snapshot.", result)
        return {"snapshot_id": result["snapshot_id"], "logic_summary": result, "completed_nodes": ["business_logic"]}


async def a_intelligence(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        snapshot = await session.get(MetricSnapshot, state["snapshot_id"])
        result = await bi_agent.run(session, business, snapshot, workflow_run_id=state["run_id"])
        payload = dict(snapshot.payload)
        payload["intelligence"] = {
            "findings": result["findings"],
            "counts": result["counts"],
            "narrative": result["narrative"],
            "generated_at": utcnow().isoformat(),
        }
        snapshot.payload = payload
        await session.flush()
        await _log_step(
            session,
            state,
            "intelligence",
            f"Business intelligence produced {len(result['findings'])} findings.",
            {"counts": result["counts"], "issue": (result.get("issue") or {}).get("title")},
        )
        return {
            "findings": result["findings"],
            "intelligence_summary": {"counts": result["counts"], "narrative": result["narrative"]},
            "issue": result.get("issue") or {},
            "completed_nodes": ["intelligence"],
        }


async def a_monitor(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        alert_ids: list[str] = []
        created = 0
        escalated = 0
        for finding in state.get("findings", []):
            if finding["severity"] not in {"HIGH", "CRITICAL"}:
                continue
            alert, was_created, was_escalated = await alert_service.upsert(
                session,
                business_id=business.id,
                dedup_key=f"finding:{finding['id']}",
                title=finding["title"],
                detail=finding["detail"],
                severity=finding["severity"],
                area=finding["area"],
                evidence=finding["evidence"],
                actor="monitoring-service",
            )
            alert_ids.append(alert.id)
            created += int(was_created)
            escalated += int(was_escalated)
        summary = {
            "evaluated_findings": len(state.get("findings", [])),
            "alerts_created": created,
            "alerts_deduplicated": len(alert_ids) - created,
            "alerts_escalated": escalated,
            "alert_ids": alert_ids,
        }
        await _log_step(
            session,
            state,
            "anomaly_alerting",
            f"Created {created} alert(s); deduplicated {summary['alerts_deduplicated']} existing incident(s).",
            summary,
            status="SUCCEEDED",
        )
        return {
            "alert_ids": alert_ids,
            "alert_id": alert_ids[0] if alert_ids else "",
            "completed_nodes": ["anomaly_alerting"],
        }


async def a_report(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        snapshot = await session.get(MetricSnapshot, state["snapshot_id"])
        reports = await reporting_agent.daily(session, business, snapshot, workflow_run_id=state["run_id"])
        daily = reports["daily"]
        exception = reports["exception"]
        await _log_step(
            session,
            state,
            "reporting",
            "Generated daily executive summary and exception report.",
            {"daily_report_id": daily.id, "exception_report_id": exception.id, "files": daily.files},
        )
        await notification_service.send(
            session,
            business_id=business.id,
            subject=f"Daily executive summary ready - {snapshot.payload.get('latest', {}).get('label')}",
            body=daily.content.get("executive_summary", ""),
            channel="IN_APP",
            related_type="report",
            related_id=daily.id,
        )
        return {
            "report_ids": [daily.id, exception.id],
            "completed_nodes": ["reporting"],
        }


async def a_finish(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        snapshot = await session.get(MetricSnapshot, state["snapshot_id"]) if state.get("snapshot_id") else None
        summary = (
            f"Daily business intelligence completed for {snapshot.payload.get('latest', {}).get('label') if snapshot else 'n/a'}. "
            f"{len(state.get('alert_ids', []))} open alert(s) tracked. Report: {', '.join(state.get('report_ids', []))}."
        )
        session.add(
            BusinessEvent(
                business_id=business.id,
                event_type="WORKFLOW_COMPLETED",
                title="Daily business intelligence cycle completed",
                detail=summary,
                severity="INFO",
                actor=state.get("actor", "system"),
                related_type="workflow",
                related_id=state["run_id"],
            )
        )
        await _log_step(session, state, "notification", "Management notification recorded.", {"summary": summary})
        return {"status": "COMPLETED", "summary": summary, "completed_nodes": ["notification"]}


def build_daily_graph() -> StateGraph:
    graph = StateGraph(WorkflowState)
    retry = RetryPolicy(max_attempts=3, initial_interval=0.5, backoff_factor=2.0)
    graph.add_node("acquisition", a_acquire, retry_policy=retry)
    graph.add_node("validation", a_validate)
    graph.add_node("transformation", a_transform, retry_policy=retry)
    graph.add_node("business_logic", a_logic)
    graph.add_node("intelligence", a_intelligence)
    graph.add_node("anomaly_alerting", a_monitor)
    graph.add_node("reporting", a_report)
    graph.add_node("notification", a_finish)
    graph.add_edge(START, "acquisition")
    graph.add_edge("acquisition", "validation")
    graph.add_edge("validation", "transformation")
    graph.add_edge("transformation", "business_logic")
    graph.add_edge("business_logic", "intelligence")
    graph.add_edge("intelligence", "anomaly_alerting")
    graph.add_edge("anomaly_alerting", "reporting")
    graph.add_edge("reporting", "notification")
    graph.add_edge("notification", END)
    return graph


# ---------------------------------------------------------------------------
# Workflow B: Decision and Execution
# ---------------------------------------------------------------------------
async def b_intake(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        snapshot = await ensure_snapshot(session, business, max_age_minutes=120)
        issue = state.get("issue") or {}
        alert = None
        if state.get("alert_id"):
            alert = await session.get(Alert, state["alert_id"])
        if not issue:
            analysis = detect_anomalies(snapshot.payload)
            issue = analysis.get("issue") or {}
            if alert and issue:
                issue = {
                    **issue,
                    "alert_id": alert.id,
                    "title": alert.title or issue.get("title"),
                    "severity": alert.severity,
                    "summary": alert.detail or issue.get("summary"),
                }
        if not issue:
            await _log_step(session, state, "intake", "No actionable issue found; workflow stopped.", {})
            return {
                "snapshot_id": snapshot.id,
                "issue": {},
                "status": "COMPLETED",
                "summary": "No actionable business issue was identified.",
                "completed_nodes": ["intake"],
            }
        alert_id = state.get("alert_id") or issue.get("alert_id") or ""
        await _log_step(session, state, "intake", f"Loaded issue: {issue.get('title', '')}.", {"issue": issue})
        return {
            "snapshot_id": snapshot.id,
            "issue": issue,
            "alert_id": alert_id,
            "revision_count": state.get("revision_count", 0),
            "completed_nodes": ["intake"],
        }


def route_intake(state: WorkflowState) -> str:
    return "no_action" if not state.get("issue") else "decide"


async def b_decide(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        snapshot = await session.get(MetricSnapshot, state["snapshot_id"])
        decision = await decision_agent.run(
            session, business, snapshot, state["issue"], workflow_run_id=state["run_id"]
        )
        if state.get("alert_id"):
            decision.alert_id = state["alert_id"]
        await session.flush()
        await _log_step(
            session,
            state,
            "decision",
            f"Generated recommendation '{decision.title}'.",
            {"decision_id": decision.id, "alternatives": len(decision.alternatives)},
        )
        return {"decision_id": decision.id, "completed_nodes": ["decision"]}


async def b_audit(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        snapshot = await session.get(MetricSnapshot, state["snapshot_id"])
        decision = await session.get(Decision, state["decision_id"])
        result = await auditor_agent.run(
            session, business, decision, snapshot, workflow_run_id=state["run_id"]
        )
        await _log_step(
            session,
            state,
            "audit",
            f"Auditor verdict: {result['verdict']}.",
            {"verdict": result["verdict"], "round": result["round"], "conditions": result["conditions"]},
            status="SUCCEEDED" if result["verdict"] != "REJECTED" else "REJECTED",
        )
        return {
            "audit": result,
            "audit_verdict": result["verdict"],
            "completed_nodes": ["audit"],
        }


def route_after_audit(state: WorkflowState) -> str:
    verdict = state.get("audit_verdict", "REJECTED")
    if verdict == "REJECTED":
        if state.get("revision_count", 0) + 1 >= settings.max_audit_rounds:
            return "human_review"
        return "revise"
    if verdict == "REQUIRES_HUMAN_REVIEW":
        return "human_review"
    decision_id = state.get("decision_id")
    # requires_approval is carried in the audit payload to keep routing pure.
    audit = state.get("audit") or {}
    if audit.get("requires_approval", True):
        return "request_approval"
    return "auto_authorize"


async def b_revise(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        revised = await decision_agent.revise(
            session, business, decision, state.get("audit") or {}, workflow_run_id=state["run_id"]
        )
        await _log_step(
            session,
            state,
            "decision_revision",
            f"Decision revised to '{revised.title}'.",
            {"decision_id": revised.id, "round": revised.audit_rounds},
        )
        return {
            "revision_count": state.get("revision_count", 0) + 1,
            "decision_id": revised.id,
            "completed_nodes": ["decision_revision"],
        }


async def b_request_approval(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        audit = state.get("audit") or {}
        approval = await approval_service.request(
            session,
            business,
            decision,
            policy_type="DECISION_APPROVAL",
            conditions=audit.get("conditions", []),
            requested_by="decision-audit-workflow",
        )
        payload = {
            "type": "decision_approval",
            "approval_id": approval.id,
            "decision_id": decision.id,
            "business_id": business.id,
            "title": decision.title,
            "issue": state.get("issue", {}).get("title"),
            "expected_financial_impact": decision.expected_financial_impact,
            "risk_level": decision.risk_level,
            "confidence": decision.confidence,
            "audit_verdict": audit.get("verdict"),
            "conditions": audit.get("conditions", []),
            "reasons": [reason for reason in audit.get("reasons", []) if reason.get("severity") in {"HIGH", "CRITICAL"}],
            "policy": approval.policy,
        }
        await _log_step(
            session,
            state,
            "approval_request",
            "Workflow interrupted pending human authorisation.",
            {"approval_id": approval.id, "policy": approval.policy},
            status="WAITING_APPROVAL",
        )
    resumed = interrupt(payload)
    async with session_scope() as session:
        approval = await session.get(Approval, payload["approval_id"])
        decision = await session.get(Decision, payload["decision_id"])
        approved = (
            approval.status == "APPROVED"
            if approval and approval.status != "PENDING"
            else bool((resumed or {}).get("approved"))
        )
        if approval and approval.status == "PENDING":
            approval.status = "APPROVED" if approved else "REJECTED"
            approval.decided_at = utcnow()
            approval.decided_by = (resumed or {}).get("actor", "human-reviewer")
            approval.comment = (resumed or {}).get("comment", "")
        decision.status = "APPROVED" if approved else "REJECTED"
        await session.flush()
        await _log_step(
            session,
            state,
            "approval_resume",
            f"Human approval {'granted' if approved else 'rejected'}.",
            {"approved": approved, "actor": (resumed or {}).get("actor"), "comment": (resumed or {}).get("comment", "")},
            status="SUCCEEDED" if approved else "REJECTED",
        )
        return {
            "approval_result": {
                "approved": approved,
                "approval_id": payload["approval_id"],
                "actor": (resumed or {}).get("actor", approval.decided_by if approval else ""),
                "comment": (resumed or {}).get("comment", approval.comment if approval else ""),
            },
            "completed_nodes": ["approval"],
        }


async def b_human_review(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        audit = state.get("audit") or {}
        approval = await approval_service.request(
            session,
            business,
            decision,
            policy_type="AUDIT_ESCALATION",
            conditions=audit.get("conditions", []) + ["Audit could not reach an automated clearance; human judgement required."],
            requested_by="independent-audit-escalation",
        )
        payload = {
            "type": "audit_escalation",
            "approval_id": approval.id,
            "decision_id": decision.id,
            "business_id": business.id,
            "title": decision.title,
            "audit_verdict": audit.get("verdict"),
            "reasons": audit.get("reasons", []),
            "conditions": audit.get("conditions", []),
            "expected_financial_impact": decision.expected_financial_impact,
            "risk_level": decision.risk_level,
            "policy": approval.policy,
            "note": "The auditor did not clear this decision automatically. A human must accept or reject the residual risk.",
        }
        await _log_step(
            session,
            state,
            "audit_escalation",
            "Audit escalated to human review.",
            {"approval_id": approval.id, "verdict": audit.get("verdict")},
            status="WAITING_HUMAN_REVIEW",
        )
    resumed = interrupt(payload)
    async with session_scope() as session:
        approval = await session.get(Approval, payload["approval_id"])
        decision = await session.get(Decision, payload["decision_id"])
        approved = (
            approval.status == "APPROVED"
            if approval and approval.status != "PENDING"
            else bool((resumed or {}).get("approved"))
        )
        if approval and approval.status == "PENDING":
            approval.status = "APPROVED" if approved else "REJECTED"
            approval.decided_at = utcnow()
            approval.decided_by = (resumed or {}).get("actor", "human-reviewer")
            approval.comment = (resumed or {}).get("comment", "")
        decision.status = "APPROVED" if approved else "REJECTED"
        await session.flush()
        await _log_step(
            session,
            state,
            "human_review_resume",
            f"Human review {'accepted' if approved else 'rejected'}.",
            {"approved": approved, "actor": (resumed or {}).get("actor")},
            status="SUCCEEDED" if approved else "REJECTED",
        )
        return {
            "approval_result": {
                "approved": approved,
                "approval_id": payload["approval_id"],
                "actor": (resumed or {}).get("actor"),
                "comment": (resumed or {}).get("comment", ""),
                "escalated": True,
            },
            "completed_nodes": ["audit_escalation"],
        }


async def b_auto_authorize(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        decision = await session.get(Decision, state["decision_id"])
        decision.status = "APPROVED"
        await session.flush()
        await _log_step(
            session,
            state,
            "auto_authorize",
            "Decision met the automatic execution policy; no human approval required.",
            {"decision_id": decision.id},
        )
        return {"completed_nodes": ["auto_authorize"]}


def route_after_approval(state: WorkflowState) -> str:
    return "action" if (state.get("approval_result") or {}).get("approved") else "rejected"


async def b_action(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        try:
            action = await action_agent.run(session, business, decision, workflow_run_id=state["run_id"])
        except Exception as exc:
            await _log_step(session, state, "action_execution", f"Action failed: {exc}", {"error": str(exc)}, status="FAILED")
            raise
        await _log_step(
            session,
            state,
            "action_execution",
            f"Executed {action.action_type} against {action.target_system}.",
            {"action_id": action.id, "status": action.status, "simulated": action.simulated},
        )
        return {
            "action_id": action.id,
            "action_summary": {"action_id": action.id, "type": action.action_type, "status": action.status, "simulated": action.simulated},
            "completed_nodes": ["action_execution"],
        }


async def b_verify(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        from app.domain.models import BusinessAction

        action = await session.get(BusinessAction, state["action_id"])
        result = await verification_agent.run(
            session, business, action, decision, workflow_run_id=state["run_id"]
        )
        await _log_step(
            session,
            state,
            "execution_verification",
            f"Verification result: {result['status']}.",
            result,
            status="SUCCEEDED" if result["status"] == "VERIFIED" else "PARTIAL",
        )
        return {
            "verification": result,
            "business_impact": result["business_impact"],
            "completed_nodes": ["execution_verification"],
        }


async def b_update_state(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        action = state.get("action_summary", {})
        summary = (
            f"Operational request {action.get('type')} executed and verified. "
            "Production observations were not modified by the simulated integration. "
            "The projected financial impact remains SIMULATED until a measured follow-up window exists."
        )
        session.add(
            BusinessEvent(
                business_id=business.id,
                event_type="BUSINESS_STATE_UPDATE",
                title="Operational state update recorded",
                detail=summary,
                severity="INFO",
                actor="execution-verification-agent",
                related_type="decision",
                related_id=decision.id,
                payload={"projected": (decision.chosen or {}).get("expected_outcome"), "measured": None, "simulated": True},
            )
        )
        await _log_step(session, state, "state_update", summary, {"decision_id": decision.id})
        return {"summary": summary, "completed_nodes": ["state_update"]}


async def b_report(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        snapshot = await session.get(MetricSnapshot, state["snapshot_id"])
        report = await reporting_agent.decision(session, business, decision, workflow_run_id=state["run_id"])
        daily_reports = await reporting_agent.daily(session, business, snapshot, workflow_run_id=state["run_id"])
        await _log_step(
            session,
            state,
            "decision_report",
            "Generated decision report and refreshed the daily executive report.",
            {"report_id": report.id, "daily_report_id": daily_reports["daily"].id, "files": report.files},
        )
        return {
            "report_ids": [
                *(state.get("report_ids") or []),
                report.id,
                daily_reports["daily"].id,
                daily_reports["exception"].id,
            ],
            "completed_nodes": ["decision_report"],
        }


async def b_finish(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        verification = state.get("verification") or {}
        summary = (
            f"Decision '{decision.title}' executed and verified ({verification.get('status', 'n/a')}). "
            "Projected impact is simulated; actual impact awaits measurement."
        )
        await notification_service.send(
            session,
            business_id=business.id,
            subject=f"Decision executed: {decision.title}",
            body=summary,
            channel="IN_APP",
            related_type="decision",
            related_id=decision.id,
        )
        await _log_step(session, state, "completion", summary, {"decision_id": decision.id, "verification": verification})
        return {"status": "COMPLETED", "summary": summary, "completed_nodes": ["completion"]}


async def b_rejected(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        decision = await session.get(Decision, state["decision_id"])
        reason = (state.get("approval_result") or {}).get("comment") or (
            "Auditor rejected the recommendation" if state.get("audit_verdict") == "REJECTED" else "Human reviewer rejected the decision"
        )
        decision.status = "REJECTED"
        await session.flush()
        summary = f"Decision '{decision.title}' was not executed. {reason}"
        await notification_service.send(
            session,
            business_id=business.id,
            subject=f"Decision rejected: {decision.title}",
            body=summary,
            channel="IN_APP",
            related_type="decision",
            related_id=decision.id,
        )
        await _log_step(session, state, "rejected", summary, {"decision_id": decision.id}, status="REJECTED")
        return {"status": "COMPLETED", "summary": summary, "completed_nodes": ["rejected"]}


async def b_no_action(state: WorkflowState) -> dict[str, Any]:
    return {"status": "COMPLETED", "summary": "No actionable issue identified.", "completed_nodes": ["no_action"]}


def build_decision_graph() -> StateGraph:
    graph = StateGraph(WorkflowState)
    graph.add_node("intake", b_intake)
    graph.add_node("decision", b_decide)
    graph.add_node("audit", b_audit)
    graph.add_node("decision_revision", b_revise)
    graph.add_node("request_approval", b_request_approval)
    graph.add_node("human_review", b_human_review)
    graph.add_node("auto_authorize", b_auto_authorize)
    graph.add_node("action_execution", b_action)
    graph.add_node("execution_verification", b_verify)
    graph.add_node("state_update", b_update_state)
    graph.add_node("decision_report", b_report)
    graph.add_node("completion", b_finish)
    graph.add_node("rejected", b_rejected)
    graph.add_node("no_action", b_no_action)

    graph.add_edge(START, "intake")
    graph.add_conditional_edges(
        "intake", route_intake, {"decide": "decision", "no_action": "no_action"}
    )
    graph.add_edge("decision", "audit")
    graph.add_conditional_edges(
        "audit",
        route_after_audit,
        {
            "revise": "decision_revision",
            "request_approval": "request_approval",
            "human_review": "human_review",
            "auto_authorize": "auto_authorize",
        },
    )
    graph.add_edge("decision_revision", "audit")
    graph.add_conditional_edges(
        "request_approval", route_after_approval, {"action": "action_execution", "rejected": "rejected"}
    )
    graph.add_conditional_edges(
        "human_review", route_after_approval, {"action": "action_execution", "rejected": "rejected"}
    )
    graph.add_edge("auto_authorize", "action_execution")
    graph.add_edge("action_execution", "execution_verification")
    graph.add_edge("execution_verification", "state_update")
    graph.add_edge("state_update", "decision_report")
    graph.add_edge("decision_report", "completion")
    graph.add_edge("completion", END)
    graph.add_edge("rejected", END)
    graph.add_edge("no_action", END)
    return graph


# ---------------------------------------------------------------------------
# Workflow C: Business Simulation
# ---------------------------------------------------------------------------
def _validate_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "price_change_pct": (-20, 20),
        "marketing_change_pct": (-80, 150),
        "cogs_change_pct": (-20, 20),
        "discount_change_pp": (-15, 15),
        "headcount_change": (-50, 50),
        "inventory_change_pct": (-50, 50),
        "revenue_impact_pct": (-30, 50),
        "other_opex_change_pct": (-30, 30),
        "one_off_cost": (0, 5_000_000),
    }
    clean: dict[str, Any] = {}
    for key, value in (parameters or {}).items():
        if key not in allowed:
            raise TwinError(f"Unknown scenario parameter '{key}'")
        low, high = allowed[key]
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TwinError(f"Scenario parameter '{key}' must be numeric") from exc
        if not low <= number <= high:
            raise TwinError(f"Scenario parameter '{key}' is outside the tested range {low}..{high}")
        clean[key] = int(number) if key == "headcount_change" else number
    if not clean:
        raise TwinError("At least one scenario parameter is required")
    return clean


async def c_baseline(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        snapshot_id = state.get("snapshot_id")
        snapshot = await session.get(MetricSnapshot, snapshot_id) if snapshot_id else await ensure_snapshot(session, business)
        parameters = _validate_parameters(state.get("scenario_parameters") or {})
        await _log_step(
            session,
            state,
            "baseline",
            "Loaded isolated business snapshot for simulation.",
            {"snapshot_id": snapshot.id, "parameters": parameters},
        )
        return {
            "snapshot_id": snapshot.id,
            "scenario_parameters": parameters,
            "completed_nodes": ["baseline"],
        }


async def c_simulate(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        snapshot = await session.get(MetricSnapshot, state["snapshot_id"])
        simulation = await simulation_agent.run(
            session,
            business,
            snapshot,
            state["scenario_parameters"],
            name=state.get("scenario_name") or "Interactive scenario",
            description=state.get("scenario_description", ""),
            created_by=state.get("actor", "simulation-agent"),
            with_monte_carlo=state.get("with_monte_carlo", True),
            workflow_run_id=state["run_id"],
        )
        await _log_step(
            session,
            state,
            "simulate",
            "Deterministic projection, sensitivity and Monte Carlo completed.",
            {"simulation_id": simulation.id, "results": simulation.results.get("scenario", {}).get("summary")},
        )
        return {
            "simulation_id": simulation.id,
            "simulation_summary": (simulation.results or {}).get("scenario", {}).get("summary", {}),
            "completed_nodes": ["simulate"],
        }


async def c_compare(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        simulation = await session.get(Simulation, state["simulation_id"])
        results = simulation.results or {}
        comparison = {
            "baseline": {
                "label": "Unchanged baseline",
                "revenue": (simulation.baseline or {}).get("revenue"),
                "gross_margin_pct": (simulation.baseline or {}).get("gross_margin_pct"),
                "net_profit": (simulation.baseline or {}).get("net_profit"),
            },
            "scenario": results.get("scenario", {}).get("summary"),
            "alternatives": results.get("alternatives", []),
            "constraints": results.get("scenario", {}).get("constraints", []),
            "monte_carlo": simulation.monte_carlo,
            "sensitivity": simulation.sensitivity,
            "backtest": simulation.backtest,
            "separation": "All scenario values are SIMULATED. They do not modify production observations or metrics.",
        }
        report = Report(
            business_id=simulation.business_id,
            report_type="SIMULATION",
            title=f"Scenario report: {simulation.name}",
            period_end=utcnow(),
            status="READY",
            content={"simulation_id": simulation.id, "name": simulation.name, "comparison": comparison, "assumptions": simulation.assumptions},
            generated_by="simulation-agent",
        )
        session.add(report)
        await session.flush()
        await _log_step(
            session,
            state,
            "comparison",
            "Compared baseline, base, best and worst scenarios.",
            {"simulation_id": simulation.id, "report_id": report.id},
        )
        return {
            "simulation_comparison": comparison,
            "report_ids": [report.id],
            "completed_nodes": ["comparison"],
        }


async def c_finish(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        business = await session.get(Business, state["business_id"])
        session.add(
            BusinessEvent(
                business_id=business.id,
                event_type="SIMULATION_COMPLETED",
                title="Business simulation completed",
                detail="Scenario projection stored in isolation. No production state was modified.",
                severity="INFO",
                actor=state.get("actor", "system"),
                related_type="simulation",
                related_id=state.get("simulation_id", ""),
            )
        )
        await _log_step(session, state, "simulation_report", "Scenario report generated.", {"simulation_id": state.get("simulation_id")})
        return {
            "status": "COMPLETED",
            "summary": "Simulation completed and stored without modifying production state.",
            "completed_nodes": ["simulation_report"],
        }


def build_simulation_graph() -> StateGraph:
    graph = StateGraph(WorkflowState)
    graph.add_node("baseline", c_baseline)
    graph.add_node("simulate", c_simulate, retry_policy=RetryPolicy(max_attempts=2, initial_interval=1.0))
    graph.add_node("comparison", c_compare)
    graph.add_node("simulation_report", c_finish)
    graph.add_edge(START, "baseline")
    graph.add_edge("baseline", "simulate")
    graph.add_edge("simulate", "comparison")
    graph.add_edge("comparison", "simulation_report")
    graph.add_edge("simulation_report", END)
    return graph


# ---------------------------------------------------------------------------
# Workflow D: Excel Logic Conversion
# ---------------------------------------------------------------------------
async def d_inspect(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        conversion = await session.get(ExcelConversion, state["conversion_id"])
        if not conversion:
            raise TwinError("Excel conversion not found")
        conversion.workflow_run_id = state["run_id"]
        result = await excel_service.inspect_and_translate(session, conversion)
        inspection = result["inspection"]
        generated = result["generated"]
        await _log_step(
            session,
            state,
            "workbook_inspection",
            f"Inspected {inspection['formula_count']} formulas and translated {generated['generated_formula_count']}.",
            {
                "formula_count": inspection["formula_count"],
                "generated": generated["generated_formula_count"],
                "unsupported": inspection["unsupported"],
                "cycles": inspection["dependency_graph"]["cycles"],
            },
        )
        return {
            "conversion_result": {
                "status": conversion.status,
                "formula_count": inspection["formula_count"],
                "generated_formula_count": generated["generated_formula_count"],
                "unsupported": inspection["unsupported"],
                "cycles": inspection["dependency_graph"]["cycles"],
            },
            "completed_nodes": ["workbook_inspection"],
        }


async def d_validate(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        conversion = await session.get(ExcelConversion, state["conversion_id"])
        validation = await excel_service.validate(session, conversion)
        await _log_step(
            session,
            state,
            "validation",
            f"Validation status: {validation.get('status')}.",
            {
                "status": validation.get("status"),
                "datasets": validation.get("datasets"),
                "mismatches": validation.get("mismatches", [])[:10],
                "report_path": conversion.report_path,
            },
            status="SUCCEEDED" if validation.get("passed") else "REVIEW_REQUIRED",
        )
        return {
            "conversion_result": {
                **(state.get("conversion_result") or {}),
                "status": conversion.status,
                "validation_status": validation.get("status"),
                "validation_message": validation.get("message"),
                "report_path": conversion.report_path,
            },
            "completed_nodes": ["validation"],
        }


def route_after_validation(state: WorkflowState) -> str:
    return "request_approval" if (state.get("conversion_result") or {}).get("status") == "AWAITING_APPROVAL" else "review_required"


async def d_approval(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        conversion = await session.get(ExcelConversion, state["conversion_id"])
        payload = {
            "type": "excel_conversion_approval",
            "conversion_id": conversion.id,
            "business_id": conversion.business_id,
            "filename": conversion.filename,
            "validation_status": (conversion.validation or {}).get("status"),
            "validation_message": (conversion.validation or {}).get("message"),
            "outputs": (conversion.workbook_meta or {}).get("outputs", []),
            "inputs": (conversion.workbook_meta or {}).get("inputs", []),
            "unsupported": conversion.unsupported,
            "report_path": conversion.report_path,
        }
        await _log_step(
            session,
            state,
            "approval_request",
            "Workflow interrupted pending human approval of generated logic.",
            {"conversion_id": conversion.id, "report_path": conversion.report_path},
            status="WAITING_APPROVAL",
        )
    resumed = interrupt(payload)
    async with session_scope() as session:
        business = await session.get(Business, payload["business_id"])
        conversion = await session.get(ExcelConversion, payload["conversion_id"])
        approved = bool((resumed or {}).get("approved"))
        actor = (resumed or {}).get("actor", "approver")
        if approved:
            rule = await excel_service.activate(session, business, conversion, actor)
            summary = f"Conversion approved and activated as rule {rule.key} v{rule.version}."
            result = {"status": "ACTIVATED", "rule_id": rule.id, "rule_key": rule.key}
        else:
            conversion.status = "REJECTED"
            conversion.approved_by = actor
            conversion.approved_at = utcnow()
            summary = f"Conversion rejected by {actor}."
            result = {"status": "REJECTED"}
        await session.flush()
        await _log_step(
            session,
            state,
            "approval_resume",
            summary,
            {"approved": approved, "actor": actor, "comment": (resumed or {}).get("comment", "")},
            status="SUCCEEDED" if approved else "REJECTED",
        )
        return {
            "conversion_result": {**(state.get("conversion_result") or {}), **result},
            "approval_result": {"approved": approved, "actor": actor},
            "completed_nodes": ["approval"],
        }


async def d_finish(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        conversion = await session.get(ExcelConversion, state["conversion_id"])
        summary = f"Excel conversion {conversion.id} finished with status {conversion.status}."
        await _log_step(session, state, "completion", summary, {"status": conversion.status})
        return {"status": "COMPLETED", "summary": summary, "completed_nodes": ["completion"]}


async def d_review_required(state: WorkflowState) -> dict[str, Any]:
    async with session_scope() as session:
        conversion = await session.get(ExcelConversion, state["conversion_id"])
        summary = "Conversion requires review and was not activated. See the validation report for details."
        await _log_step(session, state, "review_required", summary, {"status": conversion.status}, status="REVIEW_REQUIRED")
        return {"status": "COMPLETED", "summary": summary, "completed_nodes": ["review_required"]}


def build_excel_graph() -> StateGraph:
    graph = StateGraph(WorkflowState)
    graph.add_node("workbook_inspection", d_inspect)
    graph.add_node("validation", d_validate)
    graph.add_node("request_approval", d_approval)
    graph.add_node("completion", d_finish)
    graph.add_node("review_required", d_review_required)
    graph.add_edge(START, "workbook_inspection")
    graph.add_edge("workbook_inspection", "validation")
    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {"request_approval": "request_approval", "review_required": "review_required"},
    )
    graph.add_edge("request_approval", "completion")
    graph.add_edge("review_required", END)
    graph.add_edge("completion", END)
    return graph


GRAPH_BUILDERS = {
    "daily_bi": build_daily_graph,
    "decision_execution": build_decision_graph,
    "simulation": build_simulation_graph,
    "excel_conversion": build_excel_graph,
}
