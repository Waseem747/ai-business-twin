"""Shared API dependencies: tenant isolation and default business resolution."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db import get_db
from app.domain.models import Business, Tenant

DBSession = Annotated[AsyncSession, Depends(get_db)]


async def get_business(
    db: DBSession, user: CurrentUser, business_id: str | None = None
) -> Business:
    tenant = await db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant not found")
    query = select(Business).where(Business.tenant_id == user.tenant_id)
    if business_id:
        query = query.where(Business.id == business_id)
    else:
        query = query.order_by(Business.is_demo.desc(), Business.created_at.asc())
    business = (await db.execute(query.limit(1))).scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


BusinessDep = Annotated[Business, Depends(get_business)]
