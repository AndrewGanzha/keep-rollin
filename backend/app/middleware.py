from __future__ import annotations

import logging
import time
from uuid import uuid4

from anyio import CancelScope
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.db import configure_session
from app.errors import problem_response
from app.tenancy import (
    REQUEST_ID_RE,
    TenantResolver,
    is_infra_request,
    tenant_candidates,
)

access_logger = logging.getLogger("app.access")
error_logger = logging.getLogger("app.errors")


def request_id_from(request: Request) -> str:
    supplied = request.headers.get("X-Request-Id")
    if supplied and REQUEST_ID_RE.fullmatch(supplied):
        return supplied
    return uuid4().hex


async def commit_and_close(session: AsyncSession) -> None:
    with CancelScope(shield=True):
        try:
            await session.commit()
        finally:
            await session.close()


async def rollback_and_close(session: AsyncSession) -> None:
    with CancelScope(shield=True):
        try:
            await session.rollback()
        finally:
            await session.close()


async def finalize_session(response: Response, session: AsyncSession) -> Response:
    """Finalize the transaction before the response is sent.

    BaseHTTPMiddleware exposes every response as a body iterator. For the MVP we
    buffer that body so commit/rollback and close happen before headers are sent.
    A future true-streaming endpoint must use its own session lifecycle.
    """
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is None:
        if response.status_code < 400:
            await commit_and_close(session)
        else:
            await rollback_and_close(session)
        return response

    try:
        chunks = [chunk async for chunk in body_iterator]
    except BaseException:
        await rollback_and_close(session)
        raise

    if response.status_code < 400:
        await commit_and_close(session)
    else:
        await rollback_and_close(session)

    rebuilt = Response(
        content=b"".join(chunks),
        status_code=response.status_code,
        background=response.background,
    )
    rebuilt.raw_headers = [
        (key, value) for key, value in response.raw_headers if key.lower() != b"content-length"
    ]
    return rebuilt


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID, convert unexpected errors and write an access log."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request_id_from(request)
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            error_logger.exception(
                "Unhandled request error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            response = problem_response(request, 500, "internal_error")

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        access_logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "tenant_id": getattr(request.state, "tenant_id", None),
            },
        )
        return response


class TenantMiddleware(BaseHTTPMiddleware):
    """Resolve the tenant for non-infrastructure requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if is_infra_request(request):
            return await call_next(request)

        resolver: TenantResolver | None = getattr(request.app.state, "tenant_resolver", None)
        if resolver is None:
            return problem_response(request, 503, "service_unavailable")

        candidates = tenant_candidates(request, request.app.state.settings)
        if not candidates:
            return problem_response(request, 404, "tenant_not_found")

        tenant_id = None
        try:
            for candidate in candidates:
                tenant_id = await resolver.resolve(candidate)
                if tenant_id is not None:
                    break
        except Exception as exc:
            error_logger.error(
                "Tenant resolution failed",
                extra={
                    "request_id": getattr(request.state, "request_id", ""),
                    "error_type": type(exc).__name__,
                },
            )
            return problem_response(request, 503, "service_unavailable")

        if tenant_id is None:
            return problem_response(request, 404, "tenant_not_found")

        request.state.tenant_id = tenant_id
        settings = request.app.state.settings
        session_factory = getattr(request.app.state, "session_factory", None)
        session: AsyncSession | None = None
        if session_factory is not None:
            session = session_factory()
            configure_session(
                session,
                tenant_id=tenant_id,
                database_role=settings.database_role,
            )
            request.state.db_session = session

        try:
            response = await call_next(request)
        except BaseException:
            if session is not None:
                await rollback_and_close(session)
            raise

        if session is not None:
            return await finalize_session(response, session)
        return response
