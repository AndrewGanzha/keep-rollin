from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl
from uuid import UUID

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from src.application.dtos.lot_dto import LotDTO, RentalUnit
from src.domain.entities.lot import LotStatus
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.domain.value_objects.price import PriceTier

MAX_LOT_NAME_LENGTH = 120
MAX_LOT_SLUG_LENGTH = 80
LotName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_LOT_NAME_LENGTH)
]
LotSlug = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_LOT_SLUG_LENGTH, pattern=r"^[a-z0-9-]+$")
]
Duration = Annotated[int, Field(strict=True, ge=1, le=365)]
AllowedDurationsInput = Annotated[list[Duration], Field(min_length=1, max_length=365)]

_HTTP_URL = TypeAdapter(AnyHttpUrl)


def _valid_text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("NUL characters are not allowed")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("text must contain valid Unicode") from exc
    return value


def _photo_url(value: str) -> str:
    value = _valid_text(value).strip()
    if not value.lower().startswith(("http://", "https://")) or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError("photo URLs must be absolute HTTP(S) URLs")
    url = _HTTP_URL.validate_python(value)
    if url.username is not None or url.password is not None:
        raise ValueError("photo URLs must not contain credentials")
    sensitive_keys = {"x-amz-signature", "awsaccesskeyid", "x-goog-signature", "googleaccessid"}
    if any(
        key.lower() in sensitive_keys
        for key, _ in parse_qsl(url.query or "", keep_blank_values=True)
    ):
        raise ValueError("photo URLs must not contain a storage signature")
    # Retain the exact URL so existing links and percent-encoded paths round-trip.
    return value


PhotoUrl = Annotated[str, Field(max_length=2048), AfterValidator(_photo_url)]


def _characteristic_value(value: object) -> str | int | float:
    if isinstance(value, str):
        return _valid_text(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a string or a number")
    maximum = 10**308 if isinstance(value, int) else 1e308
    if not -maximum <= value <= maximum:
        raise ValueError("number must be finite and within the supported range")
    return value


CharacteristicValue = Annotated[str | int | float, BeforeValidator(_characteristic_value)]


def _valid_characteristic_keys(value: object) -> object:
    if isinstance(value, dict):
        for key in value:
            if isinstance(key, str):
                _valid_text(key)
    return value


CharacteristicsInput = Annotated[
    dict[str, CharacteristicValue], BeforeValidator(_valid_characteristic_keys)
]


class LotVariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    battery_count: int = Field(strict=True, ge=0, le=MAX_DATABASE_INTEGER)
    is_active: bool = Field(default=True, strict=True)
    price_tiers: list[PriceTier] = Field(min_length=1)


VariantsInput = Annotated[list[LotVariantInput], Field(min_length=1)]


class LotPhotoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photos: list[PhotoUrl] | None = Field(default=None, max_length=20)
    file_ids: list[UUID] | None = Field(default=None, max_length=20)

    @field_validator("photos", "file_ids", mode="before")
    @classmethod
    def reject_null_photos(cls, value: object) -> object:
        if value is None:
            raise ValueError("provide a list or omit this field")
        return value

    @field_validator("name", "description", "battery_type", check_fields=False)
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return _valid_text(value) if value is not None else None


class CreateLotRequest(LotPhotoInput):
    name: LotName
    category_id: UUID
    description: str | None = None
    slug: LotSlug | None = None
    rental_unit: RentalUnit
    battery_type: str | None = None
    variants: VariantsInput
    allowed_durations: AllowedDurationsInput
    characteristics: CharacteristicsInput
    status: Literal["active", "archived"] = "active"


class BulkLotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: CreateLotRequest
    count: int = Field(strict=True, ge=1, le=50)


class BulkLotResponse(BaseModel):
    items: list[LotDTO]


ManualLotStatus = Literal["active", "archived", "maintenance"]


class LotStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ManualLotStatus


class UpdateLotRequest(LotPhotoInput):
    version: int = Field(strict=True, ge=1)
    name: LotName | None = None
    category_id: UUID | None = None
    description: str | None = None
    slug: LotSlug | None = None
    rental_unit: RentalUnit | None = None
    battery_type: str | None = None
    variants: VariantsInput | None = None
    allowed_durations: AllowedDurationsInput | None = None
    characteristics: CharacteristicsInput | None = None
    status: LotStatus | None = None

    @field_validator(
        "name",
        "category_id",
        "slug",
        "rental_unit",
        "variants",
        "allowed_durations",
        "characteristics",
        "status",
        mode="before",
    )
    @classmethod
    def reject_null_changes(cls, value: object) -> object:
        if value is None:
            raise ValueError("field must not be null")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if self.model_fields_set == {"version"}:
            raise ValueError("at least one mutable field must be provided")
        return self
