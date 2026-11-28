from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import DateTime, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.audit_deps import StaffAudit
from app.api.auth_deps import get_current_user, verify_csrf
from app.api.deps import get_db_session
from app.api.files import get_upload_storage
from app.api.idempotency import REPLAY_RESPONSE_HEADERS, Idempotency, IdempotencyKey
from app.models import User
from src.application.dtos.ticket_dto import CreateTicketRequest, Ticket, TicketPage, TicketReceipt
from src.application.services.outbox import OutboxWriter
from src.application.services.uploads import StorageUnavailableError
from src.domain.entities.user_account import UserAccount
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.models.ticket_record import TicketRecord, TicketStatus
from src.infrastructure.postgres.repositories.admin_settings_repository import (
    AdminSettingsRepository,
)
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository
from src.infrastructure.postgres.repositories.rental_repository import RentalRepository
from src.infrastructure.postgres.repositories.ticket_repository import (
    TicketDetails,
    TicketRepository,
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/me",
    tags=["tickets"],
    dependencies=[Depends(no_store)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Access denied"},
    },
)
Actor = Annotated[UserAccount, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_db_session)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)]


async def ticket_with_photos(
    request: Request, repository: TicketRepository, details: TicketDetails
) -> Ticket:
    record, lot, user = details
    records = (await repository.photos_for_tickets([record.id])).get(record.id, [])
    if not records:
        return Ticket.from_records(record, lot, user)
    try:
        storage = await run_in_threadpool(get_upload_storage, request)
        urls = [await storage.signed_url(photo.object_key, public=False) for photo in records]
    except StorageUnavailableError:
        raise HTTPException(503, detail={"code": "service_unavailable"}) from None
    return Ticket.from_records(record, lot, user, photo_urls=urls)


@router.post(
    "/rentals/{id}/tickets",
    operation_id="createRentalTicket",
    status_code=201,
    dependencies=[Depends(verify_csrf)],
    responses={
        201: {"headers": REPLAY_RESPONSE_HEADERS},
        404: {"description": "Rental not found"},
        409: {"description": "rental_not_active"},
        429: {"description": "issue_limit_exceeded"},
    },
)
async def create_ticket(
    id: UUID,
    payload: CreateTicketRequest,
    actor: Actor,
    session: Session,
    key: IdempotencyKey,
    idempotency: Idempotency,
    response: Response,
    audit: Annotated[StaffAudit, Depends()],
) -> TicketReceipt:
    cached = await idempotency.replay(
        actor.id, key, f"me.rentals.{id}.tickets.create", payload, response
    )
    if cached is not None:
        return TicketReceipt.model_validate(cached)
    tenant_id = UUID(str(session.info["tenant_id"]))
    current = await session.scalar(
        select(User)
        .where(User.id == actor.id, User.tenant_id == tenant_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if current is None or not current.is_active:
        raise HTTPException(403, detail={"code": "forbidden_role"})
    if current.verification_status != "approved":
        raise HTTPException(403, detail={"code": "verification_required"})
    rental = await RentalRepository(session).lock(id, user_id=actor.id)
    if rental is None:
        raise HTTPException(404, detail={"code": "not_found"})
    if rental.status not in ("active", "overdue"):
        raise HTTPException(409, detail={"code": "rental_not_active"})

    settings = await AdminSettingsRepository(session).get()
    assert settings is not None
    now = await session.scalar(select(func.clock_timestamp(type_=DateTime(timezone=True))))
    assert isinstance(now, datetime)
    now = now.astimezone(UTC)
    repository = TicketRepository(session)
    count = await repository.count_for_rental(id, start=now - timedelta(hours=24), end=now)
    if count >= settings.policies.tickets_per_rental_per_day:
        raise HTTPException(429, detail={"code": "issue_limit_exceeded"})
    valid = await repository.lock_photo_ids(actor.id, payload.file_ids)
    file_ids = [file_id for file_id in payload.file_ids if file_id in valid]
    record = TicketRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        rental_id=id,
        category=payload.category,
        description=payload.description,
        skipped_photo_count=payload.photo_upload_failures + len(payload.file_ids) - len(file_ids),
        status="submitted",
        created_at=now,
        updated_at=now,
        version=1,
    )
    await repository.add(record, file_ids=file_ids)

    await audit.record(action="ticket.created", entity_type="ticket", entity_id=record.id)
    recipients = await session.scalars(
        select(User.id)
        .where(
            User.tenant_id == tenant_id, User.is_active.is_(True), User.role.in_(("admin", "owner"))
        )
        .order_by(User.id)
    )
    writer = OutboxWriter(OutboxRepository(session))
    for staff_id in recipients:
        await writer.enqueue(
            event_type="ticket.created.admin", entity_id=record.id, user_id=staff_id
        )
    result = TicketReceipt(
        id=record.id,
        rental_id=record.rental_id,
        created_at=record.created_at,
        skipped_photo_count=record.skipped_photo_count,
        version=record.version,
    )
    await idempotency.save(actor.id, key, result)
    return result


@router.get("/tickets", operation_id="listMyTickets")
async def list_my_tickets(
    actor: Actor,
    session: Session,
    status: TicketStatus | None = None,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> TicketPage:
    records, total = await TicketRepository(session).list_page(
        user_id=actor.id, status=status, limit=limit, offset=offset
    )
    return TicketPage(
        items=[Ticket.from_records(*item) for item in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/tickets/{id}",
    operation_id="getMyTicket",
    responses={
        404: {"description": "Ticket not found"},
        503: {"description": "Photo storage unavailable"},
    },
)
async def get_my_ticket(id: UUID, request: Request, actor: Actor, session: Session) -> Ticket:
    repository = TicketRepository(session)
    details = await repository.get_details(id, user_id=actor.id)
    if details is None:
        raise HTTPException(404, detail={"code": "not_found"})
    return await ticket_with_photos(request, repository, details)
