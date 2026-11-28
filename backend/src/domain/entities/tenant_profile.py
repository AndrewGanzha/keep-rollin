import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from src.domain.entities.base import Entity
from src.domain.exceptions import CatalogDomainError
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
POLICY_DEFAULTS: dict[str, int] = {
    "booking_horizon_days": 60,
    "min_rental_minutes": 60,
    "max_rental_days": 30,
    "cancellation_free_hours": 24,
    "reminder_hours_before": 1,
    "tickets_per_rental_per_day": 5,
    "lot_photos_max": 10,
    "verification_docs_retention_days": 90,
}
POLICY_RANGES: dict[str, tuple[int, int]] = {
    "booking_horizon_days": (1, 365),
    "min_rental_minutes": (15, 1440),
    "max_rental_days": (1, 90),
    "cancellation_free_hours": (0, 168),
    "reminder_hours_before": (1, 72),
    "tickets_per_rental_per_day": (1, 20),
    "lot_photos_max": (1, 20),
    "verification_docs_retention_days": (30, 365),
}


class InvalidTenantProfileError(CatalogDomainError):
    pass


class SettingsVersionConflictError(CatalogDomainError):
    pass


class SettingsNotFoundError(CatalogDomainError):
    pass


@dataclass(frozen=True)
class TenantPolicies:
    booking_horizon_days: int = 60
    min_rental_minutes: int = 60
    max_rental_days: int = 30
    cancellation_free_hours: int = 24
    reminder_hours_before: int = 1
    tickets_per_rental_per_day: int = 5
    lot_photos_max: int = 10
    verification_docs_retention_days: int = 90

    def __post_init__(self) -> None:
        for field, value in self.to_mapping().items():
            low, high = POLICY_RANGES[field]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise InvalidTenantProfileError(
                    f"{field} must be an integer between {low} and {high}"
                )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> Self:
        data: dict[str, int] = {}
        for field, default in POLICY_DEFAULTS.items():
            low, high = POLICY_RANGES[field]
            raw = value.get(field, default)
            if isinstance(raw, bool) or not isinstance(raw, int) or not low <= raw <= high:
                raise InvalidTenantProfileError(
                    f"{field} must be an integer between {low} and {high}"
                )
            data[field] = raw
        return cls(**data)

    def to_mapping(self) -> dict[str, int]:
        return {
            "booking_horizon_days": self.booking_horizon_days,
            "min_rental_minutes": self.min_rental_minutes,
            "max_rental_days": self.max_rental_days,
            "cancellation_free_hours": self.cancellation_free_hours,
            "reminder_hours_before": self.reminder_hours_before,
            "tickets_per_rental_per_day": self.tickets_per_rental_per_day,
            "lot_photos_max": self.lot_photos_max,
            "verification_docs_retention_days": self.verification_docs_retention_days,
        }


@dataclass(frozen=True)
class TenantProfile(Entity):
    name: EntityName
    slug: Slug
    timezone: str
    currency: str
    logo_url: str | None
    primary_color: str
    vapid_public_key: str | None
    policies: TenantPolicies

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, EntityName) or not isinstance(self.slug, Slug):
            raise InvalidTenantProfileError("name and slug must be value objects")
        if not isinstance(self.timezone, str) or not self.timezone:
            raise InvalidTenantProfileError("timezone must be a non-empty string")
        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isupper()
        ):
            raise InvalidTenantProfileError("currency must be an uppercase three-letter code")
        if self.logo_url is not None and not isinstance(self.logo_url, str):
            raise InvalidTenantProfileError("logo_url must be a string or None")
        if not isinstance(self.primary_color, str) or not COLOR_RE.fullmatch(self.primary_color):
            raise InvalidTenantProfileError("primary_color must be a hex color")
        if self.vapid_public_key is not None and not isinstance(self.vapid_public_key, str):
            raise InvalidTenantProfileError("vapid_public_key must be a string or None")
        if not isinstance(self.policies, TenantPolicies):
            raise InvalidTenantProfileError("policies must be TenantPolicies")
