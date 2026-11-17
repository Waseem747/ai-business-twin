"""Management reports and artifact downloads."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import desc, select

from app.api.deps import BusinessDep, DBSession
from app.api.serializers import report_out
from app.core.security import CurrentUser
from app.domain.models import Report
from app.services.reporting import reporting_service

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("")
async def list_reports(
    business: BusinessDep,
    db: DBSession,
    user: CurrentUser,
    report_type: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
) -> list[dict]:
    rows = await reporting_service.list_reports(db, business.id, report_type, limit)
    return [report_out(row) for row in rows]


@router.get("/{report_id}")
async def get_report(report_id: str, business: BusinessDep, db: DBSession, user: CurrentUser) -> dict:
    report = await db.get(Report, report_id)
    if not report or report.business_id != business.id:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_out(report, include_content=True)


@router.get("/{report_id}/download")
async def download_report(
    report_id: str, business: BusinessDep, db: DBSession, user: CurrentUser, format: str = "pdf"
) -> FileResponse:
    report = await db.get(Report, report_id)
    if not report or report.business_id != business.id:
        raise HTTPException(status_code=404, detail="Report not found")
    files = report.files or {}
    if format not in files:
        raise HTTPException(status_code=404, detail=f"No {format} artifact for this report")
    path = Path(files[format])
    if not path.exists():
        raise HTTPException(status_code=410, detail="Report artifact no longer exists")
    media = {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
    }.get(format, "application/octet-stream")
    return FileResponse(path, filename=f"{report.report_type.lower()}_{report.id[-8:]}.{format}", media_type=media)
