from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class IdempotencyKeyRecord(Base):
    __tablename__ = "idempotency_key"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_idempotency_key_tenant_user",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_idempotency_key_expires_at", "expires_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    key: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
