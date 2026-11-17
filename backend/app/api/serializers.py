"""Response serializers for API output (explicit, stable contracts)."""
from __future__ import annotations

from typing import Any

from app.domain.models import (
    Agent,
    Alert,
    Approval,
    BusinessAction,
    BusinessRule,
    DataSource,
    Decision,
    DecisionReview,
    ExcelConversion,
    Notification,
    Report,
    Simulation,
    WorkflowRun,
    WorkflowStep,
)


def dt(value: Any) -> str | None:
    return value.isoformat() if value else None


def agent_out(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "key": agent.key,
        "name": agent.name,
        "role": agent.role,
        "description": agent.description,
        "status": agent.status,
        "permissions": agent.permissions,
        "tools": agent.tools,
        "last_run_at": dt(agent.last_run_at),
        "last_error": agent.last_error,
        "metrics": agent.metrics,
    }


def workflow_out(run: WorkflowRun, steps: list[WorkflowStep] | None = None, include_state: bool = False) -> dict[str, Any]:
    data = {
        "id": run.id,
        "workflow": run.workflow,
        "status": run.status,
        "trigger": run.trigger,
        "summary": run.summary,
        "error": run.error,
        "started_at": dt(run.started_at),
        "finished_at": dt(run.finished_at),
        "initiated_by": run.initiated_by,
        "state": run.state if include_state else {
            key: run.state.get(key)
            for key in ("snapshot_id", "decision_id", "approval_result", "simulation_id", "conversion_id", "status", "summary")
            if key in (run.state or {})
        },
    }
    if steps is not None:
        data["steps"] = [
            {
                "id": step.id,
                "node": step.node,
                "status": step.status,
                "summary": step.summary,
                "payload": step.payload,
                "started_at": dt(step.started_at),
                "finished_at": dt(step.finished_at),
            }
            for step in steps
        ]
    return data


def alert_out(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "severity": alert.severity,
        "status": alert.status,
        "title": alert.title,
        "detail": alert.detail,
        "area": alert.area,
        "evidence": alert.evidence,
        "occurrences": alert.occurrences,
        "escalation_level": alert.escalation_level,
        "first_seen": dt(alert.first_seen),
        "last_seen": dt(alert.last_seen),
        "acknowledged_by": alert.acknowledged_by,
        "acknowledged_at": dt(alert.acknowledged_at),
        "resolved_by": alert.resolved_by,
        "resolved_at": dt(alert.resolved_at),
        "resolution_note": alert.resolution_note,
    }


def decision_out(decision: Decision, reviews: list[DecisionReview] | None = None, approval: Approval | None = None) -> dict[str, Any]:
    chosen = decision.chosen or {}
    data = {
        "id": decision.id,
        "title": decision.title,
        "issue": decision.issue,
        "objective": decision.objective,
        "status": decision.status,
        "risk_level": decision.risk_level,
        "confidence": decision.confidence,
        "reversibility": decision.reversibility,
        "expected_financial_impact": decision.expected_financial_impact,
        "requires_approval": decision.requires_approval,
        "rationale": decision.rationale,
        "evidence": decision.evidence,
        "alternatives": decision.alternatives,
        "chosen": {
            "key": chosen.get("key"),
            "title": chosen.get("title"),
            "type": chosen.get("type"),
            "risk_level": chosen.get("risk_level"),
            "implementation_cost": chosen.get("implementation_cost"),
            "expected_outcome": chosen.get("expected_outcome"),
            "assumptions": chosen.get("assumptions"),
            "action_type": chosen.get("action_type"),
            "action_parameters": chosen.get("action_parameters"),
        },
        "audit_rounds": decision.audit_rounds,
        "simulation_id": decision.simulation_id,
        "workflow_run_id": decision.workflow_run_id,
        "alert_id": decision.alert_id,
        "created_at": dt(decision.created_at),
        "updated_at": dt(decision.updated_at),
        "simulated": True,
        "approval": approval_summary(approval) if approval else None,
    }
    if reviews is not None:
        data["reviews"] = [
            {
                "id": review.id,
                "round": review.round,
                "verdict": review.verdict,
                "reasons": review.reasons,
                "conditions": review.conditions,
                "findings": review.findings,
                "reviewer": review.reviewer,
                "model_provider": review.model_provider,
                "created_at": dt(review.created_at),
            }
            for review in reviews
        ]
    return data


def approval_summary(approval: Approval) -> dict[str, Any]:
    return {
        "id": approval.id,
        "status": approval.status,
        "decided_by": approval.decided_by,
        "decided_at": dt(approval.decided_at),
        "comment": approval.comment,
        "requested_at": dt(approval.requested_at),
        "expires_at": dt(approval.expires_at),
        "policy": approval.policy,
    }


def approval_out(approval: Approval, decision: Decision | None = None) -> dict[str, Any]:
    return {
        **approval_summary(approval),
        "decision_id": approval.decision_id,
        "business_id": approval.business_id,
        "decision_title": decision.title if decision else None,
        "decision_status": decision.status if decision else None,
        "expected_financial_impact": decision.expected_financial_impact if decision else None,
        "risk_level": decision.risk_level if decision else None,
        "workflow_run_id": decision.workflow_run_id if decision else None,
    }


def action_out(action: BusinessAction, verification: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": action.id,
        "decision_id": action.decision_id,
        "action_type": action.action_type,
        "target_system": action.target_system,
        "status": action.status,
        "parameters": action.parameters,
        "expected_outcome": action.expected_outcome,
        "external_id": action.external_id,
        "result": action.result,
        "error": action.error,
        "executed_at": dt(action.executed_at),
        "verified_at": dt(action.verified_at),
        "simulated": action.simulated,
        "verification": verification,
    }


def simulation_out(simulation: Simulation) -> dict[str, Any]:
    return {
        "id": simulation.id,
        "name": simulation.name,
        "status": simulation.status,
        "scenario_id": simulation.scenario_id,
        "snapshot_id": simulation.snapshot_id,
        "baseline": simulation.baseline,
        "results": simulation.results,
        "assumptions": simulation.assumptions,
        "alternatives": simulation.alternatives,
        "monte_carlo": simulation.monte_carlo,
        "sensitivity": simulation.sensitivity,
        "backtest": simulation.backtest,
        "simulated": simulation.simulated,
        "created_by": simulation.created_by,
        "created_at": dt(simulation.created_at),
        "finished_at": dt(simulation.finished_at),
        "error": simulation.error,
    }


def report_out(report: Report, include_content: bool = False) -> dict[str, Any]:
    data = {
        "id": report.id,
        "report_type": report.report_type,
        "title": report.title,
        "status": report.status,
        "period_start": dt(report.period_start),
        "period_end": dt(report.period_end),
        "files": report.files,
        "generated_by": report.generated_by,
        "created_at": dt(report.created_at),
    }
    if include_content:
        data["content"] = report.content
    return data


def rule_out(rule: BusinessRule, include_code: bool = False) -> dict[str, Any]:
    data = {
        "id": rule.id,
        "key": rule.key,
        "name": rule.name,
        "description": rule.description,
        "category": rule.category,
        "source": rule.source,
        "version": rule.version,
        "status": rule.status,
        "dependencies": rule.dependencies,
        "execution_frequency": rule.execution_frequency,
        "input_schema": rule.input_schema,
        "output_schema": rule.output_schema,
        "tests": rule.tests,
        "approved_by": rule.approved_by,
        "approved_at": dt(rule.approved_at),
        "excel_lineage": rule.excel_lineage,
        "created_at": dt(rule.created_at),
        "updated_at": dt(rule.updated_at),
    }
    if include_code:
        data["code"] = rule.code
    return data


def source_out(source: DataSource, health: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "kind": source.kind,
        "system": source.system,
        "status": source.status,
        "simulated": source.simulated,
        "last_sync_at": dt(source.last_sync_at),
        "freshness_at": dt(source.freshness_at),
        "last_error": source.last_error,
        "records_total": source.records_total,
        "health": health,
        "config": {key: value for key, value in (source.config or {}).items() if "token" not in key.lower() and "secret" not in key.lower()},
    }


def conversion_out(conversion: ExcelConversion, include_code: bool = False, include_validation: bool = True) -> dict[str, Any]:
    validation = conversion.validation or {}
    data = {
        "id": conversion.id,
        "filename": conversion.filename,
        "status": conversion.status,
        "workflow_run_id": conversion.workflow_run_id,
        "formula_count": len(conversion.formulas or []),
        "workbook_meta": {
            "sheets": (conversion.workbook_meta or {}).get("sheets", []),
            "named_ranges": (conversion.workbook_meta or {}).get("named_ranges", []),
            "dependency_summary": (conversion.workbook_meta or {}).get("dependency_summary", {}),
            "inputs": (conversion.workbook_meta or {}).get("inputs", []),
            "outputs": (conversion.workbook_meta or {}).get("outputs", []),
            "warnings": (conversion.workbook_meta or {}).get("warnings", []),
        },
        "unsupported": conversion.unsupported,
        "dependency_graph": conversion.dependency_graph,
        "validation_summary": {
            "status": validation.get("status"),
            "passed": validation.get("passed"),
            "message": validation.get("message"),
            "datasets": validation.get("datasets", []),
            "engine": validation.get("engine"),
            "tolerance": validation.get("tolerance"),
            "duration_ms": validation.get("duration_ms"),
            "mismatches": validation.get("mismatches", [])[:20],
            "comparisons": validation.get("comparisons", [])[:200] if include_validation else [],
        },
        "report_path": conversion.report_path,
        "rule_id": conversion.rule_id,
        "approved_by": conversion.approved_by,
        "approved_at": dt(conversion.approved_at),
        "created_at": dt(conversion.created_at),
        "error": conversion.error,
    }
    if include_code:
        data["generated_code"] = conversion.generated_code
    return data


def notification_out(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "channel": notification.channel,
        "recipient": notification.recipient,
        "subject": notification.subject,
        "body": notification.body,
        "status": notification.status,
        "related_type": notification.related_type,
        "related_id": notification.related_id,
        "created_at": dt(notification.created_at),
        "sent_at": dt(notification.sent_at),
        "error": notification.error,
    }
