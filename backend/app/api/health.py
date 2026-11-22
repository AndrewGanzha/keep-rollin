from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db import database_ready

router = APIRouter(tags=["infra"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessChecks(BaseModel):
    database: Literal["ok", "unavailable"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: ReadinessChecks


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Report that the process is alive without touching the database."""
    return HealthResponse()


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Database is not ready"}},
    summary="Readiness probe",
)
async def readyz(request: Request) -> JSONResponse:
    """Report readiness after a real, bounded database check."""
    settings = request.app.state.settings
    ready = await database_ready(settings.database_url, settings.database_timeout_seconds)
    payload = ReadinessResponse(
        status="ok" if ready else "unavailable",
        checks=ReadinessChecks(database="ok" if ready else "unavailable"),
    )
    return JSONResponse(
        status_code=200 if ready else 503,
        content=payload.model_dump(),
    )
