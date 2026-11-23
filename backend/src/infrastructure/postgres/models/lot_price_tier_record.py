from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
    from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord


class LotPriceTierRecord(Base):
    __tablename__ = "lot_price_tier"
    __table_args__ = (
        UniqueConstraint("variant_id", "min_units", name="uq_lot_price_tier_variant_min"),
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["lot_variant.tenant_id", "lot_variant.id"],
            name="fk_lot_price_tier_tenant_variant",
            ondelete="CASCADE",
        ),
        Index("ix_lot_price_tier_variant_id", "variant_id"),
        Index("ix_lot_price_tier_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    min_units: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    price_per_unit_minor: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    variant: Mapped[LotVariantRecord] = relationship(back_populates="price_tiers")
