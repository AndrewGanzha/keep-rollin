from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, User
from src.application.dtos.auth_dto import LoginRequest
from src.domain.exceptions import CatalogDomainError
from src.domain.policies.password_policy import (
    PasswordCompromisedError,
    ensure_password_not_compromised,
)
from src.domain.value_objects.slug import Slug
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord
from src.infrastructure.security.password_hasher import Argon2PasswordHasher
from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.security.vapid import generate_vapid_keypair

DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class ProvisioningError(Exception):
    pass


class ProvisioningConflictError(ProvisioningError):
    pass


@dataclass(frozen=True)
class ProvisionResult:
    created: bool
    tenant_id: UUID
    owner_id: UUID
    password: str | None
    vapid_public_key: str


class ProvisionTenantService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        secret_box: SecretBox,
        password_hasher: Argon2PasswordHasher | None = None,
    ) -> None:
        self._session = session
        self._secret_box = secret_box
        self._hasher = password_hasher or Argon2PasswordHasher()

    async def provision(
        self,
        *,
        name: str,
        slug: str,
        domain: str,
        owner_email: str,
        owner_name: str | None = None,
        password: str | None = None,
    ) -> ProvisionResult:
        normalized_name = name.strip()
        if not normalized_name or "\x00" in normalized_name:
            raise ProvisioningError("tenant name is invalid")
        normalized_slug = Slug.create(slug.strip().lower()).value
        normalized_domain = domain.strip().lower().removesuffix(".")
        if len(normalized_domain) > 253 or not all(
            DOMAIN_LABEL.fullmatch(label) for label in normalized_domain.split(".")
        ):
            raise ProvisioningError("domain must be a bare host")
        raw_password = secrets.token_urlsafe(24) if password is None else password
        try:
            credentials = LoginRequest(email=owner_email.strip(), password=raw_password)
        except ValidationError as exc:
            raise ProvisioningError("owner email or password is invalid") from exc
        normalized_email = credentials.email
        resolved_name = ((owner_name or "").strip() or normalized_email.split("@", 1)[0])[:120]
        if "\x00" in resolved_name:
            raise ProvisioningError("owner name is invalid")

        matches = (
            (
                await self._session.execute(
                    select(Tenant)
                    .where(
                        or_(
                            Tenant.slug == normalized_slug,
                            Tenant.domain == normalized_domain,
                        )
                    )
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        if len(matches) > 1:
            raise ProvisioningConflictError("slug and domain already belong to different tenants")
        existing = matches[0] if matches else None
        if existing is not None:
            if existing.slug != normalized_slug or existing.domain != normalized_domain:
                raise ProvisioningConflictError("slug or domain already belongs to another tenant")
            owner = (
                await self._session.execute(
                    select(User).where(
                        User.tenant_id == existing.id,
                        User.email == normalized_email,
                        User.role == "owner",
                    )
                )
            ).scalar_one_or_none()
            if owner is None:
                raise ProvisioningConflictError("tenant exists but the requested owner is missing")
            settings = (
                await self._session.execute(
                    select(TenantSettingsRecord).where(
                        TenantSettingsRecord.tenant_id == existing.id
                    )
                )
            ).scalar_one_or_none()
            public_key = settings.vapid_public_key if settings is not None else None
            if public_key is None:
                raise ProvisioningError("existing tenant has no VAPID public key")
            return ProvisionResult(
                created=False,
                tenant_id=existing.id,
                owner_id=owner.id,
                password=None,
                vapid_public_key=public_key,
            )

        tenant_id = uuid4()
        if password is not None:
            try:
                ensure_password_not_compromised(raw_password)
            except PasswordCompromisedError as exc:
                raise ProvisioningError("owner password is compromised") from exc
        password_hash = self._hasher.hash(raw_password)
        vapid = generate_vapid_keypair()
        private_key_enc = self._secret_box.encrypt(
            vapid.private_key,
            context=f"vapid:{tenant_id}",
        )
        tenant = Tenant(
            id=tenant_id,
            name=normalized_name[:200],
            slug=normalized_slug,
            domain=normalized_domain,
            subdomain=None,
        )
        owner = User(
            id=uuid4(),
            tenant_id=tenant_id,
            email=normalized_email,
            name=resolved_name,
            role="owner",
            password_hash=password_hash,
            verification_status="approved",
            is_active=True,
            token_version=1,
        )
        settings = TenantSettingsRecord(
            tenant_id=tenant_id,
            vapid_public_key=vapid.public_key,
            vapid_private_key_enc=private_key_enc,
            vapid_key_id=vapid.key_id,
        )
        audit = AuditLogRecord(
            tenant_id=tenant_id,
            action="tenant.provisioned",
            actor_id=None,
            actor_role="platform",
            entity_type="tenant",
            entity_id=tenant_id,
            metadata_json={"source": "cli"},
            created_at=datetime.now(UTC),
        )
        self._session.add_all([tenant, owner, settings, audit])
        try:
            await self._session.flush()
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ProvisioningConflictError("tenant provisioning conflicted") from exc
        return ProvisionResult(
            created=True,
            tenant_id=tenant_id,
            owner_id=owner.id,
            password=raw_password,
            vapid_public_key=vapid.public_key,
        )


__all__ = [
    "CatalogDomainError",
    "ProvisionResult",
    "ProvisionTenantService",
    "ProvisioningConflictError",
    "ProvisioningError",
]
