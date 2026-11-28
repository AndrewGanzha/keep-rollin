from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.postgres.base import Base

if TYPE_CHECKING:
    from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord


class LotRecord(Base):
    __tablename__ = "lot"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_lot_tenant_slug"),
        UniqueConstraint("tenant_id", "id", name="uq_lot_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["category.tenant_id", "category.id"],
            name="fk_lot_tenant_category",
            ondelete="RESTRICT",
        ),
        Index("ix_lot_tenant_id", "tenant_id"),
        Index("ix_lot_category_id", "category_id"),
        Index("ix_lot_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    photos: Mapped[list[str]] = mapped_column(
        JSONB(), nullable=False, default=list, server_default="[]"
    )
    characteristics: Mapped[dict[str, str | int | float]] = mapped_column(
        JSONB(), nullable=False, default=dict, server_default="{}"
    )
    rental_unit: Mapped[str] = mapped_column(Text(), nullable=False)
    battery_type: Mapped[str | None] = mapped_column(Text(), nullable=True)
    allowed_durations: Mapped[list[int]] = mapped_column(
        ARRAY(Integer()), nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(Text(), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    variants: Mapped[list[LotVariantRecord]] = relationship(
        back_populates="lot",
        cascade="all, delete-orphan",
    )
