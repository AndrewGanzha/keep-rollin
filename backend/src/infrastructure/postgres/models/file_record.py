from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class FileRecord(Base):
    __tablename__ = "file"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_file_tenant_id_id"),
        ForeignKeyConstraint(["tenant_id", "uploaded_by"], ["user.tenant_id", "user.id"]),
        CheckConstraint(
            "purpose IN ('lot_photo', 'ticket_photo', 'verification_passport', "
            "'verification_registration', 'verification_selfie')",
            name="purpose",
        ),
        CheckConstraint(
            "(purpose = 'lot_photo') = (public_url IS NOT NULL)", name="public_purpose"
        ),
        CheckConstraint("size_bytes > 0", name="size_bytes"),
        CheckConstraint("NOT (is_ready AND is_purging)", name="state"),
        Index("ix_file_created_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(128), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer(), nullable=False)
    public_url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_ready: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default=false())
    is_purging: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AttachmentRecord(Base):
    __tablename__ = "attachment"
    __table_args__ = (
        UniqueConstraint("lot_id", "position", name="uq_attachment_lot_position"),
        ForeignKeyConstraint(
            ["tenant_id", "lot_id"], ["lot.tenant_id", "lot.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["tenant_id", "file_id"], ["file.tenant_id", "file.id"]),
        CheckConstraint("position >= 0", name="position"),
        Index("ix_attachment_tenant_file", "tenant_id", "file_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    lot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    position: Mapped[int] = mapped_column(Integer(), nullable=False)
