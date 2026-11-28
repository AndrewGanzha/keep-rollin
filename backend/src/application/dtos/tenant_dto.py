from typing import Self
from uuid import UUID

from pydantic import BaseModel

from src.domain.entities.tenant_profile import TenantProfile


class TenantPoliciesDTO(BaseModel):
    booking_horizon_days: int
    min_rental_minutes: int
    max_rental_days: int
    cancellation_free_hours: int
    reminder_hours_before: int
    tickets_per_rental_per_day: int
    lot_photos_max: int
    verification_docs_retention_days: int


class TenantDTO(BaseModel):
    id: UUID
    name: str
    slug: str
    logo_url: str | None
    primary_color: str
    timezone: str
    currency: str
    vapid_public_key: str | None
    policies: TenantPoliciesDTO

    @classmethod
    def from_domain(cls, tenant: TenantProfile) -> Self:
        return cls(
            id=tenant.id,
            name=tenant.name.value,
            slug=tenant.slug.value,
            logo_url=tenant.logo_url,
            primary_color=tenant.primary_color,
            timezone=tenant.timezone,
            currency=tenant.currency,
            vapid_public_key=tenant.vapid_public_key,
            policies=TenantPoliciesDTO(**tenant.policies.to_mapping()),
        )
