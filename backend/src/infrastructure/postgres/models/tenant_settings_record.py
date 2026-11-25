from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base

DEFAULT_POLICIES = {
    "booking_horizon_days": 60,
    "min_rental_minutes": 60,
    "max_rental_days": 30,
    "cancellation_free_hours": 24,
    "reminder_hours_before": 1,
    "tickets_per_rental_per_day": 5,
}
DEFAULT_POLICIES_SQL = (
    '\'{"booking_horizon_days": 60, "min_rental_minutes": 60, '
    '"max_rental_days": 30, "cancellation_free_hours": 24, '
    '"reminder_hours_before": 1, "tickets_per_rental_per_day": 5}\'::jsonb'
)


class TenantSettingsRecord(Base):
    __tablename__ = "tenant_settings"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        primary_key=True,
    )
    logo_url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    primary_color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default=text("'#0f766e'")
    )
    policies: Mapped[dict[str, object]] = mapped_column(
        JSONB(),
        nullable=False,
        default=lambda: dict(DEFAULT_POLICIES),
        server_default=text(DEFAULT_POLICIES_SQL),
    )
    vapid_public_key: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
