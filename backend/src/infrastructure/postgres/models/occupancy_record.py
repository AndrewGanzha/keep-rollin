from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.ranges import Range
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class OccupancyRecord(Base):
    __tablename__ = "occupancy"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lot.tenant_id", "lot.id"],
            name="fk_occupancy_tenant_lot",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "kind IN ('booking', 'block', 'maintenance')",
            name="ck_occupancy_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'released')",
            name="ck_occupancy_status",
        ),
        ExcludeConstraint(
            ("tenant_id", "="),
            ("lot_id", "="),
            ("period", "&&"),
            name="ex_occupancy_no_overlap",
            using="gist",
            where=text("status = 'active'"),
        ),
        Index("ix_occupancy_tenant_lot", "tenant_id", "lot_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    lot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text(), nullable=False)
    period: Mapped[Range[datetime]] = mapped_column(TSTZRANGE(), nullable=False)
    ref_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Text(), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
