from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.postgres.base import Base

if TYPE_CHECKING:
    from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
    from src.infrastructure.postgres.models.lot_record import LotRecord


class LotVariantRecord(Base):
    __tablename__ = "lot_variant"
    __table_args__ = (
        UniqueConstraint("lot_id", "battery_count", name="uq_lot_variant_battery"),
        UniqueConstraint("tenant_id", "id", name="uq_lot_variant_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lot.tenant_id", "lot.id"],
            name="fk_lot_variant_tenant_lot",
            ondelete="CASCADE",
        ),
        Index("ix_lot_variant_lot_id", "lot_id"),
        Index("ix_lot_variant_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    lot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    battery_count: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    lot: Mapped[LotRecord] = relationship(back_populates="variants")
    price_tiers: Mapped[list[LotPriceTierRecord]] = relationship(
        back_populates="variant",
        cascade="all, delete-orphan",
    )
