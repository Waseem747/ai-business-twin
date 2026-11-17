"""Deterministic demo tenant for the retail MVP.

All operational values are clearly labelled DEMO / SIMULATED.  The data path is
real: connectors → ingestion lineage → validation → transformations → rules →
snapshot.  No external API is represented as live.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import seed_agents
from app.config import settings
from app.core.security import hash_password
from app.core.utils import utcnow
from app.domain.models import (
    Business,
    BusinessUnit,
    Customer,
    DataSource,
    Department,
    Employee,
    Expense,
    IngestionRun,
    InventoryItem,
    Invoice,
    KnowledgeDocument,
    Observation,
    Product,
    Project,
    Revenue,
    Service,
    Supplier,
    Tenant,
    Transaction,
    User,
    Budget,
)
from app.logic.registry import rule_registry
from app.services.ingestion import ingestion_service
from app.services.transformation import transformation_service
from app.services.twin_state import ensure_snapshot

DEMO_PASSWORD = "TwinDemo!2026"


async def _ensure_users(session: AsyncSession, tenant: Tenant) -> list[User]:
    users = [
        ("admin@northwind.demo", "Maya Chen", "ADMIN", "Platform administrator"),
        ("cfo@northwind.demo", "Daniel Okafor", "APPROVER", "Chief Financial Officer"),
        ("analyst@northwind.demo", "Priya Raman", "ANALYST", "Senior business analyst"),
        ("viewer@northwind.demo", "Tom Alvarez", "VIEWER", "Board observer"),
    ]
    created = []
    for email, name, role, title in users:
        existing = (
            await session.execute(select(User).where(User.tenant_id == tenant.id, User.email == email))
        ).scalar_one_or_none()
        if existing:
            created.append(existing)
            continue
        user = User(
            tenant_id=tenant.id,
            email=email,
            full_name=name,
            password_hash=hash_password(DEMO_PASSWORD),
            role=role,
            title=title,
        )
        session.add(user)
        created.append(user)
    await session.flush()
    return created


async def _ensure_structure(session: AsyncSession, business: Business) -> None:
    if not (
        await session.execute(select(func.count()).select_from(BusinessUnit).where(BusinessUnit.business_id == business.id))
    ).scalar_one():
        session.add_all(
            [
                BusinessUnit(business_id=business.id, name="Retail Stores", code="STORES", kind="channel", manager="Elena Rossi", headcount=84),
                BusinessUnit(business_id=business.id, name="E-commerce", code="ECOM", kind="channel", manager="Samir Patel", headcount=32),
                BusinessUnit(business_id=business.id, name="Wholesale", code="WHOLESALE", kind="channel", manager="Grace Liu", headcount=18),
            ]
        )
    if not (
        await session.execute(select(func.count()).select_from(Department).where(Department.business_id == business.id))
    ).scalar_one():
        session.add_all(
            [
                Department(business_id=business.id, name="Finance", code="FIN", owner="Daniel Okafor", headcount=12),
                Department(business_id=business.id, name="Merchandising", code="MERCH", owner="Elena Rossi", headcount=24),
                Department(business_id=business.id, name="Marketing", code="MKT", owner="Samir Patel", headcount=16),
                Department(business_id=business.id, name="Operations", code="OPS", owner="Grace Liu", headcount=52),
            ]
        )
    if not (
        await session.execute(select(func.count()).select_from(Employee).where(Employee.business_id == business.id))
    ).scalar_one():
        session.add_all(
            [
                Employee(business_id=business.id, employee_no="NW-001", name="Maya Chen", role="Platform administrator", annual_cost=185000),
                Employee(business_id=business.id, employee_no="NW-002", name="Daniel Okafor", role="Chief Financial Officer", annual_cost=240000),
                Employee(business_id=business.id, employee_no="NW-003", name="Priya Raman", role="Senior business analyst", annual_cost=132000),
                Employee(business_id=business.id, employee_no="NW-004", name="Elena Rossi", role="Merchandising Director", annual_cost=198000),
                Employee(business_id=business.id, employee_no="NW-005", name="Samir Patel", role="Digital Director", annual_cost=186000),
                Employee(business_id=business.id, employee_no="NW-006", name="Grace Liu", role="Operations Director", annual_cost=192000),
            ]
        )
    if not (
        await session.execute(select(func.count()).select_from(Customer).where(Customer.business_id == business.id))
    ).scalar_one():
        session.add_all(
            [
                Customer(business_id=business.id, customer_no="C-1001", name="Harbor Home Studio", segment="Mid-market", region="West", lifetime_revenue=428000, churn_risk=0.22),
                Customer(business_id=business.id, customer_no="C-1002", name="Cedar & Pine LLP", segment="Enterprise", region="Midwest", lifetime_revenue=612000, churn_risk=0.12),
                Customer(business_id=business.id, customer_no="C-1003", name="Willow Interiors", segment="SMB", region="East", lifetime_revenue=97000, churn_risk=0.38),
                Customer(business_id=business.id, customer_no="C-1004", name="Urban Nest Collective", segment="Mid-market", region="South", lifetime_revenue=286000, churn_risk=0.27),
                Customer(business_id=business.id, customer_no="C-1005", name="Northline Contracting", segment="Enterprise", region="West", lifetime_revenue=744000, churn_risk=0.09),
            ]
        )
    if not (
        await session.execute(select(func.count()).select_from(Supplier).where(Supplier.business_id == business.id))
    ).scalar_one():
        session.add_all(
            [
                Supplier(
                    business_id=business.id,
                    name="Atlas Home Goods",
                    category="Core homeware",
                    lead_time_days=21,
                    on_time_rate=0.94,
                    cost_escalation_pct=6.5,
                    risk_level="MEDIUM",
                ),
                Supplier(business_id=business.id, name="Coastal Supply Co.", category="Core homeware", lead_time_days=14, on_time_rate=0.97, cost_escalation_pct=2.1, risk_level="LOW"),
                Supplier(business_id=business.id, name="Meridian Textiles", category="Soft furnishings", lead_time_days=28, on_time_rate=0.89, cost_escalation_pct=4.4, risk_level="HIGH"),
            ]
        )
    if not (
        await session.execute(select(func.count()).select_from(Product).where(Product.business_id == business.id))
    ).scalar_one():
        session.add_all(
            [
                Product(business_id=business.id, sku="NW-CH-100", name="Oakline dining chair", category="Furniture", unit_cost=84, list_price=169),
                Product(business_id=business.id, sku="NW-LT-220", name="Lumen arc floor lamp", category="Lighting", unit_cost=46, list_price=119),
                Product(business_id=business.id, sku="NW-TX-310", name="Cloudweave throw", category="Textiles", unit_cost=21, list_price=59),
                Product(business_id=business.id, sku="NW-ST-400", name="Forma storage unit", category="Storage", unit_cost=96, list_price=199),
                Product(business_id=business.id, sku="NW-DC-510", name="Ridge ceramic vase", category="Decor", unit_cost=12, list_price=39),
                Product(business_id=business.id, sku="NW-BD-620", name="Haven linen duvet", category="Bedding", unit_cost=58, list_price=139),
            ]
        )
    await session.flush()
    products = (
        await session.execute(select(Product).where(Product.business_id == business.id))
    ).scalars().all()
    if products and not (
        await session.execute(select(func.count()).select_from(InventoryItem).where(InventoryItem.business_id == business.id))
    ).scalar_one():
        session.add_all(
            [
                InventoryItem(business_id=business.id, product_id=products[0].id, on_hand=820, reorder_point=600, days_of_cover=42, valuation=68880, location="DC-1"),
                InventoryItem(business_id=business.id, product_id=products[1].id, on_hand=310, reorder_point=420, days_of_cover=22, valuation=14260, location="DC-1"),
                InventoryItem(business_id=business.id, product_id=products[2].id, on_hand=1840, reorder_point=900, days_of_cover=66, valuation=38640, location="DC-2"),
                InventoryItem(business_id=business.id, product_id=products[3].id, on_hand=460, reorder_point=380, days_of_cover=35, valuation=44160, location="DC-2"),
            ]
        )
    if not (
        await session.execute(select(func.count()).select_from(Project).where(Project.business_id == business.id))
    ).scalar_one():
        session.add_all(
            [
                Project(business_id=business.id, code="PRJ-MARGIN", name="Gross margin recovery programme", status="ACTIVE", budget=180000, spent=62000, owner="Daniel Okafor"),
                Project(business_id=business.id, code="PRJ-SUPPLY", name="Dual-sourcing qualification", status="ACTIVE", budget=90000, spent=18000, owner="Grace Liu"),
            ]
        )
    await session.flush()


async def _ensure_budgets(session: AsyncSession, business: Business) -> None:
    if (
        await session.execute(select(func.count()).select_from(Budget).where(Budget.business_id == business.id))
    ).scalar_one():
        return
    anchor = utcnow().replace(day=1)
    for month_offset in range(3):
        year = anchor.year
        month = anchor.month - month_offset
        while month <= 0:
            month += 12
            year -= 1
        period = f"{year:04d}-{month:02d}"
        session.add_all(
            [
                Budget(business_id=business.id, department="Marketing", period=period, category="marketing", budgeted=62000, actual=64600 if month_offset == 0 else 63500),
                Budget(business_id=business.id, department="Operations", period=period, category="payroll", budgeted=62000, actual=63100 if month_offset == 0 else 62200),
                Budget(business_id=business.id, department="Finance", period=period, category="other_opex", budgeted=17000, actual=18500 if month_offset == 0 else 17600),
            ]
        )
    await session.flush()


def _ensure_demo_analytics_db() -> Path:
    path = Path(__file__).resolve().parents[2] / "data" / "demo" / "analytics.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_metrics (
                period TEXT NOT NULL,
                channel TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT NOT NULL,
                category TEXT NOT NULL
            )
            """
        )
        count = connection.execute("SELECT COUNT(*) FROM campaign_metrics").fetchone()[0]
        if not count:
            anchor = utcnow().replace(day=1)
            rows = []
            for offset in range(3, 0, -1):
                year = anchor.year
                month = anchor.month - offset
                while month <= 0:
                    month += 12
                    year -= 1
                period = f"{year:04d}-{month:02d}"
                rows.extend(
                    [
                        (period, "Paid search", "paid_search_spend", 9800.0 + offset * 240, "USD", "acquisition"),
                        (period, "Paid search", "paid_search_revenue", 47200.0 + offset * 910, "USD", "acquisition"),
                        (period, "Email", "email_revenue", 18400.0 + offset * 320, "USD", "retention"),
                    ]
                )
            connection.executemany(
                "INSERT INTO campaign_metrics (period, channel, metric, value, unit, category) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.commit()
    finally:
        connection.close()
    return path


async def _ensure_commercial_activity(session: AsyncSession, business: Business) -> None:
    existing = (
        await session.execute(select(func.count()).select_from(Transaction).where(Transaction.business_id == business.id))
    ).scalar_one()
    if existing:
        return
    customers = (
        await session.execute(select(Customer).where(Customer.business_id == business.id).limit(3))
    ).scalars().all()
    suppliers = (
        await session.execute(select(Supplier).where(Supplier.business_id == business.id).limit(2))
    ).scalars().all()
    now = utcnow()
    session.add_all(
        [
            Service(business_id=business.id, name="Interior design consultation", category="services", list_price=250),
            Service(business_id=business.id, name="Delivery and assembly", category="services", list_price=95),
        ]
    )
    for index, amount in enumerate([8400.0, 12600.0, 3150.0, 9800.0, 4720.0]):
        session.add(
            Transaction(
                business_id=business.id,
                occurred_at=now - timedelta(days=index + 1),
                kind="SALE",
                channel=["Online", "Stores", "Wholesale"][index % 3],
                amount=amount,
                external_ref=f"DEMO-TXN-{1000 + index}",
                description="Fictional demo transaction detail record",
            )
        )
    for index, amount in enumerate([18400.0, 9200.0, 41500.0]):
        session.add(
            Invoice(
                business_id=business.id,
                customer_id=customers[index % len(customers)].id if customers else None,
                invoice_no=f"NW-INV-{2400 + index}",
                issued_at=now - timedelta(days=index * 5 + 2),
                due_at=now + timedelta(days=28 - index * 5),
                amount=amount,
                tax=round(amount * 0.08, 2),
                status=["OPEN", "OPEN", "PAID"][index],
            )
        )
    for index, (category, amount) in enumerate(
        [("marketing", 12400.0), ("logistics", 8600.0), ("software", 3100.0), ("facilities", 7200.0)]
    ):
        session.add(
            Expense(
                business_id=business.id,
                supplier_id=suppliers[index % len(suppliers)].id if suppliers else None,
                incurred_at=now - timedelta(days=index * 3 + 1),
                category=category,
                amount=amount,
                reference=f"DEMO-EXP-{510 + index}",
            )
        )
    for index in range(3):
        month_start = (now.replace(day=1) - timedelta(days=index * 30)).replace(day=1)
        session.add(
            Revenue(
                business_id=business.id,
                period_start=month_start,
                period_end=month_start + timedelta(days=27),
                channel="All channels",
                amount=[559788.95, 548000.0, 536000.0][index],
                recognized_at=month_start + timedelta(days=28),
                status="RECOGNIZED",
            )
        )
    await session.flush()


async def _ensure_knowledge(session: AsyncSession, business: Business) -> None:
    existing = (
        await session.execute(select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.business_id == business.id))
    ).scalar_one()
    if existing:
        return
    documents = [
        (
            "policies",
            "Decision approval policy",
            "Any action with a projected financial impact above USD 5,000, any supplier contract change, any price change, or any irreversible action requires named human approval by an APPROVER or ADMIN. The Decision Auditor cannot execute actions.",
        ),
        (
            "policies",
            "Treasury cash policy",
            "Projected operating cash must remain above USD 250,000 on a 12-month view. A breach requires CFO approval and a documented mitigation plan.",
        ),
        (
            "policies",
            "Procurement approval policy",
            "Supplier contract reviews require legal review, a named commercial owner and a dual-sourcing assessment before commitment.",
        ),
        (
            "policies",
            "Data freshness policy",
            "Sources older than 48 hours are stale. Missing values are never imputed as zero. Decisions based on stale or incomplete data require human review.",
        ),
        (
            "playbooks",
            "Margin recovery playbook",
            "Sequence: verify landed cost changes; quantify channel mix and discount impact; evaluate supplier renegotiation, discount discipline and selective pricing; simulate cash and margin; obtain independent audit and human approval; measure post-action outcomes.",
        ),
    ]
    for collection, title, content in documents:
        session.add(
            KnowledgeDocument(
                business_id=business.id,
                collection=collection,
                title=title,
                content=content,
                meta={"demo": True, "approved": True},
            )
        )
    await session.flush()


