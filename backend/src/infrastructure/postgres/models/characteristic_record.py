from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.postgres.base import Base

if TYPE_CHECKING:
    from src.infrastructure.postgres.models.category_record import CategoryRecord


class CharacteristicRecord(Base):
    __tablename__ = "characteristic"
    __table_args__ = (
        UniqueConstraint("category_id", "code", name="uq_characteristic_category_code"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["category.tenant_id", "category.id"],
            name="fk_characteristic_tenant_category",
            ondelete="CASCADE",
        ),
        Index("ix_characteristic_category_id", "category_id"),
        Index("ix_characteristic_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    type: Mapped[str] = mapped_column(Text(), nullable=False)
    unit: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_required: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false"
    )
    options: Mapped[list[str]] = mapped_column(
        JSONB(), nullable=False, default=list, server_default="[]"
    )
    sort: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    is_archived: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    category: Mapped[CategoryRecord] = relationship(back_populates="characteristics")
