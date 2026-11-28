from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from app.tenancy import DatabaseTenantResolver, TenantCandidate
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.mfa_challenge_record import MfaChallengeRecord
from src.infrastructure.postgres.models.password_reset_token_record import (
    PasswordResetTokenRecord,
)
from tests.factories import TenantSeedFactory, UserSeedFactory

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)


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
async def seeded(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID, str, str]]:
    suffix = uuid4().hex[:10]
    tenant_a_seed = TenantSeedFactory.build(
        name="Tenant A",
        slug=f"tenant-a-{suffix}",
        domain=f"tenant-a-{suffix}.test",
        subdomain=f"tenant-a-{suffix}",
    )
    tenant_b_seed = TenantSeedFactory.build(
        name="Tenant B",
        slug=f"tenant-b-{suffix}",
        domain=f"tenant-b-{suffix}.test",
        subdomain=f"tenant-b-{suffix}",
    )
    user_a_seed = UserSeedFactory.build(
        email=f"a-{suffix}@example.com",
        name="User A",
        role="user",
    )
    user_b_seed = UserSeedFactory.build(
        email=f"b-{suffix}@example.com",
        name="User B",
        role="user",
    )

    async with session_factory() as session:
        tenant_a = Tenant(**tenant_a_seed.__dict__)
        tenant_b = Tenant(**tenant_b_seed.__dict__)
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        session.add_all(
            [
                User(tenant_id=tenant_a.id, **user_a_seed.__dict__),
                User(tenant_id=tenant_b.id, **user_b_seed.__dict__),
            ]
        )
        await session.commit()

    tenant_ids = (tenant_a.id, tenant_b.id)
    try:
        yield tenant_a.id, tenant_b.id, user_a_seed.email, user_b_seed.email
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(AuditLogRecord).where(AuditLogRecord.tenant_id.in_(tenant_ids))
            )
            await session.execute(delete(User).where(User.tenant_id.in_(tenant_ids)))
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
            await session.commit()


async def test_superuser_database_role_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        configure_session(session, tenant_id=None, database_role="postgres")
        with pytest.raises(ValueError, match="SUPERUSER"):
            await session.execute(text("SELECT 1"))
        with pytest.raises((DBAPIError, InvalidRequestError)):
            await session.execute(text("SELECT 1"))


async def test_rls_hides_rows_without_context(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, str, str],
) -> None:
    async with session_factory() as session:
        configure_session(session, tenant_id=None, database_role="keep_rollin_app")
        result = await session.execute(select(User))
        assert list(result.scalars()) == []


async def test_rls_isolates_tenants(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, str, str],
) -> None:
    tenant_a, tenant_b, email_a, email_b = seeded

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        result = await session.execute(select(User.email))
        assert list(result.scalars()) == [email_a]

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_b, database_role="keep_rollin_app")
        result = await session.execute(select(User.email))
        assert list(result.scalars()) == [email_b]


async def test_rls_context_resets_after_commit(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, str, str],
) -> None:
    tenant_a, _tenant_b, email_a, _email_b = seeded

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        first = await session.execute(select(User.email))
        assert list(first.scalars()) == [email_a]
        await session.commit()

        configure_session(session, tenant_id=None, database_role="keep_rollin_app")
        second = await session.execute(select(User.email))
        assert list(second.scalars()) == []


async def test_rls_rejects_cross_tenant_insert(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, str, str],
) -> None:
    tenant_a, tenant_b, _email_a, _email_b = seeded

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        session.add(
            User(
                tenant_id=tenant_b,
                email=f"cross-{uuid4().hex[:10]}@example.com",
                name="Cross tenant",
                role="user",
            )
        )
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()


async def test_database_tenant_resolver(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, str, str],
) -> None:
    _tenant_a, _tenant_b, _email_a, _email_b = seeded
    suffix = uuid4().hex[:10]
    seed = TenantSeedFactory.build(
        name="Resolver tenant",
        slug=f"resolver-{suffix}",
        domain=f"resolver-{suffix}.test",
        subdomain=f"resolver-{suffix}",
    )
    async with session_factory() as session:
        tenant = Tenant(**seed.__dict__)
        session.add(tenant)
        await session.commit()
        tenant_id = tenant.id

    try:
        resolver = DatabaseTenantResolver(session_factory, "keep_rollin_app")
        assert await resolver.resolve(TenantCandidate(seed.domain, "domain")) is not None
        assert await resolver.resolve(TenantCandidate(seed.subdomain, "subdomain")) is not None
        assert await resolver.resolve(TenantCandidate(seed.domain, "subdomain")) is None
        assert await resolver.resolve(TenantCandidate("missing.test", "domain")) is None
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()


