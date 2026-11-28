from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class MfaChallengeRecord(Base):
    __tablename__ = "mfa_challenge"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_mfa_challenge_tenant_user",
            ondelete="CASCADE",
        ),
        CheckConstraint("purpose IN ('login', 'enroll')", name="ck_mfa_challenge_purpose"),
        Index(
            "ix_mfa_challenge_tenant_user_expires",
            "tenant_id",
            "user_id",
            "expires_at",
        ),
    )

    jti: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    secret_enc: Mapped[str | None] = mapped_column(Text(), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
