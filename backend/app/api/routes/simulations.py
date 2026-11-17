"""Business simulation API. Simulations run in an isolated workflow and never touch production state."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from app.api.deps import BusinessDep, DBSession
from app.api.schemas import SimulationCompareRequest, SimulationRequest
from app.api.serializers import dt, simulation_out
from app.core.security import CurrentUser
from app.domain.models import MetricSnapshot, Simulation, WorkflowRun
from app.simulation.model import BASE_ASSUMPTIONS, DEFAULT_PARAMETERS
from app.simulation.service import simulation_service
from app.workflows.runner import workflow_runner

router = APIRouter(prefix="/api/simulations", tags=["Simulation"])


@router.get("/assumptions")
async def assumptions(user: CurrentUser) -> dict:
    return {
        "base_assumptions": BASE_ASSUMPTIONS,
        "default_parameters": DEFAULT_PARAMETERS,
        "parameters": [
            {"key": "price_change_pct", "label": "Price change", "unit": "%", "min": -20, "max": 20, "step": 0.5},
            {"key": "marketing_change_pct", "label": "Marketing spend change", "unit": "%", "min": -80, "max": 150, "step": 5},
            {"key": "cogs_change_pct", "label": "Landed COGS change", "unit": "%", "min": -20, "max": 20, "step": 0.5},
            {"key": "discount_change_pp", "label": "Discount depth change", "unit": "pp", "min": -15, "max": 15, "step": 0.5},
            {"key": "headcount_change", "label": "Headcount change", "unit": "people", "min": -50, "max": 50, "step": 1},
            {"key": "inventory_change_pct", "label": "Inventory change", "unit": "%", "min": -50, "max": 50, "step": 1},
            {"key": "revenue_impact_pct", "label": "New revenue initiative", "unit": "%", "min": -30, "max": 50, "step": 1},
            {"key": "other_opex_change_pct", "label": "Other opex change", "unit": "%", "min": -30, "max": 30, "step": 1},
            {"key": "one_off_cost", "label": "One-off implementation cost", "unit": "USD", "min": 0, "max": 5000000, "step": 1000},
        ],
        "notice": "Model assumptions are explicit and configurable. A marketing increase is not assumed to produce proportional revenue growth.",
    }


@router.post("")
async def run_simulation(payload: SimulationRequest, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    if user.role == "VIEWER":
        raise HTTPException(status_code=403, detail="Viewers cannot run simulations")
    if payload.snapshot_id:
        snapshot = await db.get(MetricSnapshot, payload.snapshot_id)
        if not snapshot or snapshot.business_id != business.id:
            raise HTTPException(status_code=404, detail="Snapshot not found")
    run = await workflow_runner.start(
        db,
        business=business,
        workflow="simulation",
        inputs={
            "scenario_parameters": payload.parameters,
            "scenario_name": payload.name,
            "scenario_description": payload.description,
            "snapshot_id": payload.snapshot_id,
            "with_monte_carlo": payload.with_monte_carlo,
        },
        actor=user.email,
        trigger="MANUAL",
    )
    await db.commit()
    try:
        await workflow_runner.wait(run.id, timeout=120)
    except Exception:  # noqa: BLE001
        pass
    await db.refresh(run)
    if run.status == "FAILED":
        raise HTTPException(status_code=422, detail=run.error or "Simulation failed")
    simulation_id = (run.state or {}).get("simulation_id")
    simulation = await db.get(Simulation, simulation_id) if simulation_id else None
    if not simulation:
        raise HTTPException(status_code=500, detail="Simulation completed without a persisted result")
    return {"simulation": simulation_out(simulation), "workflow": {"id": run.id, "status": run.status}}


@router.get("")
async def list_simulations(business: BusinessDep, db: DBSession, user: CurrentUser, limit: int = 30) -> list[dict]:
    rows = await simulation_service.list(db, business.id, min(limit, 100))
    return [simulation_out(row) for row in rows]


@router.get("/{simulation_id}")
async def get_simulation(simulation_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    simulation = await db.get(Simulation, simulation_id)
    if not simulation or simulation.business_id != business.id:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return simulation_out(simulation)


@router.post("/compare")
async def compare(payload: SimulationCompareRequest, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    try:
        result = await simulation_service.compare(db, payload.simulation_ids, business.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result
