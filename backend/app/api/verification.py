from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.audit_deps import StaffAudit
from app.api.auth_deps import get_current_user, require_permission, verify_csrf
from app.api.deps import get_db_session
from app.api.files import get_upload_storage
from app.api.idempotency import REPLAY_RESPONSE_HEADERS, Idempotency, IdempotencyKey
from app.errors import problem_response
from src.application.dtos.verification_dto import (
    AdminVerificationRequestSummary,
    CreateVerificationRequest,
    MyVerificationRequest,
    VerificationDecisionRequest,
    VerificationDocument,
    VerificationPassport,
    VerificationRequest,
    VerificationRequestPage,
    VerificationRequestSummary,
)
from src.application.services.outbox import OutboxWriter
from src.application.services.uploads import StorageUnavailableError
from src.domain.entities.user_account import UserAccount, VerificationStatus
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository
from src.infrastructure.postgres.repositories.verification_repository import VerificationRepository
from src.infrastructure.security.secret_box import SecretBox

_VALIDATION_FIELDS = frozenset(
    {
        "passport",
        "full_name",
        "birth_date",
        "passport_number",
        "issued_by",
        "documents",
        "verification_passport",
        "verification_registration",
        "verification_selfie",
        "decision",
        "comment",
        "version",
        "id",
        "status",
        "limit",
        "offset",
        "Idempotency-Key",
    }
)


class PrivateVerificationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # Unexpected input keys can themselves contain passport data.
                fields: dict[str, str] = {}
                for error in exc.errors():
                    path = [str(part) for part in error.get("loc", ())[1:]]
                    known_path = path and all(part in _VALIDATION_FIELDS for part in path)
                    fields[".".join(path) if known_path else "body"] = "invalid value"
                return problem_response(request, 422, "validation_error", fields=fields)

        return safe_handler


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


me_router = APIRouter(
    prefix="/api/v1/me/verification-requests",
    tags=["me-verification"],
    route_class=PrivateVerificationRoute,
    dependencies=[Depends(no_store)],
)
admin_router = APIRouter(
    prefix="/api/v1/admin/verification-requests",
    tags=["admin-verification"],
    route_class=PrivateVerificationRoute,
    dependencies=[Depends(require_permission("verification.review")), Depends(no_store)],
)

Session = Annotated[AsyncSession, Depends(get_db_session)]
Actor = Annotated[UserAccount, Depends(get_current_user)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)]


def _problem(status_code: int, code: str, *, fields: dict[str, str] | None = None) -> HTTPException:
    detail: dict[str, object] = {"code": code}
    if fields:
        detail["fields"] = fields
    return HTTPException(status_code=status_code, detail=detail)


def _passport_context(tenant_id: UUID, request_id: UUID) -> str:
    return f"verification-passport:{tenant_id}:{request_id}"


def _secret_box(request: Request) -> SecretBox:
    secret_box = cast(SecretBox | None, getattr(request.app.state, "secret_box", None))
    if secret_box is None:
        raise _problem(503, "service_unavailable")
    return secret_box


async def _signed_documents(
    request: Request, repository: VerificationRepository, request_id: UUID, user_id: UUID
) -> list[VerificationDocument]:
    documents = await repository.document_keys(request_id, user_id)
    if not documents:
        return []
    try:
        storage = await run_in_threadpool(get_upload_storage, request)
        return [
            VerificationDocument(purpose=purpose, url=await storage.signed_url(key, public=False))
            for purpose, key in documents
        ]
    except StorageUnavailableError:
        raise _problem(503, "service_unavailable") from None


@me_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    operation_id="createMyVerificationRequest",
    dependencies=[Depends(verify_csrf)],
    responses={
        201: {"headers": REPLAY_RESPONSE_HEADERS},
        409: {"description": "An active verification request already exists"},
    },
)
async def create_my_request(
    request: Request,
    response: Response,
    payload: CreateVerificationRequest,
    actor: Actor,
    session: Session,
    key: IdempotencyKey,
    idempotency: Idempotency,
) -> VerificationRequestSummary:
    cached = await idempotency.replay(actor.id, key, "me.verification.create", payload, response)
    if cached is not None:
        return VerificationRequestSummary.model_validate(cached)

    repository = VerificationRepository(session)
    user = await repository.lock_user(actor.id)
    if user is None or not user.is_active:
        raise _problem(403, "forbidden_role")
    if user.verification_status == "approved" or await repository.has_active_request(user.id):
        raise _problem(409, "conflict")

    documents = payload.documents.by_purpose()
    invalid = await repository.invalid_documents(user.id, documents)
    if invalid:
        raise _problem(
            422,
            "validation_error",
            fields={f"documents.{purpose}": "invalid verification document" for purpose in invalid},
        )

    request_id = uuid4()
    passport_enc = _secret_box(request).encrypt(
        payload.passport.model_dump_json(),
        context=_passport_context(repository.tenant_id, request_id),
    )
    result = await repository.create(request_id, user, passport_enc, documents)
    await idempotency.save(actor.id, key, result)
    return result


@me_router.get("", operation_id="listMyVerificationRequests")
async def list_my_requests(
    actor: Actor, session: Session, limit: PageLimit = 20, offset: PageOffset = 0
) -> VerificationRequestPage[VerificationRequestSummary]:
    return await VerificationRepository(session).list_own(actor.id, limit=limit, offset=offset)


@me_router.get(
    "/{id}",
    operation_id="getMyVerificationRequest",
    responses={404: {"description": "Verification request was not found"}},
)
async def get_my_request(
    id: UUID, request: Request, actor: Actor, session: Session
) -> MyVerificationRequest:
    repository = VerificationRepository(session)
    summary = await repository.get_own(id, actor.id)
    if summary is None:
        raise _problem(404, "not_found")
    documents = await _signed_documents(request, repository, id, actor.id)
    return MyVerificationRequest(**summary.model_dump(), documents=documents)


@admin_router.get("", operation_id="listVerificationRequests")
async def list_requests(
    session: Session,
    status: VerificationStatus | None = None,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> VerificationRequestPage[AdminVerificationRequestSummary]:
    return await VerificationRepository(session).list_admin(
        status=status, limit=limit, offset=offset
    )


@admin_router.get(
    "/{id}",
    operation_id="getVerificationRequest",
    responses={404: {"description": "Verification request was not found"}},
)
async def get_request(id: UUID, request: Request, session: Session) -> VerificationRequest:
    repository = VerificationRepository(session)
    record = await repository.get_admin(id)
    if record is None:
        raise _problem(404, "not_found")
    summary, passport_enc = record
    secret_box = _secret_box(request)
    try:
        passport = VerificationPassport.model_validate_json(
            secret_box.decrypt(passport_enc, context=_passport_context(repository.tenant_id, id))
        )
    except ValueError:
        raise _problem(500, "internal_error") from None
    documents = await _signed_documents(request, repository, id, summary.user.id)
    return VerificationRequest(**summary.model_dump(), passport=passport, documents=documents)


@admin_router.post(
    "/{id}/decision",
    operation_id="decideVerificationRequest",
    dependencies=[Depends(verify_csrf)],
    responses={
        404: {"description": "Verification request was not found"},
        409: {"description": "Verification request was already processed or the version is stale"},
    },
)
async def decide_request(
    id: UUID,
    payload: VerificationDecisionRequest,
    actor: Actor,
    session: Session,
    audit: Annotated[StaffAudit, Depends()],
) -> AdminVerificationRequestSummary:
    if payload.decision == "rejected" and not payload.comment:
        raise _problem(422, "validation_error", fields={"comment": "required for rejection"})

    repository = VerificationRepository(session)
    locked = await repository.lock_request_for_decision(id)
    if locked is None:
        raise _problem(404, "not_found")
    record, user = locked
    if record.status != "pending":
        raise _problem(409, "already_processed")
    if record.version != payload.version:
        raise _problem(409, "stale_version")

    result = repository.decide(
        record,
        user,
        reviewer_id=actor.id,
        decision=payload.decision,
        comment=payload.comment or None,
    )
    await audit.record(
        action="verification.decided",
        entity_type="verification_request",
        entity_id=id,
        metadata={"decision": payload.decision},
    )
    await OutboxWriter(OutboxRepository(session)).enqueue(
        event_type=f"verification.{payload.decision}", entity_id=id, user_id=user.id
    )
    return result
