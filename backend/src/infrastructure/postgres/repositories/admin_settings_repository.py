from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant
from src.application.repositories.i_admin_settings_repository import (
    AdminSettingsState,
    IAdminSettingsRepository,
)
from src.domain.entities.tenant_profile import (
    SettingsNotFoundError,
    SettingsVersionConflictError,
    TenantPolicies,
)
from src.infrastructure.postgres.models.tenant_settings_record import (
    DEFAULT_POLICIES,
    TenantSettingsRecord,
)

DEFAULT_PRIMARY_COLOR = "#0f766e"


class AdminSettingsRepository(IAdminSettingsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def get(self) -> AdminSettingsState | None:
        result = await self._session.execute(
            select(Tenant, TenantSettingsRecord)
            .outerjoin(TenantSettingsRecord, TenantSettingsRecord.tenant_id == Tenant.id)
            .where(Tenant.id == self._tenant_id())
        )
        row = result.one_or_none()
        if row is None:
            return None
        tenant, settings = row
        return self._to_state(tenant, settings)

    async def update(
        self,
        *,
        version: int,
        changes: Mapping[str, object],
        policies: TenantPolicies | None,
    ) -> AdminSettingsState:
        tenant_id = self._tenant_id()
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"settings:{tenant_id}", 0)))
        )
        settings_values: dict[str, object] = {}
        for key in ("logo_url", "primary_color"):
            if key in changes:
                settings_values[key] = changes[key]
        if policies is not None:
            settings_values["policies"] = policies.to_mapping()

        existing = await self._session.scalar(
            select(TenantSettingsRecord.version).where(TenantSettingsRecord.tenant_id == tenant_id)
        )
        if existing is None:
            if version != 1:
                raise SettingsVersionConflictError("settings version is stale")
            record = TenantSettingsRecord(
                tenant_id=tenant_id,
                policies=policies.to_mapping() if policies is not None else dict(DEFAULT_POLICIES),
                version=2,
                **{
                    key: value
                    for key, value in settings_values.items()
                    if key in ("logo_url", "primary_color")
                },
            )
            self._session.add(record)
            await self._session.flush()
        else:
            values: dict[str, object] = {
                **settings_values,
                "version": TenantSettingsRecord.version + 1,
                "updated_at": func.now(),
            }
            result = await self._session.execute(
                update(TenantSettingsRecord)
                .where(
                    TenantSettingsRecord.tenant_id == tenant_id,
                    TenantSettingsRecord.version == version,
                )
                .values(**values)
                .returning(TenantSettingsRecord.version)
            )
            if result.scalar_one_or_none() is None:
                raise SettingsVersionConflictError("settings version is stale")

        tenant_changes = {
            key: value for key, value in changes.items() if key in ("timezone", "currency")
        }
        if tenant_changes:
            await self._session.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(**tenant_changes, updated_at=func.now())
            )
        state = await self.get()
        if state is None:
            raise SettingsNotFoundError("settings not found")
        return state

    @staticmethod
    def _to_state(
        tenant: Tenant,
        settings: TenantSettingsRecord | None,
    ) -> AdminSettingsState:
        return AdminSettingsState(
            logo_url=settings.logo_url if settings is not None else None,
            primary_color=(
                settings.primary_color if settings is not None else DEFAULT_PRIMARY_COLOR
            ),
            timezone=tenant.timezone,
            currency=tenant.currency,
            vapid_public_key=settings.vapid_public_key if settings is not None else None,
            policies=TenantPolicies.from_mapping(settings.policies if settings is not None else {}),
            version=settings.version if settings is not None else 1,
        )
