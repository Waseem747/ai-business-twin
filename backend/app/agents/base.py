"""Agent registry, permission declarations and execution telemetry."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.domain.models import Agent, AgentExecution


@dataclass(frozen=True)
class AgentProfile:
    key: str
    name: str
    role: str
    description: str
    permissions: tuple[str, ...]
    tools: tuple[str, ...] = field(default_factory=tuple)


AGENT_PROFILES: list[AgentProfile] = [
    AgentProfile(
        "data_acquisition",
        "Data Acquisition Agent",
        "Ingestion",
        "Retrieves business data from configured connectors with lineage, validation and deduplication.",
        ("source.read", "data.ingest", "credential.use"),
        ("rest_connector", "excel_connector", "csv_connector", "simulated_pos", "simulated_erp"),
    ),
    AgentProfile(
        "transformation",
        "Data Transformation Agent",
        "Data engineering",
        "Normalises currencies, channels and schemas while retaining original values and transformation lineage.",
        ("observation.read", "observation.transform", "transformation.registry"),
        ("currency_normalize", "channel_standardise", "quality_flag"),
    ),
    AgentProfile(
        "business_logic",
        "Business Logic Engine",
        "Deterministic calculations",
        "Executes approved custom business rules and builds the digital twin snapshot. No LLM calculation.",
        ("rule.execute", "snapshot.write", "observation.read"),
        ("rule_registry", "sandbox_executor", "formula_engine", "excel_converter"),
    ),
    AgentProfile(
        "business_intelligence",
        "Business Intelligence Analyst",
        "Analysis",
        "Detects anomalies, separates facts from hypotheses and interprets the validated business state.",
        ("metrics.read", "evidence.read", "findings.write"),
        ("anomaly_detector", "statistics_engine", "model_gateway"),
    ),
    AgentProfile(
        "decision",
        "Decision-Making Agent",
        "Recommendations",
        "Generates and ranks interventions using deterministic simulation outputs and evidence.",
        ("metrics.read", "simulation.read", "decision.write"),
        ("scenario_generator", "ranking_model", "model_gateway"),
    ),
    AgentProfile(
        "auditor",
        "Independent Decision Auditor",
        "Independent control",
        "Challenges decisions, recomputes evidence and checks policy, cash, data quality and risk. Read-only; cannot execute actions.",
        ("evidence.read", "decision.read", "review.write"),
        ("recalculation_engine", "policy_checker", "history_review"),
    ),
    AgentProfile(
        "simulation",
        "Business Simulation Agent",
        "Predictive modelling",
        "Runs isolated what-if, sensitivity and Monte Carlo simulations. Cannot modify production observations or metrics.",
        ("snapshot.read", "simulation.write"),
        ("deterministic_model", "monte_carlo", "sensitivity", "backtest"),
    ),
    AgentProfile(
        "action_execution",
        "Action Execution Agent",
        "Controlled execution",
        "Executes only approved, authorised operations with idempotency and an immutable audit trail.",
        ("action.execute_approved", "integration.write"),
        ("simulated_erp", "approval_gate", "idempotency"),
    ),
    AgentProfile(
        "execution_verification",
        "Execution Verification Agent",
        "Independent verification",
        "Retrieves external state after execution and distinguishes operational success from measured business impact.",
        ("external.read", "verification.write"),
        ("external_reader", "difference_engine"),
    ),
    AgentProfile(
        "reporting",
        "Reporting and Management Agent",
        "Management communication",
        "Generates daily summaries, exception reports, decision reports and exports with evidence lineage.",
        ("report.read", "report.write", "notification.send"),
        ("pdf_renderer", "excel_renderer", "notification_service"),
    ),
]

PROFILES_BY_KEY = {profile.key: profile for profile in AGENT_PROFILES}


async def seed_agents(session: AsyncSession, business_id: str) -> None:
    existing = set(
        (
            await session.execute(select(Agent.key).where(Agent.business_id == business_id))
        ).scalars().all()
    )
    for profile in AGENT_PROFILES:
        if profile.key in existing:
            continue
        session.add(
            Agent(
                business_id=business_id,
                key=profile.key,
                name=profile.name,
                role=profile.role,
                description=profile.description,
                status="IDLE",
                permissions=list(profile.permissions),
                tools=list(profile.tools),
                metrics={"executions": 0, "failures": 0, "avg_duration_ms": 0, "total_duration_ms": 0},
            )
        )
    await session.flush()


class AgentRuntime:
    async def record(
        self,
        session: AsyncSession,
        *,
        business_id: str,
        agent_key: str,
        workflow_run_id: str | None,
        status: str,
        summary: str,
        duration_ms: float,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        error: str | None = None,
        model_provider: str = "deterministic",
    ) -> AgentExecution:
        profile = PROFILES_BY_KEY.get(agent_key)
        execution = AgentExecution(
            business_id=business_id,
            agent_key=agent_key,
            workflow_run_id=workflow_run_id,
            status=status,
            summary=summary,
            input_summary=input_summary or {},
            output_summary=output_summary or {},
            evidence=evidence or {},
            duration_ms=round(duration_ms, 1),
            error=error,
            model_provider=model_provider,
        )
        session.add(execution)
        agent = (
            await session.execute(
                select(Agent).where(Agent.business_id == business_id, Agent.key == agent_key)
            )
        ).scalar_one_or_none()
        now = utcnow()
        if agent:
            metrics = dict(agent.metrics or {})
            executions = int(metrics.get("executions", 0)) + 1
            failures = int(metrics.get("failures", 0)) + (1 if status == "FAILED" else 0)
            total_duration = float(metrics.get("total_duration_ms", 0)) + duration_ms
            metrics.update(
                {
                    "executions": executions,
                    "failures": failures,
                    "avg_duration_ms": round(total_duration / executions, 1),
                    "total_duration_ms": round(total_duration, 1),
                    "last_status": status,
                    "last_summary": summary[:300],
                }
            )
            agent.metrics = metrics
            agent.last_run_at = now
            agent.status = "DEGRADED" if failures and failures / executions > 0.3 else "ACTIVE"
            agent.last_error = error if status == "FAILED" else agent.last_error
        elif profile:
            session.add(
                Agent(
                    business_id=business_id,
                    key=profile.key,
                    name=profile.name,
                    role=profile.role,
                    description=profile.description,
                    status="ACTIVE",
                    permissions=list(profile.permissions),
                    tools=list(profile.tools),
                    last_run_at=now,
                    metrics={"executions": 1, "failures": 1 if status == "FAILED" else 0},
                )
            )
        await session.flush()
        return execution

    def timer(self) -> float:
        return time.perf_counter()


agent_runtime = AgentRuntime()
