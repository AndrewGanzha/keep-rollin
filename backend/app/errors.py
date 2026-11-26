from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")

PROBLEM_CONTENT_TYPE = "application/problem+json"

ERROR_TITLES: dict[str, str] = {
    "tenant_not_found": "Tenant not found",
    "not_found": "Not found",
    "validation_error": "Validation error",
    "internal_error": "Internal error",
    "service_unavailable": "Service unavailable",
    "forbidden_role": "Forbidden",
    "token_invalid": "Unauthorized",
    "conflict": "Conflict",
    "method_not_allowed": "Method not allowed",
    "rate_limited": "Too many requests",
    "payload_too_large": "Payload too large",
    "unsupported_media_type": "Unsupported media type",
}


def get_trace_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


def problem_response(
    request: Request,
    status: int,
    code: str,
    *,
    title: str | None = None,
    detail: str | None = None,
    fields: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> JSONResponse:
    try:
        default_title = HTTPStatus(status).phrase
    except ValueError:
        default_title = "Error"

    payload: dict[str, Any] = {
        "type": f"urn:keeprollin:error:{code}",
        "title": title or ERROR_TITLES.get(code, default_title),
        "status": status,
        "code": code,
        "trace_id": get_trace_id(request),
    }
    if detail:
        payload["detail"] = detail
    if fields:
        payload["fields"] = dict(fields)
    response = JSONResponse(
        status_code=status,
        content=payload,
        media_type=PROBLEM_CONTENT_TYPE,
    )
    if request.url.path.startswith(("/api/v1/auth", "/api/v1/me", "/api/v1/admin")):
        response.headers["Cache-Control"] = "no-store"
    if isinstance(headers, Mapping):
        response.headers.update(headers)
    elif headers:
        response.raw_headers.extend(
            (key.encode("latin-1"), value.encode("latin-1")) for key, value in headers
        )
    return response


def _code_for_status(status: int) -> str:
    return {
        400: "validation_error",
        401: "token_invalid",
        403: "forbidden_role",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        415: "unsupported_media_type",
        422: "validation_error",
        429: "rate_limited",
        503: "service_unavailable",
    }.get(status, "internal_error")


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    detail = exc.detail
    code = _code_for_status(exc.status_code)
    message: str | None = None
    fields: Mapping[str, str] | None = None

    if isinstance(detail, Mapping):
        raw_code = detail.get("code")
        if isinstance(raw_code, str):
            code = raw_code
        raw_detail = detail.get("detail")
        if isinstance(raw_detail, str):
            message = raw_detail
        raw_fields = detail.get("fields")
        if isinstance(raw_fields, Mapping):
            fields = {str(key): str(value) for key, value in raw_fields.items()}
    elif isinstance(detail, str):
        message = detail

    if exc.status_code == 500:
        message = None
        fields = None
        code = "internal_error"
    elif exc.status_code >= 500:
        message = None
        fields = None

    return problem_response(
        request,
        exc.status_code,
        code,
        detail=message,
        fields=fields,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    fields: dict[str, str] = {}
    for error in exc.errors():
        parts = list(error.get("loc", ()))
        if parts and parts[0] in ("body", "query", "path", "header", "cookie"):
            parts = parts[1:]
        location = ".".join(str(part) for part in parts)
        fields[location or "body"] = str(error.get("msg", "invalid value"))

    return problem_response(
        request,
        422,
        "validation_error",
        fields=fields,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled application error",
        extra={"request_id": get_trace_id(request), "path": request.url.path},
    )
    return problem_response(request, 500, "internal_error")


def register_exception_handlers(application: FastAPI) -> None:
    # Starlette's signature is broader than the concrete exception classes used here.
    application.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(Exception, unhandled_exception_handler)
