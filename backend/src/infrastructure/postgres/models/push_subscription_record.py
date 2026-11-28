from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class PushSubscriptionRecord(Base):
    __tablename__ = "push_subscription"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_push_subscription_tenant_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "endpoint", name="uq_push_subscription_tenant_endpoint"),
        CheckConstraint("octet_length(endpoint) BETWEEN 1 AND 2048", name="endpoint_length"),
        Index(
            "ix_push_subscription_active_owner",
            "tenant_id",
            "user_id",
            "created_at",
            "id",
            postgresql_where=text("disabled_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    endpoint: Mapped[str] = mapped_column(Text())
    p256dh: Mapped[str] = mapped_column(Text())
    auth: Mapped[str] = mapped_column(Text())
    version: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), server_default=func.gen_random_uuid()
    )
    user_agent: Mapped[str | None] = mapped_column(String(512))
    expiration_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
