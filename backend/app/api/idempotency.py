import hmac
import json
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, Response
from pydantic import UUID4, BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.config import Settings
from src.infrastructure.postgres.repositories.idempotency_repository import IdempotencyRepository
from src.infrastructure.security.secret_box import derive_key

IdempotencyKey = Annotated[UUID4, Header(alias="Idempotency-Key")]
REPLAY_RESPONSE_HEADERS = {
    "Idempotent-Replayed": {
        "description": "Present with value true when a stored response is replayed.",
        "schema": {"type": "string", "enum": ["true"]},
    },
}


class RequestIdempotency:
    def __init__(self, repository: IdempotencyRepository, settings: Settings) -> None:
        self._repository = repository
        self._secret = settings.security_key or settings.jwt_secret
        self._previous = settings.security_previous_keys

    async def replay(
        self,
        user_id: UUID,
        key: UUID,
        operation: str,
        payload: BaseModel,
        response: Response,
    ) -> dict[str, Any] | None:
        message = json.dumps(
            [operation, payload.model_dump(mode="json")], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        request_hash = _request_hash(self._secret, message)
        existing = await self._repository.reserve(user_id, key, request_hash)
        if existing is None:
            return None
        if not hmac.compare_digest(existing.request_hash, request_hash) and not any(
            hmac.compare_digest(existing.request_hash, _request_hash(secret, message))
            for secret in self._previous.values()
        ):
            raise HTTPException(status_code=422, detail={"code": "idempotency_conflict"})
        response.headers["Idempotent-Replayed"] = "true"
        return existing.response

    async def save(self, user_id: UUID, key: UUID, result: BaseModel) -> None:
        await self._repository.save(user_id, key, result.model_dump(mode="json"))


def _request_hash(secret: str, message: bytes) -> str:
    return hmac.digest(derive_key(secret, info="idempotency"), message, "sha256").hex()


def get_idempotency(
    request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]
) -> RequestIdempotency:
    settings = cast(Settings, request.app.state.settings)
    return RequestIdempotency(IdempotencyRepository(session), settings)


Idempotency = Annotated[RequestIdempotency, Depends(get_idempotency)]
