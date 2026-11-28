from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    SQLColumnExpression,
    func,
    insert,
    literal,
    literal_column,
    or_,
    select,
    tuple_,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models import User
from src.application.services.audit import validate_audit_event
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord

# The literal predicates let PostgreSQL use the matching partial indexes.
BOOKED: ColumnElement[str] = literal_column("'booked'")
ACTIVE: ColumnElement[str] = literal_column("'active'")


@dataclass(frozen=True)
class RentalLifecycleResult:
    activated: int
    overdue: int


class RentalLifecycleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def process_batch(
        self, *, now: datetime, limit: int, request_id: str
    ) -> RentalLifecycleResult:
        if limit < 1:
            raise ValueError("rental batch limit must be positive")

        overdue_due = (RentalRecord.status == ACTIVE, RentalRecord.end_time < now)
        activation_due = (
            RentalRecord.status == BOOKED,
            RentalRecord.start_time <= now,
            self._can_activate(),
        )
        overdue_candidates = await self._candidates(
            *overdue_due, order_time=RentalRecord.end_time, limit=limit
        )
        activation_candidates = await self._candidates(
            *activation_due,
            order_time=RentalRecord.start_time,
            limit=limit - len(overdue_candidates),
        )
        candidates = overdue_candidates + activation_candidates
        if not candidates:
            return RentalLifecycleResult(activated=0, overdue=0)

        # The API also acquires the lot before the rental. Acquire the entire batch
        # in ID order and use a fresh statement for the eligibility check.
        lot_ids = {lot_id for _, lot_id in candidates}
        locked_lots = list(
            await self._session.scalars(
                select(LotRecord.id)
                .where(LotRecord.tenant_id == self._tenant_id, LotRecord.id.in_(lot_ids))
                .order_by(LotRecord.id)
                .with_for_update()
            )
        )
        locked_rentals = set(
            await self._session.scalars(
                select(RentalRecord.id)
                .where(
                    RentalRecord.tenant_id == self._tenant_id,
                    RentalRecord.id.in_([rental_id for rental_id, _ in candidates]),
                    RentalRecord.lot_id.in_(locked_lots),
                )
                .order_by(RentalRecord.lot_id, RentalRecord.id)
                .with_for_update()
            )
        )

        overdue = await self._mark_overdue(
            [rental_id for rental_id, _ in overdue_candidates if rental_id in locked_rentals],
            now=now,
            request_id=request_id,
        )
        activated = await self._activate(
            [rental_id for rental_id, _ in activation_candidates if rental_id in locked_rentals],
            now=now,
        )
        return RentalLifecycleResult(activated=activated, overdue=overdue)

    def _can_activate(self) -> ColumnElement[bool]:
        other = aliased(RentalRecord)
        # Probe each lot through its index. Flattening these checks into joins can
        # repeatedly scan unrelated rentals when tenant statistics are stale.
        lot_available = (
            select(LotRecord.id)
            .where(
                LotRecord.tenant_id == RentalRecord.tenant_id,
                LotRecord.id == RentalRecord.lot_id,
                LotRecord.status == ACTIVE,
            )
            .correlate(RentalRecord)
            .scalar_subquery()
            .is_not(None)
        )
        no_preceding_rental = (
            select(other.id)
            .where(
                other.tenant_id == RentalRecord.tenant_id,
                other.lot_id == RentalRecord.lot_id,
                or_(
                    other.status.in_(("active", "overdue")),
                    (other.status == BOOKED)
                    & (
                        tuple_(other.start_time, other.id)
                        < tuple_(RentalRecord.start_time, RentalRecord.id)
                    ),
                ),
            )
            .correlate(RentalRecord)
            .limit(1)
            .scalar_subquery()
            .is_(None)
        )
        return lot_available & no_preceding_rental

    async def _candidates(
        self,
        *predicates: ColumnElement[bool],
        order_time: SQLColumnExpression[datetime],
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        if not limit:
            return []
        rows = await self._session.execute(
            select(RentalRecord.id, RentalRecord.lot_id)
            .where(RentalRecord.tenant_id == self._tenant_id, *predicates)
            .order_by(order_time, RentalRecord.id)
            .limit(limit)
        )
        return [(rental_id, lot_id) for rental_id, lot_id in rows]

    async def _activate(self, rental_ids: list[UUID], *, now: datetime) -> int:
        if not rental_ids:
            return 0
        rows = await self._session.scalars(
            update(RentalRecord)
            .where(
                RentalRecord.tenant_id == self._tenant_id,
                RentalRecord.id.in_(rental_ids),
                RentalRecord.status == BOOKED,
                RentalRecord.start_time <= now,
                self._can_activate(),
            )
            .values(status="active", updated_at=now, version=RentalRecord.version + 1)
            .returning(RentalRecord.id)
            .execution_options(synchronize_session=False)
        )
        return len(rows.all())

    async def _mark_overdue(self, rental_ids: list[UUID], *, now: datetime, request_id: str) -> int:
        if not rental_ids:
            return 0
        changed = await self._session.execute(
            update(RentalRecord)
            .where(
                RentalRecord.tenant_id == self._tenant_id,
                RentalRecord.id.in_(rental_ids),
                RentalRecord.status == ACTIVE,
                RentalRecord.end_time < now,
            )
            .values(status="overdue", updated_at=now, version=RentalRecord.version + 1)
            .returning(RentalRecord.id, RentalRecord.lot_id)
            .execution_options(synchronize_session=False)
        )
        overdue_rentals = changed.all()
        if not overdue_rentals:
            return 0
        overdue_ids = [rental_id for rental_id, _ in overdue_rentals]

        overdue_lots = await self._session.scalars(
            update(LotRecord)
            .where(
                LotRecord.tenant_id == self._tenant_id,
                LotRecord.id.in_({lot_id for _, lot_id in overdue_rentals}),
                LotRecord.status == ACTIVE,
            )
            .values(status="overdue", updated_at=now, version=LotRecord.version + 1)
            .returning(LotRecord.id)
            .execution_options(synchronize_session=False)
        )
        await self._audit(
            "rental.overdue",
            "rental",
            overdue_ids,
            now=now,
            request_id=request_id,
            metadata={},
        )
        await self._audit(
            "lot.status_changed",
            "lot",
            overdue_lots.all(),
            now=now,
            request_id=request_id,
            metadata={"old_status": "active", "new_status": "overdue"},
        )
        await self._notify(overdue_ids, now=now)
        return len(overdue_rentals)

    async def _audit(
        self,
        action: str,
        entity_type: str,
        entity_ids: Sequence[UUID],
        *,
        now: datetime,
        request_id: str,
        metadata: dict[str, object],
    ) -> None:
        if not entity_ids:
            return
        validate_audit_event(
            action=action,
            actor_id=None,
            actor_role="system",
            entity_type=entity_type,
            metadata=metadata,
            ip=None,
            request_id=request_id,
        )
        rows = select(
            literal(self._tenant_id),
            literal("system"),
            literal(action),
            literal(entity_type),
            func.unnest(literal(list(entity_ids), ARRAY(PGUUID(as_uuid=True)))),
            literal(metadata, JSONB),
            literal(request_id),
            literal(now, DateTime(timezone=True)),
        )
        await self._session.execute(
            insert(AuditLogRecord)
            .inline()
            .from_select(
                [
                    "tenant_id",
                    "actor_role",
                    "action",
                    "entity_type",
                    "entity_id",
                    "metadata",
                    "request_id",
                    "created_at",
                ],
                rows,
            )
        )

    async def _notify(self, overdue_ids: list[UUID], *, now: datetime) -> None:
        timestamp = literal(now, DateTime(timezone=True))
        rentals = (
            select(RentalRecord.tenant_id, RentalRecord.id, RentalRecord.user_id)
            .where(RentalRecord.tenant_id == self._tenant_id, RentalRecord.id.in_(overdue_ids))
            .cte("overdue_rentals")
        )
        renters = select(
            rentals.c.tenant_id,
            rentals.c.id,
            literal("rental.overdue.user"),
            rentals.c.user_id,
            timestamp,
            timestamp,
            timestamp,
        )
        staff = (
            select(
                rentals.c.tenant_id,
                rentals.c.id,
                literal("rental.overdue.admin"),
                User.id,
                timestamp,
                timestamp,
                timestamp,
            )
            .join(User, User.tenant_id == rentals.c.tenant_id)
            .where(User.is_active.is_(True), User.role.in_(("admin", "owner")))
        )
        await self._session.execute(
            pg_insert(OutboxMessageRecord)
            .inline()
            .from_select(
                [
                    "tenant_id",
                    "entity_id",
                    "event_type",
                    "user_id",
                    "available_at",
                    "created_at",
                    "updated_at",
                ],
                union_all(renters, staff),
                include_defaults=False,
            )
            .on_conflict_do_nothing(constraint="uq_outbox_message_event_chain")
        )