async def ensure_demo_environment(session: AsyncSession) -> tuple[Tenant, Business]:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.slug == "northwind-demo"))
    ).scalar_one_or_none()
    if not tenant:
        tenant = Tenant(name="Northwind Demo Group", slug="northwind-demo", plan="enterprise")
        session.add(tenant)
        await session.flush()
    await _ensure_users(session, tenant)
    business = (
        await session.execute(
            select(Business).where(Business.tenant_id == tenant.id, Business.name == "Northwind Retail Co.")
        )
    ).scalar_one_or_none()
    if not business:
        business = Business(
            tenant_id=tenant.id,
            name="Northwind Retail Co.",
            industry="Homeware retail",
            currency="USD",
            description=(
                "Fictional omnichannel homeware retailer used for the AI Business Twin MVP demonstration. "
                "POS and ERP feeds are simulated and labelled; all calculations follow the real platform pipeline."
            ),
            is_demo=True,
        )
        session.add(business)
        await session.flush()
    await _ensure_structure(session, business)
    await _ensure_budgets(session, business)
    await _ensure_commercial_activity(session, business)
    await _ensure_knowledge(session, business)
    await transformation_service.seed(session, business.id)
    await rule_registry.seed(session, business.id)
    await seed_agents(session, business.id)

    sources = (
        await session.execute(select(DataSource).where(DataSource.business_id == business.id))
    ).scalars().all()
    if not sources:
        pos = DataSource(
            business_id=business.id,
            name="Northwind POS (simulated)",
            kind="SIMULATED_POS",
            system="northwind_pos",
            status="CONNECTED",
            simulated=True,
            config={"dataset": "northwind-demo-pos-v1", "note": "Deterministic demo POS export; no external API."},
        )
        erp = DataSource(
            business_id=business.id,
            name="Northwind ERP (simulated)",
            kind="SIMULATED_ERP",
            system="northwind_erp",
            status="CONNECTED",
            simulated=True,
            config={"dataset": "northwind-demo-erp-v1", "note": "Deterministic demo ERP export; no external API."},
        )
        session.add_all([pos, erp])
        await session.flush()
        sources = [pos, erp]

    sql_added = False
    if not any(source.kind == "SQL_DATABASE" for source in sources):
        analytics_path = _ensure_demo_analytics_db()
        sql_source = DataSource(
            business_id=business.id,
            name="Marketing Warehouse (SQL demo)",
            kind="SQL_DATABASE",
            system="demo_sqlite",
            status="CONNECTED",
            simulated=True,
            config={
                "demo": True,
                "connection_url": f"sqlite+aiosqlite:///{analytics_path.as_posix()}",
                "query": "SELECT period, channel, metric, value, unit, category FROM campaign_metrics ORDER BY period, metric",
                "max_rows": 500,
                "default_entity": "marketing",
                "mapping": {
                    "entity": "",
                    "metric": "metric",
                    "period": "period",
                    "value": "value",
                    "channel": "channel",
                    "category": "category",
                    "unit": "unit",
                },
                "note": "Demo campaign data read through the real read-only SQL connector; not a live external database.",
            },
        )
        session.add(sql_source)
        await session.flush()
        sources.append(sql_source)
        sql_added = True

    observation_count = (
        await session.execute(select(func.count()).select_from(Observation).where(Observation.business_id == business.id))
    ).scalar_one()
    if observation_count == 0:
        for source in sources:
            await ingestion_service.sync_source(session, source, trigger="BOOTSTRAP", actor="system")
        await transformation_service.apply_active(session, business.id)
    elif sql_added:
        await ingestion_service.sync_source(session, sql_source, trigger="BOOTSTRAP", actor="system")
        latest_sql_run = await ingestion_service.latest_ingestion(session, business.id, sql_source.id)
        await transformation_service.apply_active(
            session, business.id, latest_sql_run.id if latest_sql_run else None
        )
    await ensure_snapshot(session, business, max_age_minutes=180)
    await session.flush()
    return tenant, business


