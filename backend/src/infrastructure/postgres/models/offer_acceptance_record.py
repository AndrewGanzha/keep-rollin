from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class OfferAcceptanceRecord(Base):
    __tablename__ = "offer_acceptance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_offer_acceptance_tenant_user",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "offer_version_id"],
            ["offer_version.tenant_id", "offer_version.id"],
            name="fk_offer_acceptance_tenant_offer",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "user_id",
            "offer_version_id",
            name="uq_offer_acceptance_user_version",
        ),
        Index("ix_offer_acceptance_tenant_user", "tenant_id", "user_id"),
        Index("ix_offer_acceptance_offer_version", "offer_version_id"),
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
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    offer_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ip: Mapped[str | None] = mapped_column(Text(), nullable=True)
