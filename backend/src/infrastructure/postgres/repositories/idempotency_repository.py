from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.idempotency_key_record import IdempotencyKeyRecord


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def reserve(
        self, user_id: UUID, key: UUID, request_hash: str
    ) -> IdempotencyKeyRecord | None:
        table = IdempotencyKeyRecord
        statement = (
            insert(table)
            .values(
                tenant_id=self._tenant_id,
                user_id=user_id,
                key=key,
                request_hash=request_hash,
                expires_at=func.clock_timestamp() + timedelta(hours=24),
            )
            .on_conflict_do_update(
                index_elements=[table.tenant_id, table.user_id, table.key],
                set_={
                    "request_hash": request_hash,
                    "response": None,
                    "expires_at": func.clock_timestamp() + timedelta(hours=24),
                },
                where=table.expires_at <= func.clock_timestamp(),
            )
            .returning(table.key)
        )
        if await self._session.scalar(statement) is not None:
            return None

        # The upsert has waited on any concurrent writer and locked the existing row.
        # A new statement reads the committed response under READ COMMITTED.
        record = await self._session.get(table, (self._tenant_id, user_id, key))
        if record is None or record.response is None:
            raise RuntimeError("Missing committed idempotency response")
        return record

    async def save(self, user_id: UUID, key: UUID, response: dict[str, Any]) -> None:
        table = IdempotencyKeyRecord
        await self._session.execute(
            update(table)
            .where(table.tenant_id == self._tenant_id, table.user_id == user_id, table.key == key)
            .values(response=response)
        )
