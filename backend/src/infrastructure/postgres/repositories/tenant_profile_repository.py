from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant
from src.application.repositories.i_tenant_profile_repository import ITenantProfileRepository
from src.domain.entities.tenant_profile import TenantPolicies, TenantProfile
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord

DEFAULT_PRIMARY_COLOR = "#0f766e"


class TenantProfileRepository(ITenantProfileRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def get_current(self) -> TenantProfile | None:
        statement = (
            select(Tenant, TenantSettingsRecord)
            .outerjoin(TenantSettingsRecord, TenantSettingsRecord.tenant_id == Tenant.id)
            .where(Tenant.id == self._tenant_id())
        )
        result = await self._session.execute(statement)
        row = result.one_or_none()
        if row is None:
            return None

        tenant, settings = row
        policies = TenantPolicies.from_mapping(settings.policies if settings is not None else {})
        return TenantProfile(
            id=tenant.id,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            name=EntityName.create(tenant.name),
            slug=Slug.create(tenant.slug),
            timezone=tenant.timezone,
            currency=tenant.currency,
            logo_url=settings.logo_url if settings is not None else None,
            primary_color=(
                settings.primary_color if settings is not None else DEFAULT_PRIMARY_COLOR
            ),
            vapid_public_key=settings.vapid_public_key if settings is not None else None,
            policies=policies,
        )