async def test_database_tenant_resolver_handles_stored_mixed_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    suffix = uuid4().hex[:10]
    seed = TenantSeedFactory.build(
        name="Mixed case tenant",
        slug=f"mixed-{suffix}",
        domain=f"Mixed-{suffix}.Test",
        subdomain=f"MixedSub-{suffix}",
    )
    async with session_factory() as session:
        tenant = Tenant(**seed.__dict__)
        session.add(tenant)
        await session.commit()
        tenant_id = tenant.id

    try:
        resolver = DatabaseTenantResolver(session_factory, "keep_rollin_app")
        assert await resolver.resolve(TenantCandidate(f"mixed-{suffix}.test", "domain")) is not None
        assert (
            await resolver.resolve(TenantCandidate(f"mixedsub-{suffix}", "subdomain")) is not None
        )
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()


async def test_auth_hardening_tables_are_tenant_isolated(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, str, str],
) -> None:
    tenant_a, tenant_b, email_a, email_b = seeded
    async with session_factory() as session:
        rows = await session.execute(select(User.id, User.email))
        user_ids = {row.email: row.id for row in rows}
    user_a = user_ids[email_a]
    user_b = user_ids[email_b]
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    challenge_id = uuid4()
    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        session.add(
            MfaChallengeRecord(
                jti=challenge_id,
                tenant_id=tenant_a,
                user_id=user_a,
                purpose="login",
                expires_at=expires_at,
            )
        )
        session.add(
            PasswordResetTokenRecord(
                tenant_id=tenant_a,
                user_id=user_a,
                token_hash=f"hash-{challenge_id}",
                token_secret_enc="encrypted",
                expires_at=expires_at,
            )
        )
        await session.commit()

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_b, database_role="keep_rollin_app")
        assert list((await session.execute(select(MfaChallengeRecord))).scalars()) == []
        assert list((await session.execute(select(PasswordResetTokenRecord))).scalars()) == []

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        challenges = list((await session.execute(select(MfaChallengeRecord))).scalars())
        tokens = list((await session.execute(select(PasswordResetTokenRecord))).scalars())
        assert [row.jti for row in challenges] == [challenge_id]
        assert len(tokens) == 1

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        session.add(
            MfaChallengeRecord(
                jti=uuid4(),
                tenant_id=tenant_b,
                user_id=user_b,
                purpose="login",
                expires_at=expires_at,
            )
        )
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        session.add(
            PasswordResetTokenRecord(
                tenant_id=tenant_b,
                user_id=user_b,
                token_hash=f"cross-{uuid4()}",
                token_secret_enc="encrypted",
                expires_at=expires_at,
            )
        )
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()


async def test_audit_log_is_rls_isolated_and_append_only(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, str, str],
) -> None:
    tenant_a, tenant_b, _email_a, _email_b = seeded
    audit_id = uuid4()
    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        session.add(
            AuditLogRecord(
                id=audit_id,
                tenant_id=tenant_a,
                action="tenant.provisioned",
                actor_id=None,
                actor_role="platform",
                entity_type="tenant",
                entity_id=tenant_a,
                metadata_json={"source": "cli"},
            )
        )
        await session.commit()

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_b, database_role="keep_rollin_app")
        assert list((await session.execute(select(AuditLogRecord))).scalars()) == []

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        assert [row.id for row in (await session.execute(select(AuditLogRecord))).scalars()] == [
            audit_id
        ]

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        session.add(
            AuditLogRecord(
                id=uuid4(),
                tenant_id=tenant_b,
                action="tenant.provisioned",
                actor_id=None,
                actor_role="platform",
                entity_type="tenant",
                entity_id=tenant_b,
                metadata_json={"source": "cli"},
            )
        )
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        with pytest.raises(DBAPIError) as update_error:
            await session.execute(
                update(AuditLogRecord)
                .where(AuditLogRecord.id == audit_id)
                .values(request_id="changed")
            )
        await session.rollback()
        assert "permission denied" in str(update_error.value).casefold()

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        with pytest.raises(DBAPIError) as delete_error:
            await session.execute(delete(AuditLogRecord).where(AuditLogRecord.id == audit_id))
        await session.rollback()
        assert "permission denied" in str(delete_error.value).casefold()

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        with pytest.raises(DBAPIError) as truncate_error:
            await session.execute(text("TRUNCATE audit_log"))
        await session.rollback()
        assert "permission denied" in str(truncate_error.value).casefold()
