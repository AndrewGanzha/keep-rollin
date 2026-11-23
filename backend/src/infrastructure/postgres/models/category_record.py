from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.postgres.base import Base

if TYPE_CHECKING:
    from src.infrastructure.postgres.models.characteristic_record import CharacteristicRecord


class CategoryRecord(Base):
    __tablename__ = "category"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_category_tenant_slug"),
        UniqueConstraint("tenant_id", "id", name="uq_category_tenant_id_id"),
        Index("ix_category_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    characteristics: Mapped[list[CharacteristicRecord]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
    )
