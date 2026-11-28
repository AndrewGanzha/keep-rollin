from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base

TicketCategory = Literal["no_power", "no_drive", "battery", "damage", "other"]
TicketStatus = Literal["submitted", "in_progress", "resolved"]


class TicketRecord(Base):
    __tablename__ = "ticket"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_ticket_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "rental_id"],
            ["rental.tenant_id", "rental.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "category IN ('no_power', 'no_drive', 'battery', 'damage', 'other')",
            name="category",
        ),
        CheckConstraint("char_length(btrim(description)) BETWEEN 10 AND 1000", name="description"),
        CheckConstraint("status IN ('submitted', 'in_progress', 'resolved')", name="status"),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)",
            name="resolved_at",
        ),
        CheckConstraint(
            "status <> 'resolved' OR (admin_comment IS NOT NULL AND btrim(admin_comment) <> '')",
            name="resolution_comment",
        ),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint("skipped_photo_count BETWEEN 0 AND 3", name="skipped_photo_count"),
        Index("ix_ticket_tenant_created_id", "tenant_id", "created_at", "id"),
        Index("ix_ticket_tenant_rental_created_id", "tenant_id", "rental_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    rental_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    category: Mapped[TicketCategory] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        String(16), nullable=False, server_default="submitted"
    )
    admin_comment: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    skipped_photo_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")


class TicketAttachmentRecord(Base):
    __tablename__ = "ticket_attachment"
    __table_args__ = (
        UniqueConstraint("ticket_id", "position", name="uq_ticket_attachment_ticket_position"),
        ForeignKeyConstraint(
            ["tenant_id", "ticket_id"], ["ticket.tenant_id", "ticket.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["file.tenant_id", "file.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("position BETWEEN 0 AND 2", name="position"),
        Index("ix_ticket_attachment_tenant_file", "tenant_id", "file_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ticket_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    position: Mapped[int] = mapped_column(Integer(), nullable=False)
