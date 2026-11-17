"""Typed LangGraph workflow state.

Only JSON-serialisable values are placed in graph state so checkpoints are
durable and portable.  Rich domain objects live in PostgreSQL/SQLite tables.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class WorkflowState(TypedDict, total=False):
    run_id: str
    business_id: str
    workflow: str
    actor: str
    trigger: str
    status: str
    summary: str

    ingestion_run_ids: list[str]
    ingestion_summary: dict[str, Any]
    validation_summary: dict[str, Any]
    transformation_summary: dict[str, Any]
    logic_summary: dict[str, Any]
    snapshot_id: str
    findings: list[dict[str, Any]]
    intelligence_summary: dict[str, Any]
    issue: dict[str, Any]
    alert_id: str
    alert_ids: list[str]
    report_ids: list[str]
    notification_ids: list[str]

    decision_id: str
    audit: dict[str, Any]
    audit_verdict: str
    revision_count: int
    approval_id: str
    approval_result: dict[str, Any]
    action_id: str
    action_summary: dict[str, Any]
    verification: dict[str, Any]
    business_impact: dict[str, Any]

    scenario_parameters: dict[str, Any]
    scenario_name: str
    scenario_description: str
    simulation_id: str
    simulation_summary: dict[str, Any]
    simulation_comparison: dict[str, Any]
    with_monte_carlo: bool

    conversion_id: str
    conversion_result: dict[str, Any]

    completed_nodes: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
