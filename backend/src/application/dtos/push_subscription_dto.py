from datetime import UTC, datetime, timedelta
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from src.infrastructure.push.subscription import (
    MAX_PUSH_ENDPOINT_LENGTH,
    validate_push_subscription,
)

_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_EXPIRATION_MILLISECONDS = 253_402_300_799_999


class PushSubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    p256dh: str = Field(max_length=88, repr=False)
    auth: str = Field(max_length=24, repr=False)


class UpsertPushSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    endpoint: str = Field(max_length=MAX_PUSH_ENDPOINT_LENGTH, repr=False)
    keys: PushSubscriptionKeys = Field(repr=False)
    expiration_time: Annotated[
        StrictInt | None,
        Field(alias="expirationTime", gt=0, le=_MAX_EXPIRATION_MILLISECONDS),
    ] = None

    @model_validator(mode="after")
    def validate_subscription(self) -> Self:
        validate_push_subscription(self.endpoint, self.keys.p256dh, self.keys.auth)
        return self

    @property
    def expires_at(self) -> datetime | None:
        if self.expiration_time is None:
            return None
        return _UNIX_EPOCH + timedelta(milliseconds=self.expiration_time)


class PushSubscriptionResponse(BaseModel):
    id: UUID
    endpoint_hash: str
    expiration_time: datetime | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime
