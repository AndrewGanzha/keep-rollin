from contextlib import suppress
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.auth_deps import get_current_user, verify_csrf
from app.api.deps import get_db_session
from app.config import Settings
from app.errors import problem_response
from src.application.dtos.file_dto import UploadResultDTO
from src.application.services.uploads import (
    MAX_DOCUMENT_BYTES,
    MAX_PHOTO_BYTES,
    InvalidUploadError,
    StorageUnavailableError,
    UploadPurpose,
    UploadStorage,
    UploadTooLargeError,
    prepare_upload,
)
from src.domain.entities.user_account import UserAccount
from src.infrastructure.postgres.models.file_record import FileRecord
from src.infrastructure.storage.s3 import build_upload_storage

# Cap the stream before multipart parsing, with room for headers and the purpose field.
MAX_MULTIPART_BYTES = MAX_DOCUMENT_BYTES + 64 * 1024

UPLOAD_PATH = "/api/v1/files"
router = APIRouter(prefix=UPLOAD_PATH, tags=["files"])


class UploadLengthMiddleware(BaseHTTPMiddleware):
    """Use the API problem format for the native limiter's early header check."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        root_path = str(request.scope.get("root_path", ""))
        path = request.url.path
        if root_path and path.startswith(f"{root_path}/"):
            path = path[len(root_path) :]
        if request.method == "POST" and path.rstrip("/") == UPLOAD_PATH:
            length = request.headers.get("Content-Length")
            if length is not None:
                with suppress(ValueError):
                    if int(length) > MAX_MULTIPART_BYTES:
                        return problem_response(
                            request,
                            413,
                            "payload_too_large",
                            headers={"Cache-Control": "no-store"},
                        )
        return await call_next(request)


def _upload_problem(status: int, code: str) -> HTTPException:
    return HTTPException(
        status_code=status, detail={"code": code}, headers={"Cache-Control": "no-store"}
    )


def get_upload_storage(request: Request) -> UploadStorage:
    state = request.app.state
    existing = cast(UploadStorage | None, getattr(state, "upload_storage", None))
    if existing is None:
        existing = build_upload_storage(cast(Settings, state.settings))
        state.upload_storage = existing
    return existing


@router.post(
    "",
    status_code=201,
    response_model=UploadResultDTO,
    max_body_size=MAX_MULTIPART_BYTES,
    dependencies=[Depends(verify_csrf)],
    responses={
        413: {"description": "Upload exceeds the file or multipart size limit"},
        503: {"description": "Object storage is unavailable"},
    },
)
async def upload_file(
    request: Request,
    response: Response,
    actor: Annotated[UserAccount, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    file: Annotated[UploadFile, File()],
    purpose: Annotated[UploadPurpose, Form()],
) -> UploadResultDTO:
    public = purpose == "lot_photo"
    if public and "catalog.manage" not in actor.permissions:
        raise _upload_problem(403, "forbidden_role")

    limit = MAX_PHOTO_BYTES if purpose in ("lot_photo", "ticket_photo") else MAX_DOCUMENT_BYTES
    data = await file.read(limit + 1)
    try:
        upload = await run_in_threadpool(prepare_upload, data, file.content_type, purpose)
    except UploadTooLargeError as exc:
        raise _upload_problem(413, "payload_too_large") from exc
    except InvalidUploadError as exc:
        raise _upload_problem(422, "upload_invalid") from exc
    except StorageUnavailableError as exc:
        raise _upload_problem(503, "service_unavailable") from exc

    file_id = uuid4()
    tenant_id = UUID(str(session.info["tenant_id"]))
    key = f"{tenant_id}/{file_id}.{upload.extension.removeprefix('.')}"
    try:
        storage = await run_in_threadpool(get_upload_storage, request)
        record = FileRecord(
            id=file_id,
            tenant_id=tenant_id,
            uploaded_by=actor.id,
            purpose=purpose,
            object_key=key,
            content_type=upload.content_type,
            size_bytes=len(upload.data),
            public_url=storage.public_url(key) if public else None,
            is_ready=False,
        )
        session.add(record)
        # Commit a reservation first. A cancelled upload, storage failure or final
        # transaction failure leaves a known key for orphan reconciliation.
        await session.commit()
        # Hold the reservation during the write so cleanup cannot overtake it.
        locked_id = await session.scalar(
            select(FileRecord.id)
            .where(FileRecord.id == file_id, FileRecord.is_purging.is_(False))
            .with_for_update()
        )
        if locked_id is None:
            raise StorageUnavailableError("Upload reservation expired")
        await storage.put(key, upload, public=public)
        url = await storage.signed_url(key, public=public)
    except StorageUnavailableError as exc:
        raise _upload_problem(503, "service_unavailable") from exc

    record.is_ready = True
    await session.flush()
    response.headers["Cache-Control"] = "no-store"
    return UploadResultDTO(file_id=file_id, url=url)
