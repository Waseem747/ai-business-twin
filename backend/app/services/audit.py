"""Independent decision auditor.

The auditor re-derives the baseline, verifies the simulation, checks policy,
cash and data quality, reviews historical outcomes and escalates uncertainty.
The verdict is deterministic; LLM text is only commentary.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_gateway import model_gateway
from app.config import settings
from app.domain.models import Business, Decision, DecisionReview, MetricSnapshot, Simulation
from app.logic import kpis


def _reason(code: str, severity: str, message: str, evidence: Any = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


class AuditorService:
    async def review(
        self,
        session: AsyncSession,
        business: Business,
        decision: Decision,
        snapshot: MetricSnapshot,
        *,
        reviewer: str = "independent-auditor",
    ) -> dict[str, Any]:
        reasons: list[dict[str, Any]] = []
        conditions: list[str] = []
        checks: list[dict[str, Any]] = []
        hard_fail = False
        requires_human = False

        def add_check(key: str, label: str, passed: bool, detail: str, severity: str = "INFO") -> None:
            checks.append({"key": key, "label": label, "passed": passed, "detail": detail, "severity": severity})

        latest = snapshot.payload.get("latest") or {}
        simulation = await session.get(Simulation, decision.simulation_id) if decision.simulation_id else None
        evidence_types = {item.get("type") for item in (decision.evidence or [])}
        required_types = {"BUSINESS_STATE", "ANOMALY", "SIMULATION"}
        evidence_ok = required_types.issubset(evidence_types) and simulation is not None
        add_check(
            "evidence_package",
            "Evidence package completeness",
            evidence_ok,
            "Evidence includes business state, anomaly findings and simulation." if evidence_ok
            else "Decision is missing required evidence types or a linked simulation.",
            "HIGH" if not evidence_ok else "INFO",
        )
        if not evidence_ok:
            hard_fail = True
            reasons.append(
                _reason(
                    "INSUFFICIENT_EVIDENCE",
                    "HIGH",
                    "Decision cannot be audited without business-state, anomaly and simulation evidence.",
                    {"evidence_types": sorted(evidence_types)},
                )
            )

        if simulation:
            base_revenue = simulation.baseline.get("revenue")
            base_cogs = simulation.baseline.get("cogs")
            recalculated_margin = kpis.gross_margin_pct(base_revenue, base_cogs)
            baseline_ok = (
                recalculated_margin is not None
                and latest.get("gross_margin_pct") is not None
                and abs(recalculated_margin - latest["gross_margin_pct"]) <= 0.05
                and abs(float(base_revenue or 0) - float(latest.get("revenue") or 0)) < 1
            )
            add_check(
                "baseline_recalculation",
                "Baseline independently recalculated",
                baseline_ok,
                f"Auditor computed gross margin {recalculated_margin}% from raw revenue/COGS; snapshot reports {latest.get('gross_margin_pct')}%.",
                "HIGH" if not baseline_ok else "INFO",
            )
            if not baseline_ok:
                hard_fail = True
                reasons.append(
                    _reason(
                        "BASELINE_MISMATCH",
                        "HIGH",
                        "The simulation baseline does not reconcile to the validated business snapshot.",
                        {"recalculated_margin": recalculated_margin, "snapshot_margin": latest.get("gross_margin_pct")},
                    )
                )

            scenario_summary = ((simulation.results or {}).get("scenario") or {}).get("summary") or {}
            impact = float(scenario_summary.get("net_profit_delta") or 0)
            impact_ok = abs(impact - float(decision.expected_financial_impact or 0)) <= 1.0
            add_check(
                "impact_recalculation",
                "Financial impact ties to simulation",
                impact_ok,
                f"Decision states ${decision.expected_financial_impact:,.2f}; simulation summary states ${impact:,.2f}.",
                "HIGH" if not impact_ok else "INFO",
            )
            if not impact_ok:
                hard_fail = True
                reasons.append(
                    _reason(
                        "IMPACT_MISMATCH",
                        "HIGH",
                        "The expected financial impact does not match the deterministic simulation output.",
                        {"decision": decision.expected_financial_impact, "simulation": impact},
                    )
                )

            assumptions = (simulation.assumptions or {}).get("model_assumptions") or {}
            assumptions_ok = bool(assumptions) and bool((simulation.assumptions or {}).get("parameter_assumptions"))
            add_check(
                "explicit_assumptions",
                "Modelling assumptions are explicit",
                assumptions_ok,
                f"{len(assumptions)} model assumptions and scenario parameters are recorded.",
                "MEDIUM" if not assumptions_ok else "INFO",
            )
            if not assumptions_ok:
                conditions.append("Document and approve all scenario assumptions before execution.")

            baseline_margin = float(latest.get("gross_margin_pct") or 0)
            exit_margin = float(scenario_summary.get("exit_gross_margin_pct") or 0)
            improves_margin = exit_margin > baseline_margin
            add_check(
                "objective_alignment",
                "Intervention improves the targeted margin",
                improves_margin,
                f"Projected exit gross margin {exit_margin:.2f}% versus baseline {baseline_margin:.2f}%.",
                "HIGH" if not improves_margin else "INFO",
            )
            if not improves_margin:
                reasons.append(
                    _reason(
                        "OBJECTIVE_MISALIGNED",
                        "HIGH",
                        "The selected intervention does not improve the targeted margin in the base case.",
                        {"exit_margin": exit_margin, "baseline_margin": baseline_margin},
                    )
                )
                hard_fail = True

            minimum_cash = float(scenario_summary.get("minimum_cash") or 0)
            cash_ok = minimum_cash >= settings.human_approval_threshold_usd  # policy floor checked below via snapshot
            policy_floor = float(
                ((snapshot.payload.get("drivers") or {}).get("minimum_cash_policy") or {}).get("value") or 250_000
            )
            cash_ok = minimum_cash >= policy_floor
            add_check(
                "cash_policy",
                "Projected cash remains above policy floor",
                cash_ok,
                f"Minimum projected cash ${minimum_cash:,.0f}; policy floor ${policy_floor:,.0f}.",
                "CRITICAL" if not cash_ok else "INFO",
            )
            if not cash_ok:
                hard_fail = True
                reasons.append(
                    _reason(
                        "CASH_POLICY_BREACH",
                        "CRITICAL",
                        "The base-case projection breaches the treasury cash floor.",
                        {"minimum_cash": minimum_cash, "policy_floor": policy_floor},
                    )
                )

            implementation_cost = float((decision.chosen or {}).get("implementation_cost") or 0)
            available_cash = float(latest.get("cash_balance") or 0)
            affordability = implementation_cost <= max(10_000, available_cash * 0.10)
            add_check(
                "implementation_affordability",
                "Implementation cost is affordable",
                affordability,
                f"Implementation cost ${implementation_cost:,.0f}; 10% cash affordability limit ${available_cash * 0.10:,.0f}.",
                "HIGH" if not affordability else "INFO",
            )
            if not affordability:
                hard_fail = True
                reasons.append(
                    _reason(
                        "UNAFFORDABLE",
                        "HIGH",
                        "The one-off implementation cost exceeds the configured cash affordability limit.",
                        {"implementation_cost": implementation_cost, "cash": available_cash},
                    )
                )

            constraints = scenario_summary.get("constraints") or []
            breached = [constraint for constraint in constraints if constraint.get("status") == "BREACHED"]
            add_check(
                "simulation_constraints",
                "Simulation policy constraints",
                not breached,
                f"{len(breached)} scenario constraint(s) breached." if breached else "All configured scenario constraints passed.",
                "HIGH" if breached else "INFO",
            )
            if breached:
                for constraint in breached:
                    reasons.append(
                        _reason("CONSTRAINT_BREACH", "HIGH", constraint.get("message", "Constraint breached"), constraint)
                    )
                    conditions.append(constraint.get("message", "Resolve constraint breach before execution."))

            monte_carlo = simulation.monte_carlo or {}
            probability = monte_carlo.get("probability_above_baseline")
            robustness_ok = probability is None or probability >= 60
            add_check(
                "monte_carlo_robustness",
                "Monte Carlo robustness",
                robustness_ok,
                f"{probability}% of simulations outperform baseline." if probability is not None else "No Monte Carlo run recorded.",
                "MEDIUM" if not robustness_ok else "INFO",
            )
            if probability is not None and probability < 55:
                requires_human = True
                reasons.append(
                    _reason(
                        "OUTCOME_UNCERTAIN",
                        "HIGH",
                        "Most uncertainty simulations do not outperform the baseline; human judgement is required.",
                        {"probability_above_baseline": probability},
                    )
                )
            elif probability is not None and probability < 70:
                conditions.append(f"Outcome uncertainty: {probability}% of simulations beat baseline; stage the rollout with a review gate.")

        completeness = float((snapshot.payload.get("data_quality") or {}).get("completeness_pct") or 0)
        quality_ok = completeness >= 90
        add_check(
            "data_quality",
            "Input data completeness",
            quality_ok,
            f"Completeness {completeness:.1f}%; stale sources: {', '.join((snapshot.payload.get('data_quality') or {}).get('stale_sources') or []) or 'none'}.",
            "HIGH" if not quality_ok else "INFO",
        )
        if not quality_ok:
            requires_human = True
            reasons.append(
                _reason("DATA_QUALITY", "HIGH", "Data completeness is below 90%; the decision cannot be automatically cleared.", {"completeness": completeness})
            )
        if (snapshot.payload.get("data_quality") or {}).get("stale_sources"):
            conditions.append("Refresh stale sources and re-run the impact assessment before execution.")

        confidence = float(decision.confidence or 0)
        confidence_ok = confidence >= 0.55
        add_check(
            "confidence",
            "Decision confidence threshold",
            confidence_ok,
            f"Decision confidence {confidence:.2f} versus minimum 0.55.",
            "HIGH" if not confidence_ok else "INFO",
        )
        if not confidence_ok:
            requires_human = True
            reasons.append(_reason("LOW_CONFIDENCE", "HIGH", "Decision confidence is below the automatic clearance threshold.", {"confidence": confidence}))

        # Historical outcomes for the same intervention type, if any.
        history = (
            await session.execute(
                select(Decision)
                .where(
                    Decision.business_id == business.id,
                    Decision.id != decision.id,
                    Decision.status.in_(["VERIFIED", "FAILED", "EXECUTED"]),
                )
                .order_by(desc(Decision.created_at))
                .limit(10)
            )
        ).scalars().all()
        similar = [item for item in history if (item.chosen or {}).get("type") == (decision.chosen or {}).get("type")]
        failures = [item for item in similar if item.status == "FAILED"]
        history_ok = not similar or len(failures) / len(similar) <= 0.4
        add_check(
            "historical_outcomes",
            "Historical outcome review",
            history_ok,
            f"{len(similar)} similar past intervention(s); {len(failures)} failed." if similar else "No prior comparable interventions in this tenant.",
            "MEDIUM" if not history_ok else "INFO",
        )
        if not history_ok:
            conditions.append("Review prior failed interventions of this type before proceeding.")

        decision_type = (decision.chosen or {}).get("type", "")
        legal_condition = decision_type in {"PROCUREMENT", "PRICING"}
        if legal_condition:
            conditions.append("Legal/procurement review is required for contractual or pricing changes.")
        requires_approval = decision.requires_approval or abs(float(decision.expected_financial_impact)) > settings.human_approval_threshold_usd
        decision.requires_approval = requires_approval
        if requires_approval:
            conditions.append(
                f"Human approval is mandatory: projected impact ${decision.expected_financial_impact:,.0f} exceeds the ${settings.human_approval_threshold_usd:,.0f} policy threshold or the action is contractual/pricing related."
            )

        if hard_fail:
            verdict = "REJECTED"
        elif requires_human or confidence < 0.55:
            verdict = "REQUIRES_HUMAN_REVIEW"
        elif conditions:
            verdict = "APPROVED_WITH_CONDITIONS"
        else:
            verdict = "APPROVED"

        for condition in conditions:
            reasons.append(_reason("CONDITION", "INFO", condition))

        decision.audit_rounds = (decision.audit_rounds or 0) + 1
        deterministic_narrative = (
            f"{verdict.replace('_', ' ').title()}. The auditor independently reconciled the baseline, checked the projected impact against the simulation, "
            f"tested cash policy, affordability, uncertainty and data quality. "
            f"{len([r for r in reasons if r['severity'] in {'HIGH','CRITICAL'}])} high-severity issue(s) and {len(conditions)} condition(s) were recorded."
        )
        narrative = await model_gateway.narrate(
            "audit_narrative",
            {
                "verdict": verdict,
                "checks": checks,
                "reasons": reasons,
                "decision": {"title": decision.title, "impact": decision.expected_financial_impact, "risk": decision.risk_level},
            },
            deterministic_text=deterministic_narrative,
            system_prompt=(
                "You are an independent internal audit controller. Summarise the deterministic audit result. "
                "Do not change the verdict, invent facts or omit conditions. Be concise and skeptical."
            ),
        )
        review = DecisionReview(
            decision_id=decision.id,
            round=decision.audit_rounds,
            verdict=verdict,
            reasons=reasons,
            conditions=conditions,
            findings={
                "checks": checks,
                "narrative": narrative.as_dict(),
                "independence": "Auditor has read-only evidence access and no action-execution tools.",
                "data_snapshot_id": snapshot.id,
            },
            reviewer=reviewer,
            model_provider=narrative.provider,
        )
        session.add(review)
        if verdict == "REJECTED":
            decision.status = "REJECTED"
        else:
            decision.status = "AUDITED"
        await session.flush()
        return {
            "review_id": review.id,
            "verdict": verdict,
            "reasons": reasons,
            "conditions": conditions,
            "checks": checks,
            "narrative": narrative.as_dict(),
            "round": decision.audit_rounds,
            "requires_approval": decision.requires_approval,
        }


auditor_service = AuditorService()
