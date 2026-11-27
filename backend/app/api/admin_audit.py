from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import require_permission
from app.api.deps import get_db_session
from src.application.dtos.audit_dto import AuditLogEntryDTO, AuditLogPageDTO
from src.application.services.audit import (
    ALLOWED_ACTIONS,
    ALLOWED_ENTITY_TYPES,
    AuditEntry,
)
from src.infrastructure.postgres.repositories.audit_repository import AuditRepository


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/audit-log",
    tags=["admin-audit"],
    dependencies=[
        Depends(require_permission("audit.view")),
        Depends(no_store),
    ],
)


def _filter_signature(
    *,
    actor_id: UUID | None,
    action: str | None,
    entity_type: str | None,
    entity_id: UUID | None,
    from_at: datetime | None,
    to_at: datetime | None,
) -> str:
    raw = json.dumps(
        {
            "actor_id": str(actor_id) if actor_id else None,
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "from": from_at.isoformat() if from_at else None,
            "to": to_at.isoformat() if to_at else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _encode_cursor(entry: AuditEntry, signature: str) -> str:
    payload = {
        "t": entry.created_at.isoformat(),
        "i": str(entry.id),
        "f": signature,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, signature: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or payload.get("f") != signature:
            raise ValueError("cursor filters do not match")
        raw_timestamp = payload["t"]
        raw_id = payload["i"]
        if not isinstance(raw_timestamp, str) or not isinstance(raw_id, str):
            raise ValueError("invalid cursor payload")
        timestamp = datetime.fromisoformat(raw_timestamp)
        if timestamp.tzinfo is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        return timestamp, UUID(raw_id)
    except (ValueError, KeyError, binascii.Error, RecursionError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": {"cursor": "invalid cursor"}},
        ) from exc


@router.get("", response_model=AuditLogPageDTO)
async def list_audit_log(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor_id: Annotated[UUID | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=32)] = None,
    entity_id: Annotated[UUID | None, Query()] = None,
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> AuditLogPageDTO:
    if (entity_type is None) != (entity_id is None):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"entity": "entity_type and entity_id must be used together"},
            },
        )
    if action is not None and action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": {"action": "unknown action"}},
        )
    if entity_type is not None and entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"entity_type": "unknown entity type"},
            },
        )
    for name, value in (("from", from_at), ("to", to_at)):
        if value is not None and value.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "validation_error",
                    "fields": {name: "timezone-aware datetime is required"},
                },
            )
    if from_at is not None and to_at is not None and from_at >= to_at:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": {"from": "from must be before to"}},
        )
    signature = _filter_signature(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        from_at=from_at,
        to_at=to_at,
    )
    before = _decode_cursor(cursor, signature) if cursor is not None else None
    entries = await AuditRepository(session).list_entries(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        from_at=from_at,
        to_at=to_at,
        before=before,
        limit=limit + 1,
    )
    has_more = len(entries) > limit
    page = entries[:limit]
    return AuditLogPageDTO(
        items=[AuditLogEntryDTO.from_entry(entry) for entry in page],
        next_cursor=_encode_cursor(page[-1], signature) if has_more and page else None,
    )
