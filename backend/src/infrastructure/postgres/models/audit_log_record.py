from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base

AUDIT_ACTIONS = (
    "tenant.provisioned",
    "admin.created",
    "admin.deactivated",
    "user.deactivated",
    "settings.updated",
    "category.created",
    "category.updated",
    "category.characteristics_updated",
    "offer.created",
    "offer.updated",
    "offer.published",
    "lot.blocked",
    "lot.unblocked",
    "lot.status_changed",
    "verification.decided",
    "rental.booked",
    "rental.cancelled",
    "battery_stock.created",
    "battery_stock.updated",
    "battery_stock.deleted",
    "rental.closed",
    "rental.overdue",
    "ticket.status_changed",
)
AUDIT_ENTITY_TYPES = (
    "tenant",
    "user",
    "tenant_settings",
    "category",
    "offer",
    "lot",
    "lot_block",
    "verification_request",
    "rental",
    "battery_stock",
    "ticket",
)
_ACTION_SQL = ", ".join(f"'{action}'" for action in AUDIT_ACTIONS)
_ENTITY_SQL = ", ".join(f"'{entity}'" for entity in AUDIT_ENTITY_TYPES)


class AuditLogRecord(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["user.tenant_id", "user.id"],
            name="fk_audit_log_tenant_actor",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"action IN ({_ACTION_SQL})", name="action"),
        CheckConstraint(
            f"entity_type IN ({_ENTITY_SQL})",
            name="entity_type",
        ),
        CheckConstraint(
            "actor_role IN ('owner', 'admin', 'user', 'system', 'platform')",
            name="actor_role",
        ),
        CheckConstraint(
            "(actor_role IN ('owner', 'admin', 'user') AND actor_id IS NOT NULL) "
            "OR (actor_role IN ('system', 'platform') AND actor_id IS NULL)",
            name="actor",
        ),
        CheckConstraint(
            "actor_role <> 'user' OR (entity_type = 'rental' "
            "AND action IN ('rental.booked', 'rental.cancelled'))",
            name="user_action",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 4096",
            name="metadata",
        ),
        CheckConstraint(
            "request_id IS NULL OR char_length(request_id) BETWEEN 1 AND 128",
            name="request_id",
        ),
        Index("ix_audit_log_tenant_created_id", "tenant_id", "created_at", "id"),
        Index(
            "ix_audit_log_tenant_actor_created_id",
            "tenant_id",
            "actor_id",
            "created_at",
            "id",
            postgresql_where=text("actor_id IS NOT NULL"),
        ),
        Index(
            "ix_audit_log_tenant_action_created_id",
            "tenant_id",
            "action",
            "created_at",
            "id",
        ),
        Index(
            "ix_audit_log_tenant_entity_created_id",
            "tenant_id",
            "entity_type",
            "entity_id",
            "created_at",
            "id",
            postgresql_where=text("entity_id IS NOT NULL"),
        ),
        Index("ix_audit_log_created_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET(), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB(),
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
