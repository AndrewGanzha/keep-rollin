from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import get_current_user, verify_csrf
from app.api.deps import get_db_session
from src.application.dtos.notification_preferences_dto import (
    NotificationPreferencesResponse,
    UpdateNotificationPreferencesRequest,
)
from src.domain.entities.notification_preferences import applicable_events, locked_events
from src.domain.entities.user_account import UserAccount
from src.infrastructure.postgres.repositories.notification_preferences_repository import (
    NotificationPreferencesRepository,
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/me/notification-preferences",
    tags=["notification-preferences"],
    dependencies=[Depends(no_store)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Access denied"},
    },
)
Actor = Annotated[UserAccount, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("", operation_id="getNotificationPreferences")
async def get_preferences(actor: Actor, session: Session) -> NotificationPreferencesResponse:
    values = await NotificationPreferencesRepository(session).get(actor.id)
    if values is None:
        raise HTTPException(403, detail={"code": "forbidden_role"})
    return NotificationPreferencesResponse.from_state(values, actor.role)


@router.put(
    "",
    operation_id="updateNotificationPreferences",
    responses={422: {"description": "validation_error or critical_channel_locked"}},
)
async def update_preferences(
    payload: UpdateNotificationPreferencesRequest,
    actor: Actor,
    session: Session,
    _csrf: Annotated[None, Depends(verify_csrf)],
) -> NotificationPreferencesResponse:
    locked = locked_events(actor.role)
    blocked = {
        f"email_by_event.{event}": "This event requires email"
        for event, enabled in payload.email_by_event.items()
        if event in locked and not enabled
    }
    if blocked:
        raise HTTPException(422, detail={"code": "critical_channel_locked", "fields": blocked})

    applicable = applicable_events(actor.role)
    unknown = {
        f"email_by_event.{event}": "Unknown or unavailable notification event"
        for event in payload.email_by_event
        if event not in applicable
    }
    if unknown:
        raise HTTPException(422, detail={"code": "validation_error", "fields": unknown})

    values = await NotificationPreferencesRepository(session).update(
        actor.id,
        push_enabled=payload.push_enabled if "push_enabled" in payload.model_fields_set else None,
        email_by_event=payload.email_by_event,
    )
    if values is None:
        raise HTTPException(403, detail={"code": "forbidden_role"})
    return NotificationPreferencesResponse.from_state(values, actor.role)
