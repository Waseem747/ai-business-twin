"""Authentication routes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import LoginRequest
from app.core.security import CurrentUser, create_access_token, verify_password
from app.core.utils import utcnow
from app.db import get_db
from app.domain.models import Tenant, User

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "title": user.title,
        "tenant_id": user.tenant_id,
    }


async def _authenticate(db: AsyncSession, email: str, password: str, tenant_slug: str) -> User:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = (
        await db.execute(
            select(User).where(User.tenant_id == tenant.id, User.email == email.lower(), User.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user


@router.post("/login")
async def login(payload: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    user = await _authenticate(db, payload.email, payload.password, payload.tenant_slug)
    token, expires_in = create_access_token(user)
    user.last_login_at = utcnow()
    await db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in, "user": _user_payload(user)}


@router.post("/token")
async def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], db: Annotated[AsyncSession, Depends(get_db)]
) -> dict:
    user = await _authenticate(db, form.username, form.password, "northwind-demo")
    token, expires_in = create_access_token(user)
    user.last_login_at = utcnow()
    await db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in, "user": _user_payload(user)}


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return _user_payload(user)
