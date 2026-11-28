from typing import cast

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession


def get_db_session(request: Request) -> AsyncSession:
    session = cast(AsyncSession | None, getattr(request.state, "db_session", None))
    if session is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "service_unavailable", "detail": "Database session is unavailable"},
        )
    return session
