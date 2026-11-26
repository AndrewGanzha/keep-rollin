import re
from typing import Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.application.repositories.i_admin_settings_repository import AdminSettingsState
from src.domain.entities.tenant_profile import TenantPolicies

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class AdminSettingsDTO(BaseModel):
    logo_url: str | None
    primary_color: str
    timezone: str
    currency: str
    vapid_public_key: str | None
    policies: dict[str, int]
    version: int

    @classmethod
    def from_state(cls, state: AdminSettingsState) -> Self:
        return cls(
            logo_url=state.logo_url,
            primary_color=state.primary_color,
            timezone=state.timezone,
            currency=state.currency,
            vapid_public_key=state.vapid_public_key,
            policies=state.policies.to_mapping(),
            version=state.version,
        )


class SettingsPoliciesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_horizon_days: int | None = Field(default=None, ge=1, le=365)
    min_rental_minutes: int | None = Field(default=None, ge=15, le=1440)
    max_rental_days: int | None = Field(default=None, ge=1, le=90)
    cancellation_free_hours: int | None = Field(default=None, ge=0, le=168)
    reminder_hours_before: int | None = Field(default=None, ge=1, le=72)
    tickets_per_rental_per_day: int | None = Field(default=None, ge=1, le=20)
    lot_photos_max: int | None = Field(default=None, ge=1, le=20)
    verification_docs_retention_days: int | None = Field(default=None, ge=30, le=365)


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo_url: str | None = None
    primary_color: str | None = Field(default=None, pattern=COLOR_RE.pattern)
    timezone: str | None = None
    currency: str | None = Field(default=None, pattern=CURRENCY_RE.pattern)
    policies: SettingsPoliciesPatch | None = None
    version: int = Field(ge=1)

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > 2048 or "\x00" in value:
            raise ValueError("logo_url is invalid")
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("logo_url must be an absolute http(s) URL")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA name") from exc
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        mutable = {"logo_url", "primary_color", "timezone", "currency", "policies"}
        if not self.model_fields_set & mutable:
            raise ValueError("at least one settings field must be provided")
        for field in ("primary_color", "timezone", "currency", "policies"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


def merge_policies(current: TenantPolicies, patch: SettingsPoliciesPatch | None) -> TenantPolicies:
    if patch is None:
        return current
    values: dict[str, object] = dict(current.to_mapping())
    values.update(patch.model_dump(exclude_unset=True))
    return TenantPolicies.from_mapping(values)
