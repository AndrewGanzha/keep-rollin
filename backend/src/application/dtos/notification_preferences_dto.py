from collections.abc import Mapping
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from src.domain.entities.notification_preferences import (
    applicable_events,
    email_allowed,
    locked_events,
    push_enabled,
)


class NotificationPreferencesResponse(BaseModel):
    push_enabled: bool
    email_by_event: dict[str, bool]
    locked_events: list[str]

    @classmethod
    def from_state(cls, values: Mapping[str, object], role: str) -> Self:
        return cls(
            push_enabled=push_enabled(values),
            email_by_event={
                event: email_allowed(values, event, role) for event in applicable_events(role)
            },
            locked_events=list(locked_events(role)),
        )


class UpdateNotificationPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    push_enabled: StrictBool = True
    email_by_event: dict[str, StrictBool] = Field(default_factory=dict)


class NotificationPreferencesSummary(BaseModel):
    push_enabled: bool
