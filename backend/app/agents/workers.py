"""Specialised agent implementations.

Each agent has a narrow responsibility, declared permissions, structured
inputs/outputs and telemetry.  No agent is a free-running chatbot.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import agent_runtime
from app.agents.model_gateway import model_gateway
from app.domain.models import (
    Business,
    BusinessAction,
    DataSource,
    Decision,
    IngestionRun,
    MetricSnapshot,
    Report,
    Simulation,
)
from app.logic.registry import rule_registry
from app.services.actions import action_service
from app.services.anomalies import detect_anomalies
from app.services.audit import auditor_service
from app.services.decisions import decision_service
from app.services.ingestion import ingestion_service
from app.services.reporting import reporting_service
from app.services.transformation import transformation_service
from app.services.twin_state import ensure_snapshot
from app.services.verification import verification_service
from app.simulation.service import simulation_service


class BaseAgent:
    key: str = "base"

    def __init__(self) -> None:
        self._started = time.perf_counter()

    async def record(
        self,
        session: AsyncSession,
        business_id: str,
        *,
        status: str = "SUCCEEDED",
        summary: str,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        workflow_run_id: str | None = None,
        error: str | None = None,
        model_provider: str = "deterministic",
    ) -> None:
        await agent_runtime.record(
            session,
            business_id=business_id,
            agent_key=self.key,
            workflow_run_id=workflow_run_id,
            status=status,
            summary=summary,
            duration_ms=(time.perf_counter() - self._started) * 1000,
            input_summary=input_summary,
            output_summary=output_summary,
            evidence=evidence,
            error=error,
            model_provider=model_provider,
        )

    def reset_timer(self) -> None:
        self._started = time.perf_counter()


class DataAcquisitionAgent(BaseAgent):
    key = "data_acquisition"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        source_ids: list[str] | None = None,
        *,
        trigger: str = "WORKFLOW",
        actor: str = "data-acquisition-agent",
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        self.reset_timer()
        query = select(DataSource).where(DataSource.business_id == business.id)
        if source_ids:
            query = query.where(DataSource.id.in_(source_ids))
        sources = (await session.execute(query)).scalars().all()
        runs: list[IngestionRun] = []
        errors = []
        for source in sources:
            run = await ingestion_service.sync_source(session, source, trigger=trigger, actor=actor)
            runs.append(run)
            if run.status != "SUCCEEDED":
                errors.append({"source_id": source.id, "error": run.error})
        output = {
            "sources": len(sources),
            "runs": [
                {
                    "id": run.id,
                    "source_id": run.data_source_id,
                    "status": run.status,
                    "ingested": run.records_ingested,
                    "rejected": run.records_rejected,
                    "duplicates": run.duplicates_blocked,
                    "raw_payload_ref": run.raw_payload_ref,
                }
                for run in runs
            ],
            "errors": errors,
        }
        await self.record(
            session,
            business.id,
            status="SUCCEEDED" if not errors else "PARTIAL",
            summary=f"Synchronised {len(sources)} source(s); {sum(run.records_ingested for run in runs)} facts ingested.",
            input_summary={"source_ids": source_ids, "trigger": trigger},
            output_summary=output,
            workflow_run_id=workflow_run_id,
            error="; ".join(error["error"] or "" for error in errors) if errors else None,
        )
        return output


class TransformationAgent(BaseAgent):
    key = "transformation"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        ingestion_run_ids: list[str] | None = None,
        *,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        self.reset_timer()
        runs = []
        for run_id in ingestion_run_ids or [None]:
            runs.extend(await transformation_service.apply_active(session, business.id, run_id))
        output = {
            "transformations": len(runs),
            "stats": [
                {"id": run.id, "status": run.status, "stats": run.stats} for run in runs
            ],
            "raw_data_modified": False,
        }
        await self.record(
            session,
            business.id,
            summary=f"Applied {len(runs)} active transformation(s); raw payloads were not modified.",
            input_summary={"ingestion_run_ids": ingestion_run_ids},
            output_summary=output,
            workflow_run_id=workflow_run_id,
        )
        return output


class BusinessLogicAgent(BaseAgent):
    key = "business_logic"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        *,
        execute_rules: bool = True,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        self.reset_timer()
        snapshot = await ensure_snapshot(session, business, max_age_minutes=0)
        latest = snapshot.payload.get("latest", {})
        rule_outputs: dict[str, Any] = {}
        rule_errors: list[str] = []
        if execute_rules:
            rule_inputs = [
                (
                    "gross_margin",
                    {"revenue": latest.get("revenue"), "cost_of_goods_sold": latest.get("cogs")},
                ),
                (
                    "net_profit_margin",
                    {
                        "revenue": latest.get("revenue"),
                        "cost_of_goods_sold": latest.get("cogs"),
                        "marketing": latest.get("marketing_spend"),
                        "payroll": latest.get("payroll"),
                        "occupancy": latest.get("occupancy"),
                        "other_opex": latest.get("other_opex"),
                    },
                ),
                (
                    "days_sales_outstanding",
                    {"receivables": latest.get("receivables"), "revenue": latest.get("revenue"), "days_in_period": 30},
                ),
                (
                    "inventory_turnover",
                    {
                        "cogs_annualised": (latest.get("cogs") or 0) * 12,
                        "average_inventory": latest.get("inventory_value"),
                    },
                ),
                (
                    "marketing_roas",
                    {"attributed_revenue": latest.get("revenue"), "marketing_spend": latest.get("marketing_spend")},
                ),
            ]
            for key, inputs in rule_inputs:
                try:
                    outputs = await rule_registry.execute_key(
                        session, business.id, key, inputs, actor="business-logic-engine"
                    )
                    rule_outputs[key] = outputs
                except Exception as exc:  # noqa: BLE001
                    rule_errors.append(f"{key}: {exc}")
            # Persist the custom-rule results alongside the calculated snapshot.
            payload = dict(snapshot.payload)
            payload["custom_logic"] = {"rule_outputs": rule_outputs, "errors": rule_errors}
            snapshot.payload = payload
            await session.flush()
        output = {
            "snapshot_id": snapshot.id,
            "health_score": snapshot.health_score,
            "custom_rules_executed": len(rule_outputs),
            "rule_outputs": rule_outputs,
            "rule_errors": rule_errors,
            "calculation_engine": "deterministic",
        }
        await self.record(
            session,
            business.id,
            status="SUCCEEDED" if not rule_errors else "PARTIAL",
            summary=f"Built business snapshot {snapshot.payload.get('latest', {}).get('label')} with {len(rule_outputs)} approved rule execution(s).",
            input_summary={"execute_rules": execute_rules},
            output_summary=output,
            evidence={"snapshot_id": snapshot.id, "lineage": snapshot.evidence},
            workflow_run_id=workflow_run_id,
            error="; ".join(rule_errors) if rule_errors else None,
        )
        return output


class BusinessIntelligenceAgent(BaseAgent):
    key = "business_intelligence"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        snapshot: MetricSnapshot,
        *,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        self.reset_timer()
        analysis = detect_anomalies(snapshot.payload)
        narrative = await model_gateway.narrate(
            "bi_narrative",
            {
                "business_summary": snapshot.payload.get("summary"),
                "kpis": snapshot.payload.get("kpis"),
                "findings": analysis["findings"],
                "health": snapshot.payload.get("health"),
            },
            deterministic_text=snapshot.payload.get("summary", "")
            + " "
            + analysis["summary"]
            + " Facts, statistical anomalies, risks and hypotheses are labelled separately in the findings list.",
        )
        output = {
            "findings": analysis["findings"],
            "issue": analysis["issue"],
            "counts": analysis["counts"],
            "narrative": narrative.as_dict(),
            "evidence_snapshot_id": snapshot.id,
        }
        await self.record(
            session,
            business.id,
            summary=f"Identified {len(analysis['findings'])} finding(s): {analysis['summary']}",
            input_summary={"snapshot_id": snapshot.id, "period": snapshot.payload.get("latest", {}).get("label")},
            output_summary={
                "counts": analysis["counts"],
                "issue_title": (analysis["issue"] or {}).get("title"),
                "top_findings": [finding["title"] for finding in analysis["findings"][:5]],
            },
            evidence={"snapshot_id": snapshot.id, "findings": analysis["findings"]},
            workflow_run_id=workflow_run_id,
            model_provider=narrative.provider,
        )
        return output


class DecisionAgent(BaseAgent):
    key = "decision"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        snapshot: MetricSnapshot,
        issue: dict[str, Any],
        *,
        workflow_run_id: str | None = None,
    ) -> Decision:
        self.reset_timer()
        decision = await decision_service.generate(session, business, snapshot, issue)
        decision.workflow_run_id = workflow_run_id
        await session.flush()
        await self.record(
            session,
            business.id,
            summary=f"Generated decision '{decision.title}' with {len(decision.alternatives)} ranked alternative(s).",
            input_summary={"issue": issue.get("title"), "snapshot_id": snapshot.id},
            output_summary={
                "decision_id": decision.id,
                "chosen": (decision.chosen or {}).get("key"),
                "expected_impact": decision.expected_financial_impact,
                "risk": decision.risk_level,
                "requires_approval": decision.requires_approval,
                "simulation_id": decision.simulation_id,
            },
            evidence={"evidence": decision.evidence},
            workflow_run_id=workflow_run_id,
            model_provider="deterministic+gateway",
        )
        return decision

    async def revise(
        self,
        session: AsyncSession,
        business: Business,
        decision: Decision,
        audit: dict[str, Any],
        *,
        workflow_run_id: str | None = None,
    ) -> Decision:
        self.reset_timer()
        await decision_service.revise(session, decision, audit.get("reasons", []))
        await self.record(
            session,
            business.id,
            status="SUCCEEDED",
            summary=f"Revised decision to '{decision.title}'. Audit issues addressed.",
            input_summary={"decision_id": decision.id, "audit_round": audit.get("round")},
            output_summary={"chosen": (decision.chosen or {}).get("key"), "status": decision.status},
            evidence={"audit_reasons": audit.get("reasons")},
            workflow_run_id=workflow_run_id,
        )
        return decision


class AuditorAgent(BaseAgent):
    key = "auditor"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        decision: Decision,
        snapshot: MetricSnapshot,
        *,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        self.reset_timer()
        result = await auditor_service.review(session, business, decision, snapshot)
        await self.record(
            session,
            business.id,
            summary=f"Audit verdict: {result['verdict']} with {len(result['conditions'])} condition(s).",
            input_summary={"decision_id": decision.id, "snapshot_id": snapshot.id},
            output_summary={
                "review_id": result["review_id"],
                "verdict": result["verdict"],
                "conditions": result["conditions"],
                "round": result["round"],
            },
            evidence={"checks": result["checks"], "reasons": result["reasons"]},
            workflow_run_id=workflow_run_id,
            model_provider=result["narrative"].get("provider", "deterministic"),
        )
        return result


class SimulationAgent(BaseAgent):
    key = "simulation"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        snapshot: MetricSnapshot,
        parameters: dict[str, Any],
        *,
        name: str,
        description: str = "",
        created_by: str = "simulation-agent",
        with_monte_carlo: bool = True,
        workflow_run_id: str | None = None,
    ) -> Simulation:
        self.reset_timer()
        simulation, scenario, _results = await simulation_service.run(
            session,
            business,
            snapshot,
            parameters,
            name=name,
            description=description,
            created_by=created_by,
            with_monte_carlo=with_monte_carlo,
        )
        await self.record(
            session,
            business.id,
            summary=f"Completed simulation '{name}' with {simulation.monte_carlo.get('iterations', 0)} Monte Carlo draws.",
            input_summary={"parameters": parameters, "snapshot_id": snapshot.id},
            output_summary={
                "simulation_id": simulation.id,
                "net_profit_delta": ((simulation.results.get("scenario") or {}).get("summary") or {}).get("net_profit_delta"),
                "simulated": True,
                "production_state_modified": False,
            },
            evidence={"assumptions": simulation.assumptions, "snapshot_id": snapshot.id},
            workflow_run_id=workflow_run_id,
        )
        return simulation


class ActionExecutionAgent(BaseAgent):
    key = "action_execution"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        decision: Decision,
        *,
        workflow_run_id: str | None = None,
    ) -> BusinessAction:
        self.reset_timer()
        action = await action_service.execute(session, business, decision, actor="action-execution-agent")
        await self.record(
            session,
            business.id,
            summary=f"Executed {action.action_type} against {action.target_system} (simulated={action.simulated}).",
            input_summary={"decision_id": decision.id, "status": decision.status},
            output_summary={
                "action_id": action.id,
                "status": action.status,
                "external_id": action.external_id,
                "simulated": action.simulated,
                "idempotency_key": action.idempotency_key,
            },
            evidence={"request": action.parameters, "expected": action.expected_outcome},
            workflow_run_id=workflow_run_id,
        )
        return action


class ExecutionVerificationAgent(BaseAgent):
    key = "execution_verification"

    async def run(
        self,
        session: AsyncSession,
        business: Business,
        action: BusinessAction,
        decision: Decision,
        *,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        self.reset_timer()
        result = await verification_service.verify(session, business, action, decision)
        await self.record(
            session,
            business.id,
            status="SUCCEEDED" if result["status"] == "VERIFIED" else "PARTIAL",
            summary=f"Verification status {result['status']} with {len(result['differences'])} difference(s).",
            input_summary={"action_id": action.id},
            output_summary=result,
            evidence={"expected": action.parameters, "actual": result["actual"]},
            workflow_run_id=workflow_run_id,
        )
        return result


class ReportingAgent(BaseAgent):
    key = "reporting"

    async def daily(
        self,
        session: AsyncSession,
        business: Business,
        snapshot: MetricSnapshot,
        *,
        workflow_run_id: str | None = None,
    ) -> dict[str, Report]:
        self.reset_timer()
        daily = await reporting_service.generate_daily(session, business, snapshot)
        exception = await reporting_service.generate_exception(session, business, snapshot)
        await self.record(
            session,
            business.id,
            summary=f"Generated daily executive and exception reports for {snapshot.payload.get('latest', {}).get('label')}.",
            input_summary={"snapshot_id": snapshot.id},
            output_summary={
                "daily_report_id": daily.id,
                "exception_report_id": exception.id,
                "files": daily.files,
                "open_exceptions": len(exception.content.get("exceptions", [])),
            },
            evidence={"snapshot_id": snapshot.id},
            workflow_run_id=workflow_run_id,
        )
        return {"daily": daily, "exception": exception}

    async def decision(
        self,
        session: AsyncSession,
        business: Business,
        decision: Decision,
        *,
        workflow_run_id: str | None = None,
    ) -> Report:
        self.reset_timer()
        report = await reporting_service.generate_decision_report(session, business, decision)
        await self.record(
            session,
            business.id,
            summary=f"Generated decision report for '{decision.title}'.",
            input_summary={"decision_id": decision.id},
            output_summary={"report_id": report.id, "files": report.files},
            workflow_run_id=workflow_run_id,
        )
        return report


data_acquisition_agent = DataAcquisitionAgent()
transformation_agent = TransformationAgent()
business_logic_agent = BusinessLogicAgent()
bi_agent = BusinessIntelligenceAgent()
decision_agent = DecisionAgent()
auditor_agent = AuditorAgent()
simulation_agent = SimulationAgent()
action_agent = ActionExecutionAgent()
verification_agent = ExecutionVerificationAgent()
reporting_agent = ReportingAgent()
