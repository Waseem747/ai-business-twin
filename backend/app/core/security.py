"""Password hashing, JWT issuance and RBAC dependencies."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.domain.models import User

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


class Role:
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    APPROVER = "APPROVER"
    VIEWER = "VIEWER"
    ALL = {ADMIN, ANALYST, APPROVER, VIEWER}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def create_access_token(user: User) -> tuple[str, int]:
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_ttl_minutes)
    claims = {
        "sub": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "role": user.role,
        "name": user.full_name,
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int(expires.timestamp()),
        "iss": "ai-business-twin",
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.access_token_ttl_minutes * 60


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], issuer="ai-business-twin"
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Session expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user = await db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User no longer active")
    return user


def require_roles(*roles: str):
    async def _dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles and user.role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _dependency


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
ApproverUser = Annotated[User, Depends(require_roles(Role.APPROVER, Role.ANALYST))]
ViewerUser = Annotated[User, Depends(get_current_user)]


async def find_user_by_email(db: AsyncSession, tenant_id: str, email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.email == email.lower())
    )
    return result.scalar_one_or_none()
