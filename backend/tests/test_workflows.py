"""End-to-end acceptance test for the Northwind margin decline scenario."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.domain.models import (
    ActionVerification,
    Alert,
    Approval,
    BusinessAction,
    BusinessRule,
    Decision,
    ExcelConversion,
    MetricSnapshot,
    Report,
    User,
    WorkflowRun,
)
from app.excel.service import excel_service
from app.services.approvals import approval_service
from app.workflows.runner import workflow_runner


@pytest.mark.timeout(240)
async def test_full_decision_and_excel_acceptance_scenario(business, demo_workbook_path):
    # ---- Daily business intelligence -------------------------------------
    async with session_scope() as session:
        daily = await workflow_runner.start(
            session, business=business, workflow="daily_bi", inputs={}, actor="pytest", trigger="TEST"
        )
        daily_id = daily.id
    await workflow_runner.wait(daily_id, timeout=180)
    async with session_scope() as session:
        daily = await session.get(WorkflowRun, daily_id)
        assert daily.status == "COMPLETED", daily.error
        snapshot = (await session.execute(select(MetricSnapshot).order_by(MetricSnapshot.as_of.desc()))).scalars().first()
        assert snapshot.payload["latest"]["gross_margin_pct"] < 35
        alerts = (await session.execute(select(Alert))).scalars().all()
        assert alerts
        assert any(alert.severity == "CRITICAL" for alert in alerts)
        reports = (await session.execute(select(Report).where(Report.report_type == "DAILY_SUMMARY"))).scalars().all()
        assert reports
        assert reports[0].files.get("pdf")
        assert Path(reports[0].files["pdf"]).exists()
        assert reports[0].content["ai_interpretation"]["provider"] == "deterministic"
        critical_alert_id = next(alert.id for alert in alerts if alert.severity == "CRITICAL")

    # ---- Decision generation, audit and human approval -------------------
    async with session_scope() as session:
        decision_run = await workflow_runner.start(
            session,
            business=business,
            workflow="decision_execution",
            inputs={"alert_id": critical_alert_id},
            actor="pytest",
            trigger="TEST",
        )
        decision_run_id = decision_run.id
    await workflow_runner.wait(decision_run_id, timeout=180)
    async with session_scope() as session:
        decision_run = await session.get(WorkflowRun, decision_run_id)
        assert decision_run.status == "WAITING_APPROVAL", decision_run.error
        decision = (await session.execute(select(Decision))).scalars().first()
        assert decision.expected_financial_impact > 0
        assert decision.simulation_id
        assert decision.alternatives
        assert decision.requires_approval
        approval = (
            await session.execute(select(Approval).where(Approval.decision_id == decision.id, Approval.status == "PENDING"))
        ).scalar_one()
        decision_id = decision.id
        approver = (await session.execute(select(User).where(User.role == "APPROVER"))).scalars().first()

    async with session_scope() as session:
        approval = await session.get(Approval, approval.id)
        await approval_service.decide(session, approval, approver, approved=True, comment="Accept with legal review condition.")
    await workflow_runner.resume(
        decision_run_id,
        {"approved": True, "actor": approver.email, "comment": "Accept with legal review condition."},
    )
    await workflow_runner.wait(decision_run_id, timeout=180)
    async with session_scope() as session:
        decision_run = await session.get(WorkflowRun, decision_run_id)
        assert decision_run.status == "COMPLETED", decision_run.error
        decision = await session.get(Decision, decision_id)
        assert decision.status == "VERIFIED"
        action = (
            await session.execute(select(BusinessAction).where(BusinessAction.decision_id == decision.id))
        ).scalars().first()
        assert action and action.status == "VERIFIED" and action.simulated is True
        verification = (
            await session.execute(select(ActionVerification).where(ActionVerification.action_id == action.id))
        ).scalars().first()
        assert verification and verification.status == "VERIFIED"
        assert verification.business_impact["status"] == "PENDING_OBSERVATION"
        refreshed_daily = (
            await session.execute(
                select(Report).where(Report.report_type == "DAILY_SUMMARY").order_by(Report.created_at.desc()).limit(1)
            )
        ).scalars().first()
        assert any(item["id"] == decision.id for item in refreshed_daily.content["decisions"])

    # ---- Excel conversion and approved activation ------------------------
    async with session_scope() as session:
        stored = await excel_service.save_upload(demo_workbook_path.read_bytes(), demo_workbook_path.name)
        conversion = await excel_service.create(session, business, stored, demo_workbook_path.name)
        conversion_id = conversion.id
        excel_run = await workflow_runner.start(
            session,
            business=business,
            workflow="excel_conversion",
            inputs={"conversion_id": conversion.id},
            actor="pytest",
            trigger="TEST",
        )
        excel_run_id = excel_run.id
    await workflow_runner.wait(excel_run_id, timeout=180)
    async with session_scope() as session:
        conversion = await session.get(ExcelConversion, conversion_id)
        assert conversion.status == "AWAITING_APPROVAL", conversion.error
        assert conversion.validation["passed"] is True
        assert conversion.validation["status"] == "VALIDATED"
        assert conversion.report_path and Path(conversion.report_path).exists()
        excel_run = await session.get(WorkflowRun, excel_run_id)
        assert excel_run.status == "WAITING_APPROVAL"

    await workflow_runner.resume(excel_run_id, {"approved": True, "actor": approver.email, "comment": "Validated."})
    await workflow_runner.wait(excel_run_id, timeout=120)
    async with session_scope() as session:
        conversion = await session.get(ExcelConversion, conversion_id)
        assert conversion.status == "ACTIVATED"
        rule = await session.get(BusinessRule, conversion.rule_id)
        assert rule and rule.status == "ACTIVE" and rule.source == "EXCEL"
        assert rule.excel_lineage["validation_summary"]["status"] == "VALIDATED"
        assert rule.tests
        excel_run = await session.get(WorkflowRun, excel_run_id)
        assert excel_run.status == "COMPLETED", excel_run.error


async def test_api_auth_rbac_and_overview():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/api/overview")
        assert unauthorized.status_code == 401
        login = await client.post(
            "/api/auth/login",
            json={"email": "cfo@northwind.demo", "password": "TwinDemo!2026"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        overview = await client.get("/api/overview", headers=headers)
        assert overview.status_code == 200
        body = overview.json()
        assert body["snapshot"]["latest"]["gross_margin_pct"] < 35
        assert body["business"]["is_demo"] is True
        assert len(body["agents"]) == 10
        decisions = await client.get("/api/decisions", headers=headers)
        assert decisions.status_code == 200
        rules = await client.get("/api/logic/rules", headers=headers)
        assert rules.status_code == 200
        assert any(rule["source"] == "EXCEL" for rule in rules.json())

        analyst_login = await client.post(
            "/api/auth/login",
            json={"email": "analyst@northwind.demo", "password": "TwinDemo!2026"},
        )
        analyst_headers = {"Authorization": f"Bearer {analyst_login.json()['access_token']}"}
        forbidden = await client.post(
            "/api/approvals/apr_missing/decide",
            headers=analyst_headers,
            json={"approved": True, "comment": "should fail"},
        )
        assert forbidden.status_code == 403
