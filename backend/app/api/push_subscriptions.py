from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import get_current_user, verify_csrf
from app.api.deps import get_db_session
from src.application.dtos.push_subscription_dto import (
    PushSubscriptionResponse,
    UpsertPushSubscriptionRequest,
)
from src.domain.entities.user_account import UserAccount
from src.infrastructure.postgres.models.push_subscription_record import PushSubscriptionRecord
from src.infrastructure.postgres.repositories.push_subscription_repository import (
    PushSubscriptionEndpointConflict,
    PushSubscriptionInactiveActor,
    PushSubscriptionLimitReached,
    PushSubscriptionRepository,
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/me/push-subscriptions",
    tags=["push-subscriptions"],
    dependencies=[Depends(no_store)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Access denied"},
    },
)
Actor = Annotated[UserAccount, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_db_session)]


def _response(record: PushSubscriptionRecord) -> PushSubscriptionResponse:
    return PushSubscriptionResponse(
        id=record.id,
        endpoint_hash=sha256(record.endpoint.encode("ascii")).hexdigest(),
        expiration_time=record.expiration_time,
        user_agent=record.user_agent,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", operation_id="listPushSubscriptions")
async def list_push_subscriptions(actor: Actor, session: Session) -> list[PushSubscriptionResponse]:
    subscriptions = await PushSubscriptionRepository(session).list_for_user(actor.id)
    return [_response(record) for record in subscriptions]


@router.post(
    "",
    operation_id="upsertPushSubscription",
    dependencies=[Depends(verify_csrf)],
    responses={409: {"description": "Subscription conflict or active subscription limit reached"}},
)
async def upsert_push_subscription(
    payload: UpsertPushSubscriptionRequest,
    actor: Actor,
    session: Session,
    request: Request,
) -> PushSubscriptionResponse:
    expires_at = payload.expires_at
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise HTTPException(
            422,
            detail={"code": "validation_error", "fields": {"expirationTime": "Already expired"}},
        )
    user_agent = request.headers.get("user-agent", "").replace("\x00", "")[:512] or None
    try:
        subscription = await PushSubscriptionRepository(session).upsert(
            actor.id,
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_agent=user_agent,
            expiration_time=expires_at,
        )
    except PushSubscriptionInactiveActor:
        raise HTTPException(403, detail={"code": "forbidden_role"}) from None
    except PushSubscriptionEndpointConflict:
        raise HTTPException(409, detail={"code": "conflict"}) from None
    except PushSubscriptionLimitReached:
        raise HTTPException(
            409, detail={"code": "conflict", "detail": "Maximum active subscriptions reached"}
        ) from None
    except SQLAlchemyError:
        # A database error may include bound subscription credentials.
        raise HTTPException(503, detail={"code": "service_unavailable"}) from None
    return _response(subscription)


@router.delete(
    "/{subscription_id}",
    operation_id="deletePushSubscription",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_csrf)],
)
async def delete_push_subscription(subscription_id: UUID, actor: Actor, session: Session) -> None:
    await PushSubscriptionRepository(session).delete(actor.id, subscription_id)
