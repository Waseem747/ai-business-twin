"""Persistent digital-twin domain model.

Category separation is explicit: observed actuals, calculated metrics,
AI interpretations, decisions, simulations and executed actions live in
different tables and are never merged into a single undifferentiated record.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.utils import new_id, utcnow
from app.domain.types import UTCDateTime


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[Any] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


def pk(prefix: str) -> Mapped[str]:
    return mapped_column(String(64), primary_key=True, default=lambda: new_id(prefix))


# ---------------------------------------------------------------------------
# Tenant, identity, organisation
# ---------------------------------------------------------------------------
class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    id: Mapped[str] = pk("ten")
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    plan: Mapped[str] = mapped_column(String(40), default="enterprise")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = pk("usr")
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="VIEWER")
    title: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)


class Business(Base, TimestampMixin):
    __tablename__ = "businesses"
    id: Mapped[str] = pk("biz")
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(120), default="Retail")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class BusinessUnit(Base, TimestampMixin):
    __tablename__ = "business_units"
    id: Mapped[str] = pk("bu")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    code: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(60), default="division")
    manager: Mapped[str] = mapped_column(String(160), default="")
    headcount: Mapped[int] = mapped_column(Integer, default=0)


class Department(Base, TimestampMixin):
    __tablename__ = "departments"
    id: Mapped[str] = pk("dep")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    code: Mapped[str] = mapped_column(String(40))
    owner: Mapped[str] = mapped_column(String(160), default="")
    headcount: Mapped[int] = mapped_column(Integer, default=0)


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"
    id: Mapped[str] = pk("emp")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    employee_no: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(120), default="")
    annual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    id: Mapped[str] = pk("cus")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    customer_no: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    segment: Mapped[str] = mapped_column(String(60), default="SMB")
    region: Mapped[str] = mapped_column(String(80), default="")
    first_purchase_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    lifetime_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    churn_risk: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"
    id: Mapped[str] = pk("sup")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), default="")
    lead_time_days: Mapped[int] = mapped_column(Integer, default=14)
    on_time_rate: Mapped[float] = mapped_column(Float, default=1.0)
    cost_escalation_pct: Mapped[float] = mapped_column(Float, default=0.0)
    contract_until: Mapped[Any | None] = mapped_column(UTCDateTime())
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    id: Mapped[str] = pk("prd")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    sku: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80))
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    list_price: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryItem(Base, TimestampMixin):
    __tablename__ = "inventory_items"
    id: Mapped[str] = pk("inv")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer, default=0)
    days_of_cover: Mapped[float] = mapped_column(Float, default=0.0)
    valuation: Mapped[float] = mapped_column(Float, default=0.0)
    location: Mapped[str] = mapped_column(String(80), default="DC-1")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    id: Mapped[str] = pk("prj")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    budget: Mapped[float] = mapped_column(Float, default=0.0)
    spent: Mapped[float] = mapped_column(Float, default=0.0)
    owner: Mapped[str] = mapped_column(String(160), default="")


class Service(Base, TimestampMixin):
    __tablename__ = "services"
    id: Mapped[str] = pk("svc")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), default="")
    list_price: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Transaction(Base, TimestampMixin):
    """Operational transaction detail. Aggregated observations remain the twin input."""
    __tablename__ = "transactions"
    id: Mapped[str] = pk("txn")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    occurred_at: Mapped[Any] = mapped_column(UTCDateTime(), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="SALE")
    channel: Mapped[str] = mapped_column(String(80), default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    external_ref: Mapped[str] = mapped_column(String(120), default="")
    data_source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id"))
    description: Mapped[str] = mapped_column(Text, default="")


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    id: Mapped[str] = pk("invc")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"))
    invoice_no: Mapped[str] = mapped_column(String(60))
    issued_at: Mapped[Any] = mapped_column(UTCDateTime(), index=True)
    due_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    tax: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="OPEN")


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    id: Mapped[str] = pk("expn")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"))
    incurred_at: Mapped[Any] = mapped_column(UTCDateTime(), index=True)
    category: Mapped[str] = mapped_column(String(80), default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="RECORDED")
    reference: Mapped[str] = mapped_column(String(120), default="")


class Revenue(Base, TimestampMixin):
    __tablename__ = "revenue_records"
    id: Mapped[str] = pk("rev")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    period_start: Mapped[Any] = mapped_column(UTCDateTime(), index=True)
    period_end: Mapped[Any] = mapped_column(UTCDateTime())
    channel: Mapped[str] = mapped_column(String(80), default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    recognized_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(30), default="RECOGNIZED")


# ---------------------------------------------------------------------------
# Data acquisition / transformation
# ---------------------------------------------------------------------------
class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"
    id: Mapped[str] = pk("src")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(40))  # REST / GRAPHQL / CSV / EXCEL / DATABASE / SIMULATED
    system: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(30), default="CONNECTED")
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sync_cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_sync_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    freshness_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    records_total: Mapped[int] = mapped_column(Integer, default=0)


class Credential(Base, TimestampMixin):
    __tablename__ = "credentials"
    id: Mapped[str] = pk("cred")
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    ciphertext: Mapped[str] = mapped_column(Text)
    nonce: Mapped[str] = mapped_column(String(120))
    key_hint: Mapped[str] = mapped_column(String(20), default="••••")
    rotated_at: Mapped[Any | None] = mapped_column(UTCDateTime())


class IngestionRun(Base, TimestampMixin):
    __tablename__ = "ingestion_runs"
    id: Mapped[str] = pk("ing")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(30), default="MANUAL")
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    started_at: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_blocked: Mapped[int] = mapped_column(Integer, default=0)
    freshness_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    schema_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_ref: Mapped[str] = mapped_column(String(400), default="")
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Observation(Base, TimestampMixin):
    """Validated, normalised observed fact. Immutable by convention."""
    __tablename__ = "observations"
    id: Mapped[str] = pk("obs")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    entity: Mapped[str] = mapped_column(String(60))  # revenue/cogs/expense/inventory/...
    period_start: Mapped[Any | None] = mapped_column(UTCDateTime(), index=True)
    period_end: Mapped[Any | None] = mapped_column(UTCDateTime(), index=True)
    channel: Mapped[str] = mapped_column(String(80), default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    metric: Mapped[str] = mapped_column(String(100))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40), default="USD")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    recorded_at: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow)
    __table_args__ = (Index("ix_obs_biz_period_metric", "business_id", "period_start", "metric"),)


class Transformation(Base, TimestampMixin):
    __tablename__ = "transformations"
    id: Mapped[str] = pk("trf")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    source_field: Mapped[str] = mapped_column(String(160), default="")
    target_field: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(40), default="DETERMINISTIC")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer, default=1)
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class TransformationRun(Base, TimestampMixin):
    __tablename__ = "transformation_runs"
    id: Mapped[str] = pk("trun")
    transformation_id: Mapped[str] = mapped_column(ForeignKey("transformations.id"), index=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    status: Mapped[str] = mapped_column(String(30), default="SUCCEEDED")
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Business logic registry
# ---------------------------------------------------------------------------
class BusinessRule(Base, TimestampMixin):
    __tablename__ = "business_rules"
    id: Mapped[str] = pk("rule")
    business_id: Mapped[str | None] = mapped_column(ForeignKey("businesses.id"), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="general")
    source: Mapped[str] = mapped_column(String(30), default="PYTHON")  # PYTHON/FORMULA/SQL/EXCEL
    code: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    execution_frequency: Mapped[str] = mapped_column(String(40), default="DAILY")
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    approved_by: Mapped[str | None] = mapped_column(String(160))
    approved_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    excel_lineage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("business_id", "key", "version", name="uq_rule_version"),)


class RuleVersion(Base, TimestampMixin):
    __tablename__ = "rule_versions"
    id: Mapped[str] = pk("rv")
    rule_id: Mapped[str] = mapped_column(ForeignKey("business_rules.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(Text)
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    changed_by: Mapped[str] = mapped_column(String(160), default="system")
    changelog: Mapped[str] = mapped_column(Text, default="")


class RuleExecution(Base, TimestampMixin):
    __tablename__ = "rule_executions"
    id: Mapped[str] = pk("rex")
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("business_rules.id"), index=True)
    rule_key: Mapped[str] = mapped_column(String(120), index=True)
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    business_id: Mapped[str | None] = mapped_column(ForeignKey("businesses.id"), index=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="SUCCEEDED")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    trace: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sandboxed: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# Digital twin snapshots & metrics
# ---------------------------------------------------------------------------
class MetricSnapshot(Base, TimestampMixin):
    __tablename__ = "metric_snapshots"
    id: Mapped[str] = pk("snap")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    as_of: Mapped[Any] = mapped_column(UTCDateTime(), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(30), default="ACTUAL")
    health_score: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(80), default="system")


class BusinessMetric(Base, TimestampMixin):
    __tablename__ = "business_metrics"
    id: Mapped[str] = pk("met")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("metric_snapshots.id"), index=True)
    key: Mapped[str] = mapped_column(String(100), index=True)
    label: Mapped[str] = mapped_column(String(160))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(30), default="USD")
    category: Mapped[str] = mapped_column(String(30), default="CALCULATED")
    period_start: Mapped[Any | None] = mapped_column(UTCDateTime())
    period_end: Mapped[Any | None] = mapped_column(UTCDateTime())
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"
    id: Mapped[str] = pk("bud")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    department: Mapped[str] = mapped_column(String(120))
    period: Mapped[str] = mapped_column(String(20))  # YYYY-MM
    category: Mapped[str] = mapped_column(String(80))
    budgeted: Mapped[float] = mapped_column(Float)
    actual: Mapped[float] = mapped_column(Float, default=0.0)


# ---------------------------------------------------------------------------
# Agents / workflows
# ---------------------------------------------------------------------------
class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    id: Mapped[str] = pk("agt")
    business_id: Mapped[str | None] = mapped_column(ForeignKey("businesses.id"), index=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="IDLE")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_run_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentExecution(Base, TimestampMixin):
    __tablename__ = "agent_executions"
    id: Mapped[str] = pk("aex")
    business_id: Mapped[str | None] = mapped_column(ForeignKey("businesses.id"), index=True)
    agent_key: Mapped[str] = mapped_column(String(80), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="SUCCEEDED")
    summary: Mapped[str] = mapped_column(Text, default="")
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    model_provider: Mapped[str] = mapped_column(String(60), default="deterministic")


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = pk("wf")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    workflow: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="RUNNING")
    thread_id: Mapped[str] = mapped_column(String(100), unique=True)
    trigger: Mapped[str] = mapped_column(String(30), default="MANUAL")
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    initiated_by: Mapped[str] = mapped_column(String(160), default="system")
    parent_run_id: Mapped[str | None] = mapped_column(String(64))


class WorkflowStep(Base, TimestampMixin):
    __tablename__ = "workflow_steps"
    id: Mapped[str] = pk("wfs")
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    node: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="SUCCEEDED")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[Any | None] = mapped_column(UTCDateTime())


# ---------------------------------------------------------------------------
# Decisions, approvals, actions
# ---------------------------------------------------------------------------
class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"
    id: Mapped[str] = pk("dec")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    alert_id: Mapped[str | None] = mapped_column(ForeignKey("alerts.id"))
    issue: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(240))
    objective: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    alternatives: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    chosen: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_financial_impact: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    reversibility: Mapped[str] = mapped_column(String(30), default="REVERSIBLE")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    audit_rounds: Mapped[int] = mapped_column(Integer, default=0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey("simulations.id"))


class DecisionReview(Base, TimestampMixin):
    __tablename__ = "decision_reviews"
    id: Mapped[str] = pk("drev")
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    verdict: Mapped[str] = mapped_column(String(40))
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    conditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    findings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewer: Mapped[str] = mapped_column(String(80), default="independent-auditor")
    model_provider: Mapped[str] = mapped_column(String(60), default="deterministic")


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"
    id: Mapped[str] = pk("apr")
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), index=True)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requested_at: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    decided_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    decided_by: Mapped[str | None] = mapped_column(String(160))
    comment: Mapped[str] = mapped_column(Text, default="")


class BusinessAction(Base, TimestampMixin):
    __tablename__ = "business_actions"
    id: Mapped[str] = pk("act")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(80))
    target_system: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_outcome: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    external_id: Mapped[str | None] = mapped_column(String(160))
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    verified_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class ActionVerification(Base, TimestampMixin):
    __tablename__ = "action_verifications"
    id: Mapped[str] = pk("aver")
    action_id: Mapped[str] = mapped_column(ForeignKey("business_actions.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    expected: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actual: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    differences: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    business_impact: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")


class MockExternalRecord(Base, TimestampMixin):
    """A local stand-in for a third-party system.

    This is explicitly simulated. It is the only thing our mock ERP connector
    touches; the platform never claims a real external API was called.
    """
    __tablename__ = "mock_external_records"
    id: Mapped[str] = pk("ext")
    system: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(80), index=True)
    record_key: Mapped[str] = mapped_column(String(160), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("system", "entity", "record_key", name="uq_mock_record"),)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
class Scenario(Base, TimestampMixin):
    __tablename__ = "scenarios"
    id: Mapped[str] = pk("scn")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(160), default="system")


class Simulation(Base, TimestampMixin):
    __tablename__ = "simulations"
    id: Mapped[str] = pk("sim")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("metric_snapshots.id"))
    baseline: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    alternatives: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    monte_carlo: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sensitivity: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    backtest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(160), default="system")
    finished_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Alerts, notifications, reports, audit
# ---------------------------------------------------------------------------
class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"
    id: Mapped[str] = pk("alr")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    dedup_key: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(30), default="OPEN", index=True)
    title: Mapped[str] = mapped_column(String(240))
    detail: Mapped[str] = mapped_column(Text, default="")
    area: Mapped[str] = mapped_column(String(80), default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow)
    acknowledged_by: Mapped[str | None] = mapped_column(String(160))
    acknowledged_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    resolved_by: Mapped[str | None] = mapped_column(String(160))
    resolved_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    resolution_note: Mapped[str] = mapped_column(Text, default="")


class AlertEvent(Base, TimestampMixin):
    __tablename__ = "alert_events"
    id: Mapped[str] = pk("ale")
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(160), default="system")


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[str] = pk("ntf")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="IN_APP")
    recipient: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")
    related_type: Mapped[str] = mapped_column(String(60), default="")
    related_id: Mapped[str] = mapped_column(String(64), default="")
    sent_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(Text)


class Report(Base, TimestampMixin):
    __tablename__ = "reports"
    id: Mapped[str] = pk("rpt")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    report_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(240))
    period_start: Mapped[Any | None] = mapped_column(UTCDateTime())
    period_end: Mapped[Any | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(30), default="READY")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    files: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    generated_by: Mapped[str] = mapped_column(String(80), default="reporting-agent")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = pk("aud")
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    business_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(160))
    actor_type: Mapped[str] = mapped_column(String(30), default="USER")
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(60), default="")
    request_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class BusinessEvent(Base, TimestampMixin):
    __tablename__ = "business_events"
    id: Mapped[str] = pk("evt")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(240))
    detail: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="INFO")
    actor: Mapped[str] = mapped_column(String(120), default="system")
    related_type: Mapped[str] = mapped_column(String(60), default="")
    related_id: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Excel conversion
# ---------------------------------------------------------------------------
class ExcelConversion(Base, TimestampMixin):
    __tablename__ = "excel_conversions"
    id: Mapped[str] = pk("xls")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(40), default="UPLOADED", index=True)
    workbook_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dependency_graph: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    formulas: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    unsupported: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    generated_code: Mapped[str] = mapped_column(Text, default="")
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report_path: Mapped[str] = mapped_column(String(500), default="")
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("business_rules.id"))
    approved_by: Mapped[str | None] = mapped_column(String(160))
    approved_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    workflow_run_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = pk("kdoc")
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    collection: Mapped[str] = mapped_column(String(80), default="policies")
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(JSON)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
