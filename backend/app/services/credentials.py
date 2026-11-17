"""Encrypted credential metadata service. Secrets are never returned by the API."""
from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.secrets import encrypt_secret, key_hint
from app.core.utils import utcnow
from app.domain.models import Credential, DataSource, Tenant


class CredentialService:
    async def store(
        self,
        session: AsyncSession,
        *,
        tenant: Tenant,
        business_id: str,
        data_source_id: str,
        name: str,
        value: str,
        actor: str,
    ) -> Credential:
        source = await session.get(DataSource, data_source_id)
        if not source or source.business_id != business_id:
            raise NotFoundError("Data source not found")
        ciphertext, nonce = encrypt_secret(value)
        credential = (
            await session.execute(
                select(Credential).where(
                    Credential.data_source_id == data_source_id, Credential.name == name
                )
            )
        ).scalar_one_or_none()
        if credential:
            credential.ciphertext = ciphertext
            credential.nonce = nonce
            credential.key_hint = key_hint(value)
            credential.rotated_at = utcnow()
        else:
            credential = Credential(
                tenant_id=tenant.id,
                data_source_id=data_source_id,
                name=name,
                ciphertext=ciphertext,
                nonce=nonce,
                key_hint=key_hint(value),
                rotated_at=utcnow(),
            )
            session.add(credential)
        await session.flush()
        return credential

    async def list_metadata(self, session: AsyncSession, business_id: str) -> list[dict]:
        sources = (
            await session.execute(select(DataSource.id).where(DataSource.business_id == business_id))
        ).scalars().all()
        if not sources:
            return []
        rows = (
            await session.execute(
                select(Credential)
                .where(Credential.data_source_id.in_(sources))
                .order_by(desc(Credential.updated_at))
            )
        ).scalars().all()
        return [
            {
                "id": row.id,
                "data_source_id": row.data_source_id,
                "name": row.name,
                "key_hint": row.key_hint,
                "rotated_at": row.rotated_at.isoformat() if row.rotated_at else None,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]


credential_service = CredentialService()
