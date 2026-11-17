"""Business Logic Studio: rule registry, testing, versioning and Excel conversion."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import desc, select

from app.api.deps import BusinessDep, DBSession
from app.api.schemas import (
    ExcelApprovalRequest,
    RuleActivateRequest,
    RuleCreateRequest,
    RuleDraftRequest,
    RuleRunRequest,
    RuleTestRequest,
)
from app.api.serializers import conversion_out, dt, rule_out
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.sandbox import SandboxValidationError, run_sandboxed, run_tests, validate_rule_code
from app.core.security import CurrentUser
from app.core.utils import utcnow
from app.domain.models import BusinessRule, ExcelConversion, RuleExecution, RuleVersion, WorkflowRun
from app.excel.service import excel_service
from app.logic.registry import rule_registry
from app.workflows.runner import workflow_runner

router = APIRouter(prefix="/api/logic", tags=["Business Logic Studio"])


@router.get("/rules")
async def list_rules(business: BusinessDep, db: DBSession, user: CurrentUser) -> list[dict]:
    rules = await rule_registry.list_rules(db, business.id)
    return [rule_out(rule) for rule in rules]


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    try:
        rule = await rule_registry.get(db, rule_id, business.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    versions = await rule_registry.versions(db, rule.id)
    executions = (
        await db.execute(
            select(RuleExecution).where(RuleExecution.rule_id == rule.id).order_by(desc(RuleExecution.created_at)).limit(20)
        )
    ).scalars().all()
    payload = rule_out(rule, include_code=True)
    payload["versions"] = [
        {
            "id": version.id,
            "version": version.version,
            "status": version.status,
            "changed_by": version.changed_by,
            "changelog": version.changelog,
            "tests": version.tests,
            "created_at": dt(version.created_at),
        }
        for version in versions
    ]
    payload["executions"] = [
        {
            "id": execution.id,
            "status": execution.status,
            "version": execution.rule_version,
            "inputs": execution.inputs,
            "outputs": execution.outputs,
            "duration_ms": execution.duration_ms,
            "error": execution.error,
            "sandboxed": execution.sandboxed,
            "created_at": dt(execution.created_at),
        }
        for execution in executions
    ]
    return payload


@router.get("/executions")
async def executions(business: BusinessDep, db: DBSession, user: CurrentUser, rule_key: str | None = None, limit: int = 50) -> list[dict]:
    rows = await rule_registry.executions(db, business.id, min(limit, 200), rule_key)
    return [
        {
            "id": row.id,
            "rule_key": row.rule_key,
            "rule_version": row.rule_version,
            "status": row.status,
            "inputs": row.inputs,
            "outputs": row.outputs,
            "duration_ms": row.duration_ms,
            "error": row.error,
            "sandboxed": row.sandboxed,
            "created_at": dt(row.created_at),
        }
        for row in rows
    ]


@router.post("/rules")
async def create_rule(payload: RuleCreateRequest, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    if user.role not in {"ADMIN", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Only analysts or administrators can create logic")
    existing = (
        await db.execute(
            select(BusinessRule).where(BusinessRule.business_id == business.id, BusinessRule.key == payload.key)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A rule with this key already exists")
    try:
        validate_rule_code(payload.code)
    except SandboxValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    results = run_tests(payload.code, "calculate", payload.tests)
    rule = BusinessRule(
        business_id=business.id,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        source="PYTHON",
        code=payload.code,
        input_schema=payload.input_schema,
        output_schema=payload.output_schema,
        version=1,
        dependencies=[],
        execution_frequency=payload.execution_frequency,
        tests=payload.tests,
        status="TESTING" if all(item["passed"] for item in results) else "DRAFT",
        excel_lineage={},
    )
    db.add(rule)
    await db.flush()
    version = RuleVersion(
        rule_id=rule.id,
        version=1,
        code=payload.code,
        tests=payload.tests,
        status=rule.status,
        changed_by=user.email,
        changelog="Initial draft",
    )
    db.add(version)
    await db.commit()
    return {
        "rule": rule_out(rule, include_code=True),
        "version_id": version.id,
        "test_results": results,
        "activation_required": True,
    }


@router.post("/rules/{rule_id}/draft")
async def create_draft(
    rule_id: str, payload: RuleDraftRequest, business: BusinessDep, db: DBSession, user: CurrentUser
) -> dict:
    if user.role not in {"ADMIN", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Only analysts or administrators can edit logic")
    rule = await rule_registry.get(db, rule_id, business.id)
    try:
        validate_rule_code(payload.code)
        version = await rule_registry.create_draft_version(
            db, rule, payload.code, payload.tests, payload.changelog, user.email, payload.description
        )
    except (SandboxValidationError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return {"version_id": version.id, "version": version.version, "status": version.status, "message": "Draft saved; approval required before activation."}


@router.post("/rules/{rule_id}/test")
async def test_rule(rule_id: str, payload: RuleTestRequest, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    rule = await rule_registry.get(db, rule_id, business.id)
    code = payload.code or rule.code
    tests = payload.tests if payload.tests is not None else rule.tests
    try:
        validate_rule_code(code)
    except SandboxValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.inputs is not None:
        result = run_sandboxed(code, "calculate", payload.inputs)
        return {"mode": "console", "ok": result.ok, "outputs": result.result, "error": result.error, "duration_ms": result.duration_ms}
    return {"mode": "tests", "results": run_tests(code, "calculate", tests or [])}


@router.post("/rules/{rule_id}/run")
async def run_rule(rule_id: str, payload: RuleRunRequest, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    if user.role == "VIEWER":
        raise HTTPException(status_code=403, detail="Viewers cannot execute rules")
    rule = await rule_registry.get(db, rule_id, business.id)
    try:
        output = await rule_registry.execute(
            db,
            rule,
            payload.inputs,
            business_id=business.id,
            actor=user.email,
            require_active=not payload.test_mode,
        )
    except (ConflictError, ValidationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"rule_key": rule.key, "version": rule.version, "outputs": output, "test_mode": payload.test_mode}


@router.post("/rules/{rule_id}/activate")
async def activate_rule(rule_id: str, payload: RuleActivateRequest, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    if user.role not in {"ADMIN", "APPROVER"}:
        raise HTTPException(status_code=403, detail="Only an approver or administrator can activate logic")
    rule = await rule_registry.get(db, rule_id, business.id)
    try:
        rule = await rule_registry.activate_version(db, rule, payload.version_id, user.email)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return {"rule": rule_out(rule, include_code=True), "message": "Rule version activated after passing tests."}


@router.get("/excel/conversions")
async def list_conversions(business: BusinessDep, db: DBSession, user: CurrentUser) -> list[dict]:
    rows = await excel_service.list(db, business.id)
    return [conversion_out(row, include_validation=False) for row in rows]


@router.post("/excel/conversions")
async def upload_conversion(business: BusinessDep, db: DBSession, user: CurrentUser, file: UploadFile = File(...)) -> dict:
    if user.role not in {"ADMIN", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Only analysts or administrators can upload workbooks")
    content = await file.read()
    try:
        stored = await excel_service.save_upload(content, file.filename or "workbook.xlsx")
        conversion = await excel_service.create(db, business, stored, file.filename or "workbook.xlsx")
    except (ConflictError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    run = await workflow_runner.start(
        db,
        business=business,
        workflow="excel_conversion",
        inputs={"conversion_id": conversion.id},
        actor=user.email,
        trigger="UPLOAD",
    )
    await db.commit()
    return {"conversion": conversion_out(conversion), "workflow": {"id": run.id, "status": run.status}}


@router.get("/excel/conversions/{conversion_id}")
async def get_conversion(conversion_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    try:
        conversion = await excel_service.get(db, conversion_id, business.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return conversion_out(conversion, include_code=True)


@router.get("/excel/conversions/{conversion_id}/code", response_class=PlainTextResponse)
async def conversion_code(conversion_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> str:
    conversion = await excel_service.get(db, conversion_id, business.id)
    return conversion.generated_code


@router.get("/excel/conversions/{conversion_id}/report")
async def conversion_report(conversion_id: str, business: BusinessDep, db: DBSession, user: CurrentUser):
    conversion = await excel_service.get(db, conversion_id, business.id)
    path = Path(conversion.report_path)
    if not conversion.report_path or not path.exists():
        raise HTTPException(status_code=404, detail="Conversion report is not available")
    return FileResponse(path, filename=f"{Path(conversion.filename).stem}_conversion_report.md", media_type="text/markdown")


@router.post("/excel/conversions/{conversion_id}/approve")
async def approve_conversion(
    conversion_id: str, payload: ExcelApprovalRequest, business: BusinessDep, db: DBSession, user: CurrentUser
) -> dict:
    if user.role not in {"ADMIN", "APPROVER"}:
        raise HTTPException(status_code=403, detail="Only an approver or administrator can approve conversions")
    conversion = await excel_service.get(db, conversion_id, business.id)
    if conversion.status == "ACTIVATED":
        return {"conversion": conversion_out(conversion), "message": "Conversion already activated."}
    run = await db.get(WorkflowRun, conversion.workflow_run_id) if conversion.workflow_run_id else None
    if run and run.status == "WAITING_APPROVAL":
        await db.commit()
        await workflow_runner.resume(
            run.id,
            {"approved": payload.approved, "actor": user.email, "comment": payload.comment},
        )
        return {
            "conversion_id": conversion.id,
            "workflow": {"id": run.id, "status": "RUNNING"},
            "message": "Approval submitted; activation is executing in the workflow.",
        }
    if payload.approved and conversion.status == "AWAITING_APPROVAL":
        try:
            rule = await excel_service.activate(db, business, conversion, user.email)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await db.commit()
        return {"conversion": conversion_out(conversion), "rule": rule_out(rule), "message": "Conversion activated."}
    if not payload.approved:
        conversion.status = "REJECTED"
        conversion.approved_by = user.email
        conversion.approved_at = utcnow()
        await db.commit()
        return {"conversion": conversion_out(conversion), "message": "Conversion rejected."}
    raise HTTPException(status_code=409, detail="Conversion is not awaiting approval")
