from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.tenant_profile import (
    InvalidTenantProfileError,
    TenantPolicies,
    TenantProfile,
)
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_policies_apply_defaults_and_validate_values() -> None:
    policies = TenantPolicies.from_mapping({"booking_horizon_days": 90})
    assert policies.booking_horizon_days == 90
    assert policies.max_rental_days == 30

    with pytest.raises(InvalidTenantProfileError):
        TenantPolicies.from_mapping({"max_rental_days": True})
    with pytest.raises(InvalidTenantProfileError):
        TenantPolicies.from_mapping({"tickets_per_rental_per_day": -1})


def test_tenant_profile_validates_branding_and_currency() -> None:
    profile = TenantProfile(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        name=EntityName.create("Severny Veter"),
        slug=Slug.create("severny-veter"),
        timezone="Europe/Moscow",
        currency="RUB",
        logo_url="https://example.com/logo.png",
        primary_color="#0f766e",
        vapid_public_key="public-key",
        policies=TenantPolicies(),
    )
    assert profile.policies.reminder_hours_before == 1

    with pytest.raises(InvalidTenantProfileError):
        TenantProfile(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            name=EntityName.create("Bad"),
            slug=Slug.create("bad"),
            timezone="Europe/Moscow",
            currency="RUB",
            logo_url=None,
            primary_color="green",
            vapid_public_key=None,
            policies=TenantPolicies(),
        )
    with pytest.raises(InvalidTenantProfileError):
        TenantProfile(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            name=EntityName.create("Bad"),
            slug=Slug.create("bad"),
            timezone="Europe/Moscow",
            currency="rub",
            logo_url=None,
            primary_color="#0f766e",
            vapid_public_key=None,
            policies=TenantPolicies(),
        )
