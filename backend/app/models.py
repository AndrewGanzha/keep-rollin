from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    domain: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    subdomain: Mapped[str | None] = mapped_column(CITEXT(), nullable=True, unique=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Europe/Moscow"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="RUB")
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    users: Mapped[list[User]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        UniqueConstraint("tenant_id", "id", name="uq_user_tenant_id_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    phone: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="user")
    password_hash: Mapped[str | None] = mapped_column(Text(), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    token_version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")
