"""Pydantic request contracts for the API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    tenant_slug: str = "northwind-demo"


class WorkflowRunRequest(BaseModel):
    alert_id: str | None = None
    issue: dict[str, Any] | None = None
    source_ids: list[str] | None = None
    snapshot_id: str | None = None
    parameters: dict[str, Any] | None = None
    name: str | None = None
    description: str = ""
    with_monte_carlo: bool = True


class SimulationRequest(BaseModel):
    parameters: dict[str, Any]
    name: str = Field(default="Interactive scenario", max_length=200)
    description: str = ""
    snapshot_id: str | None = None
    with_monte_carlo: bool = True
    horizon_months: int = Field(default=12, ge=1, le=36)


class SimulationCompareRequest(BaseModel):
    simulation_ids: list[str] = Field(min_length=1, max_length=8)


class ApprovalDecision(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=4000)


class AlertAction(BaseModel):
    note: str = Field(default="", max_length=2000)


class RuleCreateRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,80}$")
    name: str = Field(min_length=3, max_length=200)
    description: str = ""
    category: str = "custom"
    code: str
    input_schema: dict[str, str] = Field(default_factory=dict)
    output_schema: dict[str, str] = Field(default_factory=dict)
    tests: list[dict[str, Any]] = Field(default_factory=list)
    execution_frequency: str = "ON_DEMAND"


class RuleDraftRequest(BaseModel):
    code: str
    tests: list[dict[str, Any]] = Field(default_factory=list)
    changelog: str = Field(default="", max_length=1000)
    description: str | None = None


class RuleTestRequest(BaseModel):
    code: str | None = None
    tests: list[dict[str, Any]] | None = None
    inputs: dict[str, Any] | None = None
    rule_id: str | None = None


class RuleRunRequest(BaseModel):
    inputs: dict[str, Any]
    test_mode: bool = False


class RuleActivateRequest(BaseModel):
    version_id: str


class SourceSyncRequest(BaseModel):
    trigger: str = "MANUAL"


class ExcelApprovalRequest(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=2000)


class CredentialStoreRequest(BaseModel):
    data_source_id: str
    name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=8000)


class ConnectorTestRequest(BaseModel):
    kind: str
    config: dict[str, Any]


class DataSourceCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    kind: str
    system: str = ""
    config: dict[str, Any]
    sync_now: bool = True
