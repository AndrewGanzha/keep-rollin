from datetime import datetime
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
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class VerificationRequestRecord(Base):
    __tablename__ = "verification_request"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_verification_request_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewed_by"],
            ["user.tenant_id", "user.id"],
            name="fk_verification_request_reviewer_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint(
            "(status = 'pending' AND reviewed_at IS NULL AND reviewed_by IS NULL "
            "AND admin_comment IS NULL) OR "
            "(status <> 'pending' AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)",
            name="review_state",
        ),
        CheckConstraint(
            "status <> 'rejected' OR (admin_comment IS NOT NULL AND btrim(admin_comment) <> '')",
            name="reject_comment",
        ),
        Index(
            "uq_verification_request_active_user",
            "tenant_id",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
        ),
        Index("ix_verification_request_tenant_user_created", "tenant_id", "user_id", "created_at"),
        Index("ix_verification_request_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    passport_enc: Mapped[str] = mapped_column(Text(), nullable=False, deferred=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    admin_comment: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")


class VerificationDocumentRecord(Base):
    __tablename__ = "verification_document"
    __table_args__ = (
        UniqueConstraint("request_id", "file_id", name="uq_verification_document_request_file"),
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["verification_request.tenant_id", "verification_request.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["file.tenant_id", "file.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "purpose IN ('verification_passport', 'verification_registration', "
            "'verification_selfie')",
            name="purpose",
        ),
        Index("ix_verification_document_tenant_file", "tenant_id", "file_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
