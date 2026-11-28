from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import DateTime, exists, func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import User
from src.domain.entities.occupancy import Occupancy
from src.domain.entities.tenant_profile import TenantPolicies
from src.domain.exceptions import LotUnavailableError
from src.domain.pricing.calculator import calculate_units, calculate_variant_price
from src.domain.pricing.errors import RentalPeriodNotAllowedError
from src.domain.value_objects.duration import AllowedDurations
from src.domain.value_objects.price import RentalUnit
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.repositories.admin_lot_repository import AdminLotRepository
from src.infrastructure.postgres.repositories.admin_settings_repository import (
    AdminSettingsRepository,
)
from src.infrastructure.postgres.repositories.battery_stock_repository import BatteryStockRepository
from src.infrastructure.postgres.repositories.lot_repository import LotRepository
from src.infrastructure.postgres.repositories.occupancy_repository import (
    OccupancyRepository,
    insert_occupancy,
)
from src.infrastructure.postgres.repositories.offer_repository import OfferRepository
from src.infrastructure.postgres.repositories.rental_repository import RentalRepository


class RentalCommandError(Exception):
    def __init__(self, code: str, status: int, fields: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.fields = fields


class RentalCommandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))
        self._rentals = RentalRepository(session)
        self._occupancy = OccupancyRepository(session)

    async def create(
        self, actor_id: UUID, lot_id: UUID, variant_id: UUID, period: TimeRange
    ) -> tuple[RentalRecord, LotRecord, datetime]:
        # Publication takes the exclusive form of this same advisory lock.
        await self._session.execute(
            select(
                func.pg_advisory_xact_lock_shared(
                    func.hashtextextended(f"offer:{self._tenant_id}", 0)
                )
            )
        )
        actor = await self._session.scalar(
            select(User)
            .where(User.tenant_id == self._tenant_id, User.id == actor_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if actor is None or not actor.is_active:
            raise RentalCommandError("forbidden_role", 403)
        if actor.verification_status != "approved":
            raise RentalCommandError("verification_required", 403)
        if not await OfferRepository(self._session).has_accepted_current(user_id=actor_id):
            raise RentalCommandError("offer_not_accepted", 403)

        lot = await self._rentals.lock_lot(lot_id)
        if lot is None:
            raise RentalCommandError("not_found", 404)
        category_available = await self._session.scalar(
            select(CategoryRecord.id)
            .where(
                CategoryRecord.id == lot.category_id,
                CategoryRecord.tenant_id == self._tenant_id,
                CategoryRecord.is_archived.is_(False),
            )
            .with_for_update(read=True)
        )
        if lot.status != "active" or category_available is None:
            raise LotUnavailableError

        variant = await self._session.scalar(
            select(LotVariantRecord)
            .where(
                LotVariantRecord.tenant_id == self._tenant_id,
                LotVariantRecord.lot_id == lot_id,
                LotVariantRecord.id == variant_id,
                LotVariantRecord.is_active.is_(True),
            )
            .options(selectinload(LotVariantRecord.price_tiers))
        )
        if variant is None:
            raise RentalCommandError("validation_error", 422, {"variant_id": "invalid lot variant"})

        settings = await AdminSettingsRepository(self._session).get()
        if settings is None:
            raise RentalCommandError("tenant_not_found", 404)
        policies = settings.policies
        now = await self._now()
        self._validate_period(period, now, policies)
        selected = LotRepository._variant_to_domain(variant)
        price = calculate_variant_price(
            selected,
            units=calculate_units(period, cast(RentalUnit, lot.rental_unit)),
            allowed_durations=AllowedDurations.create(lot.allowed_durations),
        )
        rental_id, occupancy_id = uuid4(), uuid4()
        await self._occupancy.add(
            Occupancy(
                id=occupancy_id,
                created_at=now,
                updated_at=now,
                lot_id=lot_id,
                kind="booking",
                period=period,
                ref_id=rental_id,
                status="active",
                created_by=actor_id,
            )
        )
        count = selected.battery_count.value
        battery_type = lot.battery_type if count else None
        if count and (
            battery_type is None
            or await BatteryStockRepository(self._session).capacity(battery_type, period, lock=True)
            < count
        ):
            raise RentalCommandError("battery_unavailable", 409)

        rental = await self._rentals.add(
            RentalRecord(
                id=rental_id,
                tenant_id=self._tenant_id,
                user_id=actor_id,
                lot_id=lot_id,
                variant_id=variant_id,
                occupancy_id=occupancy_id,
                battery_type=battery_type,
                battery_count=count,
                start_time=period.start,
                end_time=period.end,
                price_minor=price.total_minor,
                currency=settings.currency,
                status="booked",
                cancellation_deadline=period.start
                - timedelta(hours=policies.cancellation_free_hours),
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
        return rental, lot, now

    async def cancel(
        self, rental_id: UUID, actor_id: UUID, *, own: bool, reason: str | None
    ) -> tuple[RentalRecord, datetime, bool]:
        rental = await self._rentals.lock(rental_id, user_id=actor_id if own else None)
        if rental is None:
            raise RentalCommandError("not_found", 404)
        now = await self._now()
        if rental.status == "cancelled":
            return rental, now, False
        if own:
            if rental.status != "booked":
                raise RentalCommandError("rental_not_active", 409)
            if now > rental.cancellation_deadline:
                raise RentalCommandError("cancellation_not_allowed", 409)
        elif rental.status not in ("booked", "active"):
            raise RentalCommandError("rental_not_active", 409)
        await self._occupancy.release(rental.occupancy_id)
        rental.status = "cancelled"
        rental.cancelled_at = now
        rental.cancelled_by = actor_id
        rental.cancellation_reason = reason
        rental.version += 1
        rental.updated_at = now
        await self._rentals.flush()
        return rental, now, True

    async def close(
        self, rental_id: UUID, actor_id: UUID, *, comment: str, lot_status: str
    ) -> tuple[RentalRecord, datetime, str]:
        rental = await self._rentals.lock(rental_id)
        if rental is None:
            raise RentalCommandError("not_found", 404)
        if rental.status in ("completed", "cancelled"):
            raise RentalCommandError("rental_already_closed", 409)
        lot = await self._rentals.lock_lot(rental.lot_id)
        assert lot is not None
        other_overdue = await self._session.scalar(
            select(
                exists().where(
                    RentalRecord.tenant_id == self._tenant_id,
                    RentalRecord.lot_id == lot.id,
                    RentalRecord.id != rental.id,
                    RentalRecord.status == "overdue",
                )
            )
        )
        if other_overdue and rental.status != "overdue":
            raise RentalCommandError("lot_has_active_rental", 409)
        resulting_status = "overdue" if other_overdue else lot_status
        now = await self._now()

        await self._occupancy.release(rental.occupancy_id)
        if resulting_status == "maintenance" and lot.status != "maintenance":
            await insert_occupancy(
                self._session,
                OccupancyRecord(
                    tenant_id=self._tenant_id,
                    lot_id=lot.id,
                    kind="maintenance",
                    period=Range(now, None, bounds="[)"),
                    ref_id=lot.id,
                    status="active",
                    created_by=actor_id,
                    created_at=now,
                    updated_at=now,
                ),
            )
        if resulting_status == "active" and lot.status == "maintenance":
            await AdminLotRepository(self._session)._close_status_maintenance(lot.id, now)
        if lot.status != resulting_status:
            lot.status = resulting_status
            lot.version += 1
            lot.updated_at = now

        rental.status = "completed"
        rental.completed_at = now
        rental.closed_by = actor_id
        rental.close_comment = comment
        rental.version += 1
        rental.updated_at = now
        await self._rentals.flush()
        return rental, now, resulting_status

    async def _now(self) -> datetime:
        timestamp = await self._session.scalar(
            select(func.clock_timestamp(type_=DateTime(timezone=True)))
        )
        assert isinstance(timestamp, datetime)
        return timestamp.astimezone(UTC)

    @staticmethod
    def _validate_period(period: TimeRange, now: datetime, policies: TenantPolicies) -> None:
        if period.start < now:
            raise RentalCommandError(
                "validation_error", 422, {"start_time": "must not be in the past"}
            )
        if period.start > now + timedelta(days=policies.booking_horizon_days):
            raise RentalCommandError(
                "validation_error", 422, {"start_time": "outside booking horizon"}
            )
        if (
            not policies.min_rental_minutes * 60
            <= period.duration_seconds
            <= policies.max_rental_days * 86400
        ):
            raise RentalPeriodNotAllowedError("Rental duration exceeds tenant limits")
