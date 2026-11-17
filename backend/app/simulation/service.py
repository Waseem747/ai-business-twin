"""Simulation orchestration and persistence.

Simulations read an immutable snapshot and write only to simulation tables.
Production observations and metrics are never updated.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.domain.models import Business, MetricSnapshot, Scenario, Simulation
from app.simulation import model


class SimulationService:
    async def run(
        self,
        session: AsyncSession,
        business: Business,
        snapshot: MetricSnapshot,
        parameters: dict[str, Any],
        *,
        name: str = "Untitled scenario",
        description: str = "",
        created_by: str = "system",
        horizon_months: int = 12,
        with_monte_carlo: bool = True,
        persist: bool = True,
    ) -> tuple[Simulation, Scenario, dict[str, Any]]:
        baseline = {**snapshot.payload.get("latest", {})}
        baseline["channels"] = snapshot.payload.get("channels", [])
        baseline["discount_depth_pct"] = (
            (snapshot.payload.get("drivers") or {}).get("discount_depth_pct", {}) or {}
        ).get("value", 8.0)
        scenario_results = model.run_scenarios(baseline, parameters, horizon_months=horizon_months)
        sensitivity = model.sensitivity_analysis(baseline, parameters, horizon_months=horizon_months)
        monte_carlo = (
            model.monte_carlo(baseline, parameters, horizon_months=horizon_months)
            if with_monte_carlo
            else {}
        )
        backtest_result = model.backtest(snapshot.payload.get("periods", []))
        base = scenario_results["base"]
        constraints = base["summary"]["constraints"]
        confidence = 82.0
        quality = snapshot.payload.get("data_quality", {})
        confidence -= max(0.0, (100 - float(quality.get("completeness_pct", 100))) * 0.4)
        confidence -= 6 if quality.get("stale_sources") else 0
        confidence -= 5 if (snapshot.payload.get("lineage") or {}).get("simulated_demo_data") else 0
        confidence = max(20.0, min(92.0, confidence))

        results = {
            "scenario": {
                "summary": base["summary"],
                "monthly": base["monthly"],
                "baseline_monthly": base["baseline_monthly"],
                "constraints": constraints,
            },
            "best_case": {"summary": scenario_results["best_case"]["summary"]},
            "worst_case": {"summary": scenario_results["worst_case"]["summary"]},
            "alternatives": scenario_results["alternatives"],
            "assumptions_used": base["assumptions_used"],
            "confidence_pct": round(confidence, 1),
            "is_simulation": True,
            "production_state_modified": False,
            "model": base["model"],
        }
        assumptions = {
            "model_assumptions": base["assumptions_used"],
            "parameter_assumptions": parameters,
            "data_snapshot_as_of": snapshot.as_of.isoformat(),
            "baseline_period": snapshot.payload.get("latest", {}).get("label"),
            "limitations": [
                "Projection is a deterministic model, not an LLM forecast.",
                "Marketing response uses a diminishing-returns elasticity; a 20% spend increase does not imply 20% revenue growth.",
                "Actual execution timing, competitor response and macro conditions are not modelled.",
                "Backtest validates the baseline assumption only and is not a counterfactual.",
            ],
        }
        scenario = Scenario(
            business_id=business.id,
            name=name,
            description=description,
            parameters=parameters,
            created_by=created_by,
        )
        session.add(scenario)
        await session.flush()
        simulation = Simulation(
            business_id=business.id,
            scenario_id=scenario.id,
            name=name,
            status="COMPLETED",
            snapshot_id=snapshot.id,
            baseline=baseline,
            results=results,
            assumptions=assumptions,
            alternatives=scenario_results["alternatives"],
            monte_carlo=monte_carlo,
            sensitivity=sensitivity,
            backtest=backtest_result,
            simulated=True,
            created_by=created_by,
            finished_at=utcnow(),
        )
        if persist:
            session.add(simulation)
            await session.flush()
        return simulation, scenario, results

    async def get(self, session: AsyncSession, simulation_id: str, business_id: str) -> Simulation:
        simulation = await session.get(Simulation, simulation_id)
        if not simulation or simulation.business_id != business_id:
            raise ValueError("Simulation not found")
        return simulation

    async def list(self, session: AsyncSession, business_id: str, limit: int = 30) -> list[Simulation]:
        result = await session.execute(
            select(Simulation)
            .where(Simulation.business_id == business_id)
            .order_by(desc(Simulation.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def compare(self, session: AsyncSession, simulation_ids: list[str], business_id: str) -> dict[str, Any]:
        simulations = []
        for simulation_id in simulation_ids:
            simulation = await session.get(Simulation, simulation_id)
            if simulation and simulation.business_id == business_id and simulation.simulated:
                simulations.append(
                    {
                        "id": simulation.id,
                        "name": simulation.name,
                        "parameters": (simulation.assumptions or {}).get("parameter_assumptions", {}),
                        "summary": ((simulation.results or {}).get("scenario") or {}).get("summary", {}),
                        "monte_carlo": simulation.monte_carlo,
                    }
                )
        return {"simulations": simulations, "baseline_reference": simulations[0] if simulations else None}


simulation_service = SimulationService()
