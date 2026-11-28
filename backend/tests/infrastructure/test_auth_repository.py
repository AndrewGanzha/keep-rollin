from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.domain.entities.user_account import EmailTakenError
from src.infrastructure.postgres.repositories.auth_repository import AuthRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def tenants(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID]]:
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="Auth A",
        slug=f"auth-a-{suffix}",
        domain=f"auth-a-{suffix}.test",
        subdomain=f"auth-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Auth B",
        slug=f"auth-b-{suffix}",
        domain=f"auth-b-{suffix}.test",
        subdomain=f"auth-b-{suffix}",
    )
    async with session_factory() as session:
        session.add_all([tenant_a, tenant_b])
        await session.commit()
    try:
        yield tenant_a.id, tenant_b.id
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a.id, tenant_b.id])))
            await session.commit()


def _configured(session: AsyncSession, tenant_id: UUID) -> None:
    configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")


async def test_database_sessions_use_read_committed(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        result = await connection.execute(text("SHOW transaction_isolation"))
        assert result.scalar_one() == "read committed"


async def test_user_creation_and_duplicate_email(
    session_factory: async_sessionmaker[AsyncSession],
    tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, _tenant_b = tenants
    async with session_factory() as session:
        _configured(session, tenant_a)
        repository = AuthRepository(session)
        user = await repository.create_user(
            email="rider@example.com",
            name="Rider",
            password_hash="hash",
            phone=None,
        )
        assert user.role == "user"
        assert user.verification_status == "pending"
        assert await repository.get_by_email("rider@example.com") is not None
        with pytest.raises(EmailTakenError):
            await repository.create_user(
                email="rider@example.com",
                name="Other",
                password_hash="hash",
                phone=None,
            )
        await session.rollback()


async def test_refresh_sessions_rotate_and_are_tenant_scoped(
    session_factory: async_sessionmaker[AsyncSession],
    tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = tenants
    async with session_factory() as session:
        _configured(session, tenant_a)
        repository = AuthRepository(session)
        user = await repository.create_user(
            email="rider@example.com",
            name="Rider",
            password_hash="hash",
            phone=None,
        )
        session_id = await repository.create_refresh_session(
            user_id=user.id,
            token_hash="token-a",
            family_id=uuid4(),
            expires_at=NOW + timedelta(days=30),
            user_agent=None,
            ip=None,
        )
        await session.commit()
        stored = await repository.get_refresh_session("token-a")
        assert stored is not None
        await repository.revoke_session(session_id, revoked_at=NOW)
        await session.commit()
        stored_after = await repository.get_refresh_session("token-a")
        assert stored_after is not None
        assert stored_after.revoked_at is not None

    async with session_factory() as session:
        _configured(session, tenant_b)
        assert await AuthRepository(session).get_refresh_session("token-a") is None


async def test_cross_tenant_refresh_session_write_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = tenants
    async with session_factory() as session:
        _configured(session, tenant_b)
        user_b = await AuthRepository(session).create_user(
            email="tenant-b@example.com",
            name="Tenant B",
            password_hash="hash",
            phone=None,
        )
        await session.commit()

    async with session_factory() as session:
        _configured(session, tenant_a)
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO refresh_session "
                    "(tenant_id, user_id, token_hash, family_id, expires_at) "
                    "VALUES (:tenant_id, :user_id, :token_hash, :family_id, "
                    "now() + interval '1 day')"
                ),
                {
                    "tenant_id": tenant_b,
                    "user_id": user_b.id,
                    "token_hash": "cross-tenant-token",
                    "family_id": uuid4(),
                },
            )
        await session.rollback()


async def test_for_update_refreshes_stale_identity_map(
    session_factory: async_sessionmaker[AsyncSession],
    tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, _tenant_b = tenants
    async with session_factory() as first:
        _configured(first, tenant_a)
        first_repository = AuthRepository(first)
        user = await first_repository.create_user(
            email=f"stale-{uuid4().hex[:8]}@example.com",
            name="Stale",
            password_hash="old-hash",
            phone=None,
        )
        await first.commit()
        cached = await first_repository.get_by_id(user.id)
        assert cached is not None
        assert cached.password_hash == "old-hash"
        mapped = await first.get(User, user.id)
        assert mapped is not None
        assert mapped.password_hash == "old-hash"

        async with session_factory() as second:
            _configured(second, tenant_a)
            await AuthRepository(second).update_password(
                user.id,
                password_hash="new-hash",
                token_version=2,
            )
            await second.commit()

        refreshed = await first_repository.get_by_id_for_update(user.id)
        assert refreshed is not None
        assert refreshed.password_hash == "new-hash"
        assert refreshed.token_version == 2
        await first.refresh(mapped)
        assert mapped.password_hash == "new-hash"
        assert mapped.token_version == 2
        await first.commit()
