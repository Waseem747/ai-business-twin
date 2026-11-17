"""Decision generation.

Alternatives are defined as deterministic business playbooks and evaluated by
the simulation engine.  The LLM may write the rationale, but it cannot choose
figures, rank by invented numbers or bypass approval policy.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_gateway import model_gateway
from app.config import settings
from app.core.utils import utcnow
from app.domain.models import Business, Decision, MetricSnapshot, Simulation
from app.simulation import model
from app.simulation.service import simulation_service


def _baseline(snapshot: MetricSnapshot) -> dict[str, Any]:
    baseline = dict(snapshot.payload.get("latest") or {})
    baseline["channels"] = snapshot.payload.get("channels") or []
    baseline["discount_depth_pct"] = (
        (snapshot.payload.get("drivers") or {}).get("discount_depth_pct") or {}
    ).get("value", 8.0)
    return baseline


def _playbooks(snapshot: MetricSnapshot) -> list[dict[str, Any]]:
    discount = _baseline(snapshot).get("discount_depth_pct", 8.0)
    return [
        {
            "key": "supplier_renegotiation",
            "title": "Renegotiate Atlas Home Goods pricing and qualify a secondary supplier",
            "type": "PROCUREMENT",
            "action_type": "SUPPLIER_CONTRACT_REVIEW",
            "parameters": {"cogs_change_pct": -5.0, "one_off_cost": 25_000},
            "implementation_cost": 25_000,
            "time_horizon_months": 3,
            "reversibility": "PARTIALLY_REVERSIBLE",
            "risk_level": "MEDIUM",
            "assumptions": [
                "A 5% landed-cost reduction is negotiated on the Atlas Home Goods contract.",
                "A secondary supplier is qualified within 60 days; no supply disruption.",
                "One-off legal and qualification cost of $25,000 is incurred in month 1.",
            ],
            "action_parameters": {
                "supplier": "Atlas Home Goods",
                "requested_reduction_pct": 5.0,
                "contract_renewal_window_days": 45,
                "secondary_supplier": "Coastal Supply Co.",
            },
        },
        {
            "key": "discount_discipline",
            "title": "Tighten promotional discount depth from 11.8% to 8.8%",
            "type": "PRICING",
            "action_type": "PROMOTION_POLICY_UPDATE",
            "parameters": {"discount_change_pp": -3.0, "one_off_cost": 5_000},
            "implementation_cost": 5_000,
            "time_horizon_months": 2,
            "reversibility": "REVERSIBLE",
            "risk_level": "MEDIUM",
            "assumptions": [
                "Average discount depth reduces by 3pp across retail channels.",
                "Volume response is modelled at -0.6% volume per 1pp of discount removed.",
                "A $5,000 one-off cost covers promotion system changes and customer communication.",
            ],
            "action_parameters": {
                "current_discount_depth_pct": discount,
                "target_discount_depth_pct": max(0.0, round(discount - 3.0, 1)),
                "scope": "Stores,Online",
            },
        },
        {
            "key": "selective_price_increase",
            "title": "Apply a 3% price increase on selected retail categories",
            "type": "PRICING",
            "action_type": "PRICE_UPDATE",
            "parameters": {"price_change_pct": 3.0, "one_off_cost": 8_000},
            "implementation_cost": 8_000,
            "time_horizon_months": 2,
            "reversibility": "REVERSIBLE",
            "risk_level": "HIGH",
            "assumptions": [
                "Price rises 3% on the retail book; wholesale pricing is contractually locked.",
                "Price elasticity is -0.8, so a 3% increase reduces retail volume by 2.4%.",
                "A $8,000 one-off cost covers pricing analytics, label updates and customer notice.",
            ],
            "action_parameters": {
                "price_change_pct": 3.0,
                "scope": "Stores,Online",
                "apply_date_note": "Next catalogue cycle",
            },
        },
        {
            "key": "procurement_mix",
            "title": "Shift 25% of volume to a lower-cost supplier",
            "type": "PROCUREMENT",
            "action_type": "PROCUREMENT_ALLOCATION_UPDATE",
            "parameters": {"cogs_change_pct": -2.5, "one_off_cost": 12_000},
            "implementation_cost": 12_000,
            "time_horizon_months": 2,
            "reversibility": "PARTIALLY_REVERSIBLE",
            "risk_level": "MEDIUM",
            "assumptions": [
                "25% of category volume moves to Coastal Supply Co. at a 2.5% blended cost reduction.",
                "Quality audit passes and no stock-out occurs.",
                "One-off transition cost of $12,000.",
            ],
            "action_parameters": {
                "supplier": "Coastal Supply Co.",
                "volume_shift_pct": 25,
                "target_system": "simulated_erp",
            },
        },
        {
            "key": "discretionary_opex_reduction",
            "title": "Reduce discretionary operating expenses by 6%",
            "type": "OPERATING_COST",
            "action_type": "BUDGET_UPDATE",
            "parameters": {"other_opex_change_pct": -6.0, "one_off_cost": 0},
            "implementation_cost": 0,
            "time_horizon_months": 1,
            "reversibility": "REVERSIBLE",
            "risk_level": "LOW",
            "assumptions": [
                "Discretionary non-marketing operating costs reduce by 6% without service impact.",
                "No headcount reduction is assumed.",
            ],
            "action_parameters": {"category": "discretionary_opex", "reduction_pct": 6.0},
        },
        {
            "key": "inventory_release",
            "title": "Release 8% of slow-moving inventory into working capital",
            "type": "WORKING_CAPITAL",
            "action_type": "INVENTORY_REALLOCATION",
            "parameters": {"inventory_change_pct": -8.0, "one_off_cost": 6_000},
            "implementation_cost": 6_000,
            "time_horizon_months": 3,
            "reversibility": "PARTIALLY_REVERSIBLE",
            "risk_level": "MEDIUM",
            "assumptions": [
                "Slow-moving inventory reduces by 8% with no impact on available SKUs.",
                "Holding cost falls at 1.2% per month of inventory value.",
                "One-off redistribution cost of $6,000.",
            ],
            "action_parameters": {"inventory_reduction_pct": 8.0, "scope": "slow_moving_skus"},
        },
    ]


class DecisionService:
    async def generate(
        self,
        session: AsyncSession,
        business: Business,
        snapshot: MetricSnapshot,
        issue: dict[str, Any],
        *,
        actor: str = "decision-making-agent",
    ) -> Decision:
        baseline = _baseline(snapshot)
        playbooks = _playbooks(snapshot)
        evaluated: list[dict[str, Any]] = []
        for playbook in playbooks:
            basic = model.simulate(baseline, playbook["parameters"], horizon_months=12)
            evaluated.append({**playbook, "simulation": basic})

        max_impact = max(abs(item["simulation"]["summary"]["net_profit_delta"]) for item in evaluated) or 1.0
        max_cost = max(item["implementation_cost"] for item in evaluated) or 1.0
        risk_score = {"LOW": 0.12, "MEDIUM": 0.42, "HIGH": 0.75}
        reversibility_score = {"REVERSIBLE": 1.0, "PARTIALLY_REVERSIBLE": 0.55, "IRREVERSIBLE": 0.1}
        for item in evaluated:
            summary = item["simulation"]["summary"]
            impact = summary["net_profit_delta"]
            normalized_impact = max(0.0, impact) / max_impact
            confidence = 0.74
            quality = snapshot.payload.get("data_quality") or {}
            if float(quality.get("completeness_pct", 100)) < 95:
                confidence -= 0.08
            if quality.get("stale_sources"):
                confidence -= 0.1
            if item["risk_level"] == "HIGH":
                confidence -= 0.06
            score = (
                0.55 * normalized_impact
                + 0.15 * (1 - risk_score[item["risk_level"]])
                + 0.10 * (1 - item["implementation_cost"] / max_cost)
                + 0.10 * reversibility_score[item["reversibility"]]
                + 0.10 * confidence
            )
            item["score"] = round(score, 4)
            item["confidence"] = round(max(0.2, min(0.9, confidence)), 2)
            item["expected_impact"] = impact
            item["summary"] = summary
        evaluated.sort(key=lambda item: item["score"], reverse=True)
        chosen = evaluated[0]
        chosen_summary = chosen["simulation"]["summary"]

        simulation, scenario, _results = await simulation_service.run(
            session,
            business,
            snapshot,
            chosen["parameters"],
            name=f"Decision simulation: {chosen['title']}",
            description=f"Pre-decision projection for issue: {issue.get('title', '')}",
            created_by=actor,
            with_monte_carlo=True,
        )

        requires_approval = (
            chosen["implementation_cost"] > 0
            or abs(chosen_summary["net_profit_delta"]) > settings.human_approval_threshold_usd
            or chosen["type"] in {"PROCUREMENT", "PRICING"}
            or chosen["risk_level"] == "HIGH"
        )
        deterministic_rationale = (
            f"The recommended intervention is to {chosen['title'].lower()}. "
            f"The deterministic model projects a 12-month net profit impact of ${chosen_summary['net_profit_delta']:,.0f} "
            f"versus the unchanged baseline, with exit gross margin of {chosen_summary['exit_gross_margin_pct']:.1f}% "
            f"and minimum projected cash of ${chosen_summary['minimum_cash']:,.0f}. "
            f"Implementation cost is ${chosen['implementation_cost']:,.0f} and the risk rating is {chosen['risk_level']}. "
            "Assumptions are explicit in the simulation record and the outcome is simulated, not measured."
        )
        narrative = await model_gateway.narrate(
            "decision_rationale",
            {
                "issue": issue.get("title"),
                "baseline": {
                    "revenue": baseline.get("revenue"),
                    "gross_margin_pct": baseline.get("gross_margin_pct"),
                    "net_profit": baseline.get("net_profit"),
                },
                "chosen_alternative": {
                    "title": chosen["title"],
                    "score": chosen["score"],
                    "risk": chosen["risk_level"],
                    "implementation_cost": chosen["implementation_cost"],
                    "simulation_summary": chosen_summary,
                    "assumptions": chosen["assumptions"],
                },
                "ranked_alternatives": [
                    {"title": item["title"], "score": item["score"], "impact": item["expected_impact"]}
                    for item in evaluated
                ],
            },
            deterministic_text=deterministic_rationale,
        )

        alternatives = [
            {
                "key": item["key"],
                "title": item["title"],
                "type": item["type"],
                "risk_level": item["risk_level"],
                "reversibility": item["reversibility"],
                "implementation_cost": item["implementation_cost"],
                "time_horizon_months": item["time_horizon_months"],
                "expected_impact_12m": item["expected_impact"],
                "exit_gross_margin_pct": item["summary"]["exit_gross_margin_pct"],
                "exit_cash_balance": item["summary"]["exit_cash_balance"],
                "roi_pct": item["summary"]["roi_pct"],
                "confidence": item["confidence"],
                "score": item["score"],
                "selected": item is chosen,
                "parameters": item["parameters"],
                "assumptions": item["assumptions"],
                "constraints": item["summary"]["constraints"],
            }
            for item in evaluated
        ]
        evidence = [
            {
                "type": "BUSINESS_STATE",
                "source": "Business Logic Engine",
                "snapshot_id": snapshot.id,
                "period": baseline.get("label"),
                "metrics": {
                    "revenue": baseline.get("revenue"),
                    "gross_margin_pct": baseline.get("gross_margin_pct"),
                    "net_profit": baseline.get("net_profit"),
                },
            },
            {
                "type": "ANOMALY",
                "source": "Business Intelligence Agent",
                "finding_ids": [finding.get("id") for finding in issue.get("findings", [])][:8],
                "severity": issue.get("severity"),
                "summary": issue.get("summary"),
            },
            {
                "type": "SIMULATION",
                "source": "Business Simulation Engine",
                "simulation_id": simulation.id,
                "scenario": chosen["title"],
                "projected_net_profit_delta": chosen_summary["net_profit_delta"],
                "projected_exit_margin_pct": chosen_summary["exit_gross_margin_pct"],
                "monte_carlo_p10": simulation.monte_carlo.get("p10"),
                "monte_carlo_p90": simulation.monte_carlo.get("p90"),
                "assumptions": chosen["assumptions"],
                "is_simulated": True,
            },
        ]
        decision = Decision(
            business_id=business.id,
            alert_id=None,
            issue=issue.get("summary") or issue.get("title", ""),
            title=chosen["title"],
            objective="Restore gross margin toward the 38% operating target without breaching the cash policy floor.",
            evidence=evidence,
            alternatives=alternatives,
            chosen={
                **chosen,
                "simulation_id": simulation.id,
                "expected_outcome": {
                    "net_profit_delta_12m": chosen_summary["net_profit_delta"],
                    "exit_gross_margin_pct": chosen_summary["exit_gross_margin_pct"],
                    "minimum_cash": chosen_summary["minimum_cash"],
                },
            },
            expected_financial_impact=chosen_summary["net_profit_delta"],
            confidence=chosen["confidence"],
            risk_level=chosen["risk_level"],
            reversibility=chosen["reversibility"],
            requires_approval=requires_approval,
            status="DRAFT",
            rationale=narrative.text,
            simulation_id=simulation.id,
        )
        session.add(decision)
        await session.flush()
        return decision

    async def revise(
        self,
        session: AsyncSession,
        decision: Decision,
        audit_reasons: list[dict[str, Any]],
        *,
        actor: str = "decision-making-agent",
    ) -> Decision:
        """Select the next-best alternative after a rejection (deterministic)."""
        chosen_key = (decision.chosen or {}).get("key")
        alternatives = sorted(
            decision.alternatives or [], key=lambda item: item.get("score", 0), reverse=True
        )
        remaining = [item for item in alternatives if item.get("key") != chosen_key]
        if not remaining:
            decision.status = "REJECTED"
            await session.flush()
            return decision
        new_choice = remaining[0]
        decision.title = new_choice["title"]
        decision.chosen = {**new_choice, "expected_outcome": {
            "net_profit_delta_12m": new_choice.get("expected_impact_12m"),
            "exit_gross_margin_pct": new_choice.get("exit_gross_margin_pct"),
            "exit_cash_balance": new_choice.get("exit_cash_balance"),
        }}
        decision.expected_financial_impact = float(new_choice.get("expected_impact_12m") or 0)
        decision.confidence = float(new_choice.get("confidence") or 0.5)
        decision.risk_level = new_choice.get("risk_level", "MEDIUM")
        decision.reversibility = new_choice.get("reversibility", "REVERSIBLE")
        decision.rationale = (
            f"Revised recommendation after independent audit. Selected '{new_choice['title']}' because the prior option was rejected. "
            "The revised option is ranked next by the deterministic scoring model; all projected figures remain simulations. "
            f"Audit reasons addressed: {'; '.join(item.get('message', '') for item in audit_reasons)[:800]}"
        )
        for item in decision.alternatives:
            item["selected"] = item.get("key") == new_choice.get("key")
        decision.status = "DRAFT"
        decision.updated_at = utcnow()
        await session.flush()
        return decision


decision_service = DecisionService()
