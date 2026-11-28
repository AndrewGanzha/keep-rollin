from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base

RentalStatus = Literal["booked", "active", "overdue", "completed", "cancelled"]


class RentalPriceMinor(TypeDecorator[int]):
    """Preserve the exact product of a BIGINT price tier and rental units."""

    impl = Numeric(24, 0)
    cache_ok = True

    def process_bind_param(self, value: int | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)

    def process_result_value(self, value: Decimal | None, dialect: Dialect) -> int | None:
        return None if value is None else int(value)


class RentalRecord(Base):
    __tablename__ = "rental"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_rental_tenant_id_id"),
        UniqueConstraint("occupancy_id", name="uq_rental_occupancy"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_rental_tenant_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lot.tenant_id", "lot.id"],
            name="fk_rental_tenant_lot",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "lot_id", "occupancy_id"],
            ["occupancy.tenant_id", "occupancy.lot_id", "occupancy.id"],
            name="fk_rental_tenant_lot_occupancy",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "battery_type"],
            ["battery_stock.tenant_id", "battery_stock.battery_type"],
            name="fk_rental_tenant_battery_stock",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "closed_by"],
            ["user.tenant_id", "user.id"],
            name="fk_rental_tenant_closed_by_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "cancelled_by"],
            ["user.tenant_id", "user.id"],
            name="fk_rental_tenant_cancelled_by_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "status IN ('booked', 'active', 'overdue', 'completed', 'cancelled')", name="status"
        ),
        CheckConstraint("start_time < end_time", name="period"),
        CheckConstraint("price_minor > 0", name="price_minor"),
        CheckConstraint(
            "(battery_count = 0 AND battery_type IS NULL) OR "
            "(battery_count > 0 AND battery_type IS NOT NULL)",
            name="battery",
        ),
        CheckConstraint("version > 0", name="version"),
        Index("ix_rental_tenant_created", "tenant_id", "created_at", "id"),
        Index("ix_rental_tenant_user_created", "tenant_id", "user_id", "created_at", "id"),
        Index("ix_rental_tenant_lot", "tenant_id", "lot_id"),
        Index("ix_rental_tenant_battery_end", "tenant_id", "battery_type", "end_time"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    lot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    occupancy_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # Catalog edits can replace a variant. Keep the original selection in rental history.
    variant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    battery_type: Mapped[str | None] = mapped_column(Text())
    battery_count: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_minor: Mapped[int] = mapped_column(RentalPriceMinor(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[RentalStatus] = mapped_column(
        String(16), nullable=False, server_default="booked"
    )
    cancellation_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    close_comment: Mapped[str | None] = mapped_column(Text())
    version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
