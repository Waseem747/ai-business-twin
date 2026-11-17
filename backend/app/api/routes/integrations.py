"""Data integration routes: source health, sync, tabular upload and transformation lineage."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import desc, select

from app.api.deps import BusinessDep, DBSession
from app.api.schemas import ConnectorTestRequest, CredentialStoreRequest, DataSourceCreateRequest
from app.api.serializers import dt, source_out
from app.config import settings
from app.core.security import CurrentUser
from app.domain.models import DataSource, IngestionRun, Tenant, Transformation, TransformationRun
from app.services.credentials import credential_service
from app.services.ingestion import CONNECTORS, ingestion_service
from app.services.transformation import transformation_service
from app.services.twin_state import build_snapshot
from app.connectors.sql_database import validate_read_query

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])

CONNECTOR_METADATA = {
    "SQL_DATABASE": {
        "label": "SQL database",
        "description": "Read-only SELECT query against PostgreSQL, MySQL or SQLite. Secrets are environment references.",
        "fields": ["name", "connection_env", "query", "value_column", "period_column", "entity", "metric"],
    },
    "GOOGLE_SHEETS": {
        "label": "Google Sheets",
        "description": "Read a link-shared sheet via CSV export, or a private sheet via API key / service account.",
        "fields": ["spreadsheet_url", "sheet_name", "range", "service_account_env", "value_column", "period_column"],
    },
    "REST": {
        "label": "REST API",
        "description": "Paginated JSON API with retries, authentication environment reference and field mapping.",
        "fields": ["base_url", "path", "records_path", "auth_env", "value", "period"],
    },
    "GRAPHQL": {
        "label": "GraphQL",
        "description": "Read-only GraphQL query. Raw data is retained; a mapping adapter can be added.",
        "fields": ["base_url", "query", "auth_env"],
    },
}

SECRET_KEYS = {"password", "secret", "token", "private_key", "api_key", "connection_url"}


def _safe_connector_error(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"://[^@\s]+@", "://***@", message)
    return f"{type(exc).__name__}: {message}"[:800]


def _validate_connector_config(kind: str, config: dict) -> dict:
    if kind not in CONNECTOR_METADATA:
        raise HTTPException(status_code=422, detail=f"Unsupported connector kind '{kind}'")
    for key in (config or {}):
        lowered = key.lower()
        if lowered.endswith("_env"):
            continue
        if any(secret in lowered for secret in SECRET_KEYS):
            raise HTTPException(
                status_code=422,
                detail="Do not send raw secrets. Use an environment/secret reference (for example connection_env or auth_env).",
            )
    if kind == "SQL_DATABASE":
        if not config.get("connection_env"):
            raise HTTPException(status_code=422, detail="connection_env (secret reference) is required")
        try:
            validate_read_query(str(config.get("query") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if kind == "GOOGLE_SHEETS":
        if not (config.get("spreadsheet_id") or config.get("spreadsheet_url")):
            raise HTTPException(status_code=422, detail="spreadsheet_url or spreadsheet_id is required")
        if not (config.get("sheet_name") or config.get("range")):
            raise HTTPException(status_code=422, detail="sheet_name or range is required")
    if kind in {"REST", "GRAPHQL"} and not config.get("base_url"):
        raise HTTPException(status_code=422, detail="base_url is required")
    if kind == "REST" and not config.get("mapping", {}).get("value"):
        raise HTTPException(status_code=422, detail="mapping.value is required for REST sources")
    return config


@router.get("/connector-types")
async def connector_types(user: CurrentUser) -> dict:
    return {
        "connectors": [
            {
                "kind": key,
                **value,
                "secret_policy": "Credentials are provided as environment variable references and never stored in source config.",
            }
            for key, value in CONNECTOR_METADATA.items()
        ],
        "auth": {
            "sql": {"env_example": "ANALYTICS_DATABASE_URL=postgresql://readonly:...@host:5432/analytics"},
            "google_private": {"service_account_env": "GOOGLE_SERVICE_ACCOUNT_JSON", "api_key_env": "GOOGLE_SHEETS_API_KEY"},
            "rest": {"auth_env": "VENDOR_API_TOKEN"},
        },
    }


@router.post("/connectors/test")
async def test_connector(payload: ConnectorTestRequest, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    if user.role not in {"ADMIN", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    config = _validate_connector_config(payload.kind, payload.config or {})
    connector_cls = CONNECTORS.get(payload.kind)
    if not connector_cls:
        raise HTTPException(status_code=422, detail=f"No connector implementation for {payload.kind}")
    try:
        connector = connector_cls(config)
        result = await asyncio.wait_for(connector.fetch(None, {}), timeout=60)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Connection test failed: {_safe_connector_error(exc)}") from exc
    sample = [
        {
            "period": fact.period_start.isoformat() if fact.period_start else None,
            "entity": fact.entity,
            "metric": fact.metric,
            "value": fact.value,
            "channel": fact.channel,
            "category": fact.category,
            "unit": fact.unit,
        }
        for fact in result.facts[:5]
    ]
    return {
        "ok": True,
        "kind": payload.kind,
        "fact_count": len(result.facts),
        "sample": sample,
        "schema": result.schema,
        "notes": result.notes,
        "simulated": result.simulated,
        "freshness_at": result.freshness_at.isoformat() if result.freshness_at else None,
    }


@router.post("/sources")
async def create_source(payload: DataSourceCreateRequest, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    if user.role not in {"ADMIN", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    config = _validate_connector_config(payload.kind, payload.config or {})
    source = DataSource(
        business_id=business.id,
        name=payload.name.strip(),
        kind=payload.kind,
        system=payload.system or payload.kind.lower(),
        status="CONNECTED",
        simulated=False,
        config=config,
    )
    db.add(source)
    await db.flush()
    run = None
    if payload.sync_now:
        run = await ingestion_service.sync_source(
            db, source, trigger="CONNECTION_SETUP", actor=user.email
        )
        if run.status == "SUCCEEDED":
            await transformation_service.apply_active(db, business.id, run.id)
            await build_snapshot(db, business)
    await db.commit()
    return {
        "source": source_out(source),
        "run": {
            "id": run.id,
            "status": run.status,
            "records_read": run.records_read,
            "records_ingested": run.records_ingested,
            "records_rejected": run.records_rejected,
            "duplicates_blocked": run.duplicates_blocked,
            "lineage": run.lineage,
            "error": run.error,
        }
        if run
        else None,
    }


@router.get("")
async def integrations(business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    sources = (
        await db.execute(select(DataSource).where(DataSource.business_id == business.id))
    ).scalars().all()
    health = {item["id"]: item for item in await ingestion_service.source_health(db, business.id)}
    runs = (
        await db.execute(
            select(IngestionRun).where(IngestionRun.business_id == business.id).order_by(desc(IngestionRun.started_at)).limit(20)
        )
    ).scalars().all()
    transforms = (
        await db.execute(select(Transformation).where(Transformation.business_id == business.id))
    ).scalars().all()
    transform_runs = (
        await db.execute(
            select(TransformationRun)
            .where(TransformationRun.transformation_id.in_([transform.id for transform in transforms]))
            .order_by(desc(TransformationRun.created_at))
            .limit(15)
        )
    ).scalars().all() if transforms else []
    return {
        "sources": [source_out(source, health.get(source.id)) for source in sources],
        "summary": {
            "connected": sum(1 for source in sources if source.status == "CONNECTED"),
            "stale": sum(1 for item in health.values() if item.get("stale")),
            "errors": sum(1 for source in sources if source.status == "ERROR"),
            "simulated": sum(1 for source in sources if source.simulated),
        },
        "recent_ingestions": [
            {
                "id": run.id,
                "source_id": run.data_source_id,
                "status": run.status,
                "trigger": run.trigger,
                "records_read": run.records_read,
                "records_ingested": run.records_ingested,
                "records_rejected": run.records_rejected,
                "duplicates_blocked": run.duplicates_blocked,
                "raw_payload_ref": run.raw_payload_ref,
                "lineage": run.lineage,
                "error": run.error,
                "started_at": dt(run.started_at),
                "finished_at": dt(run.finished_at),
            }
            for run in runs
        ],
        "transformations": [
            {
                "id": transform.id,
                "name": transform.name,
                "description": transform.description,
                "kind": transform.kind,
                "status": transform.status,
                "version": transform.version,
                "ai_assisted": transform.ai_assisted,
                "reviewed_by": transform.reviewed_by,
                "source_field": transform.source_field,
                "target_field": transform.target_field,
            }
            for transform in transforms
        ],
        "transformation_runs": [
            {"id": run.id, "status": run.status, "stats": run.stats, "created_at": dt(run.created_at)}
            for run in transform_runs
        ],
        "notice": "Credentials are never returned by the API. Simulated sources are labelled and do not contact external systems.",
    }


@router.post("/{source_id}/sync")
async def sync_source(source_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    if user.role == "VIEWER":
        raise HTTPException(status_code=403, detail="Viewers cannot trigger synchronisation")
    source = await db.get(DataSource, source_id)
    if not source or source.business_id != business.id:
        raise HTTPException(status_code=404, detail="Data source not found")
    run = await ingestion_service.sync_source(db, source, trigger="MANUAL", actor=user.email)
    transform_runs = await transformation_service.apply_active(db, business.id, run.id)
    await db.flush()
    if run.status == "SUCCEEDED":
        await build_snapshot(db, business)
    await db.commit()
    return {
        "run": {
            "id": run.id,
            "status": run.status,
            "records_read": run.records_read,
            "records_ingested": run.records_ingested,
            "records_rejected": run.records_rejected,
            "duplicates_blocked": run.duplicates_blocked,
            "lineage": run.lineage,
            "error": run.error,
        },
        "transformations": [{"id": item.id, "status": item.status, "stats": item.stats} for item in transform_runs],
        "source": source_out(source),
    }


@router.post("/credentials")
async def store_credential(
    payload: CredentialStoreRequest, business: BusinessDep, db: DBSession, user: CurrentUser
) -> dict:
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Only administrators can manage credentials")
    tenant = await db.get(Tenant, user.tenant_id)
    credential = await credential_service.store(
        db,
        tenant=tenant,
        business_id=business.id,
        data_source_id=payload.data_source_id,
        name=payload.name,
        value=payload.value,
        actor=user.email,
    )
    await db.commit()
    return {
        "id": credential.id,
        "name": credential.name,
        "key_hint": credential.key_hint,
        "data_source_id": credential.data_source_id,
        "rotated_at": dt(credential.rotated_at),
    }


@router.get("/credentials")
async def list_credentials(business: BusinessDep, db: DBSession, user: CurrentUser) -> list[dict]:
    if user.role not in {"ADMIN", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await credential_service.list_metadata(db, business.id)


@router.post("/upload")
async def upload_tabular(
    business: BusinessDep,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    entity: str = Form(...),
    metric: str = Form(...),
    period_column: str = Form("period"),
    value_column: str = Form("value"),
    channel_column: str = Form("channel"),
    category_column: str = Form("category"),
) -> dict:
    if user.role not in {"ADMIN", "ANALYST"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    filename = Path(file.filename or "upload.csv").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xlsm"}:
        raise HTTPException(status_code=422, detail="Only CSV or Excel uploads are supported")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    folder = settings.storage_path / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{business.id[:8]}_{safe}"
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Upload exceeds 25 MB")
    path.write_bytes(content)
    source = DataSource(
        business_id=business.id,
        name=f"Uploaded {filename}",
        kind="EXCEL" if suffix in {".xlsx", ".xlsm"} else "CSV",
        system="file_upload",
        status="CONNECTED",
        simulated=False,
        config={
            "path": str(path),
            "mapping": {
                "entity": "entity",
                "metric": "metric",
                "period": period_column,
                "value": value_column,
                "channel": channel_column,
                "category": category_column,
                "unit": "unit",
            },
            "default_entity": entity,
            "default_metric": metric,
        },
    )
    db.add(source)
    await db.flush()
    run = await ingestion_service.sync_source(db, source, trigger="UPLOAD", actor=user.email)
    if run.status == "SUCCEEDED":
        await transformation_service.apply_active(db, business.id, run.id)
        await build_snapshot(db, business)
    await db.commit()
    return {
        "source": source_out(source),
        "run": {
            "id": run.id,
            "status": run.status,
            "records_ingested": run.records_ingested,
            "records_rejected": run.records_rejected,
            "lineage": run.lineage,
            "error": run.error,
        },
    }