async def bootstrap_demo_workflows() -> dict[str, Any]:
    """Run the demo workflows once after the core seed. Imported lazily to avoid cycles."""
    from app.agents.workers import bi_agent
    from app.db import session_scope
    from app.domain.models import Alert, Decision, WorkflowRun
    from app.excel.service import excel_service
    from app.workflows.runner import workflow_runner

    result: dict[str, Any] = {}
    async with session_scope() as session:
        business = (
            await session.execute(select(Business).where(Business.is_demo.is_(True)))
        ).scalars().first()
        if not business:
            return {"status": "no_demo_business"}
        daily_runs = (
            await session.execute(
                select(func.count()).select_from(WorkflowRun).where(
                    WorkflowRun.business_id == business.id, WorkflowRun.workflow == "daily_bi"
                )
            )
        ).scalar_one()
        if not daily_runs:
            run = await workflow_runner.start(
                session,
                business=business,
                workflow="daily_bi",
                inputs={},
                actor="scheduler",
                trigger="BOOTSTRAP",
            )
            await session.flush()
            run_id = run.id
        else:
            run_id = None
    if run_id:
        try:
            await workflow_runner.wait(run_id, timeout=180)
        except Exception:  # noqa: BLE001
            pass
        result["daily_run_id"] = run_id

    async with session_scope() as session:
        business = (
            await session.execute(select(Business).where(Business.is_demo.is_(True)))
        ).scalars().first()
        decision_runs = (
            await session.execute(
                select(func.count()).select_from(WorkflowRun).where(
                    WorkflowRun.business_id == business.id, WorkflowRun.workflow == "decision_execution"
                )
            )
        ).scalar_one()
        if not decision_runs:
            alerts = (
                await session.execute(
                    select(Alert).where(Alert.business_id == business.id, Alert.status != "RESOLVED")
                )
            ).scalars().all()
            severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
            alerts = sorted(alerts, key=lambda item: severity_rank.get(item.severity, 0), reverse=True)
            alert = alerts[0] if alerts else None
            if alert:
                run = await workflow_runner.start(
                    session,
                    business=business,
                    workflow="decision_execution",
                    inputs={"alert_id": alert.id},
                    actor="monitoring-service",
                    trigger="ALERT",
                )
                await session.flush()
                run_id = run.id
            else:
                run_id = None
        else:
            run_id = None
    if run_id:
        try:
            await workflow_runner.wait(run_id, timeout=180)
        except Exception:  # noqa: BLE001
            pass
        result["decision_run_id"] = run_id

    async with session_scope() as session:
        business = (
            await session.execute(select(Business).where(Business.is_demo.is_(True)))
        ).scalars().first()
        existing_conversion = (
            await session.execute(select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.business_id == business.id, WorkflowRun.workflow == "excel_conversion"
            ))
        ).scalar_one()
        if not existing_conversion:
            path = Path(__file__).resolve().parents[2] / "data" / "demo" / "Northwind_Margin_Model.xlsx"
            if path.exists():
                content = path.read_bytes()
                stored = await excel_service.save_upload(content, path.name)
                conversion = await excel_service.create(session, business, stored, path.name)
                run = await workflow_runner.start(
                    session,
                    business=business,
                    workflow="excel_conversion",
                    inputs={"conversion_id": conversion.id},
                    actor="system",
                    trigger="BOOTSTRAP",
                )
                await session.flush()
                run_id = run.id
            else:
                run_id = None
        else:
            run_id = None
    if run_id:
        try:
            await workflow_runner.wait(run_id, timeout=180)
        except Exception:  # noqa: BLE001
            pass
        result["excel_run_id"] = run_id
    return result
