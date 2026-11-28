from __future__ import annotations

import asyncio
import base64
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.repositories.admin_user_repository import AdminUserRepository
from src.infrastructure.security.password_hasher import Argon2PasswordHasher
from src.infrastructure.security.totp import code_at
from tests.api.auth_helpers import MFA_SECRET, PASSWORD, enable_mfa, login_with_mfa

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"
ADMIN_PASSWORD = "Admin-Rider-2026!"


@dataclass(frozen=True)
class SeededAdmins:
    domain_a: str
    domain_b: str
    tenant_a: UUID
    tenant_b: UUID
    owner_id: UUID
    owner_email: str
    owner_b_id: UUID
    owner_b_email: str
    admin_email: str
    user_email: str
    foreign_user_id: UUID


def seed_admins() -> SeededAdmins:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    hasher = Argon2PasswordHasher()
    tenant_a = Tenant(
        id=uuid4(),
        name="Admin A",
        slug=f"admin-a-{suffix}",
        domain=f"admin-a-{suffix}.test",
        subdomain=f"admin-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Admin B",
        slug=f"admin-b-{suffix}",
        domain=f"admin-b-{suffix}.test",
        subdomain=f"admin-b-{suffix}",
    )
    password_hash = hasher.hash(PASSWORD)
    owner = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"owner-{suffix}@example.com",
        name="Owner",
        role="owner",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    owner_b = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"owner-b-{suffix}@example.com",
        name="Owner B",
        role="owner",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    admin = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"admin-{suffix}@example.com",
        name="Admin",
        role="admin",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    user = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"user-{suffix}@example.com",
        name="User",
        role="user",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    foreign = User(
        id=uuid4(),
        tenant_id=tenant_b.id,
        email=f"foreign-{suffix}@example.com",
        name="Foreign",
        role="user",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    enable_mfa(owner)
    enable_mfa(owner_b)
    enable_mfa(admin)

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all([owner, owner_b, admin, user, foreign])
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededAdmins(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_a=tenant_a.id,
        tenant_b=tenant_b.id,
        owner_id=owner.id,
        owner_email=owner.email,
        owner_b_id=owner_b.id,
        owner_b_email=owner_b.email,
        admin_email=admin.email,
        user_email=user.email,
        foreign_user_id=foreign.id,
    )


def cleanup(tenant_ids: tuple[UUID, UUID]) -> None:
    assert DATABASE_URL is not None

    async def run() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(
                    delete(AuditLogRecord).where(AuditLogRecord.tenant_id.in_(tenant_ids))
                )
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.fixture
def seeded() -> Iterator[SeededAdmins]:
    value = seed_admins()
    try:
        yield value
    finally:
        cleanup((value.tenant_a, value.tenant_b))


def client_for(domain: str) -> TestClient:
    assert DATABASE_URL is not None
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
        database_role="keep_rollin_app",
        jwt_secret=JWT_SECRET,
        refresh_cookie_secure=True,
    )
    return TestClient(
        create_app(settings),
        base_url=f"https://{domain}",
        headers={
            "Sec-Fetch-Site": "same-origin",
            "Origin": f"https://{domain}",
        },
    )


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def next_step_code() -> str:
    return code_at(MFA_SECRET, timestamp=time.time() + 30)


def _login(client: TestClient, email: str) -> str:
    payload = login_with_mfa(client, email)
    return str(payload["access_token"])


def _audit_rows(tenant_id: UUID) -> list[AuditLogRecord]:
    assert DATABASE_URL is not None

    async def run() -> list[AuditLogRecord]:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                result = await session.execute(
                    select(AuditLogRecord)
                    .where(AuditLogRecord.tenant_id == tenant_id)
                    .order_by(AuditLogRecord.created_at, AuditLogRecord.id)
                )
                return list(result.scalars().all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _insert_audit_rows(tenant_id: UUID, actor_id: UUID, count: int) -> None:
    assert DATABASE_URL is not None
    base = datetime.now(UTC) - timedelta(minutes=10)

    async def run() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                for _index in range(count):
                    session.add(
                        AuditLogRecord(
                            tenant_id=tenant_id,
                            action="admin.created",
                            actor_id=actor_id,
                            actor_role="owner",
                            entity_type="user",
                            entity_id=uuid4(),
                            metadata_json={"role": "admin"},
                            created_at=base,
                        )
                    )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def _insert_custom_audit(
    tenant_id: UUID,
    actor_id: UUID,
    *,
    action: str,
    entity_type: str,
    entity_id: UUID,
    created_at: datetime,
    ip: str | None = None,
) -> None:
    assert DATABASE_URL is not None

    async def run() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add(
                    AuditLogRecord(
                        tenant_id=tenant_id,
                        action=action,
                        ip=ip,
                        actor_id=actor_id,
                        actor_role="owner",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        metadata_json={"role": "admin"},
                        created_at=created_at,
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def _mfa_attempts(tenant_id: UUID, user_id: UUID) -> tuple[int, object]:
    assert DATABASE_URL is not None

    async def run() -> tuple[int, object]:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                row = (
                    await session.execute(
                        select(User.mfa_failed_attempts, User.mfa_locked_until).where(
                            User.tenant_id == tenant_id,
                            User.id == user_id,
                        )
                    )
                ).one()
                return int(row.mfa_failed_attempts), row.mfa_locked_until
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_admin_create_requires_step_up_and_audits(seeded: SeededAdmins) -> None:
    email = f"new-admin-{uuid4().hex[:8]}@example.com"
    with client_for(seeded.domain_a) as client:
        owner = _login(client, seeded.owner_email)
        missing = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            json={"email": email, "password": ADMIN_PASSWORD},
        )
        invalid = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            json={"email": email, "password": ADMIN_PASSWORD, "mfa_code": "000000"},
        )
        unicode_code = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            json={"email": email, "password": ADMIN_PASSWORD, "mfa_code": "١٢٣٤٥٦"},
        )
        attempts_after_unicode, _locked = _mfa_attempts(seeded.tenant_a, seeded.owner_id)
        compromised = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            json={
                "email": email,
                "password": "password123",
                "mfa_code": next_step_code(),
            },
        )
        created = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            json={
                "email": email,
                "name": "New Admin",
                "password": ADMIN_PASSWORD,
                "mfa_code": next_step_code(),
            },
        )
        duplicate = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(_login(client, seeded.owner_b_email)),
            json={
                "email": email,
                "password": ADMIN_PASSWORD,
                "mfa_code": next_step_code(),
            },
        )
        listed = client.get(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            params={"q": "new-admin"},
        )

        admin_token = _login(client, seeded.admin_email)
        forbidden = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={"email": "nope@example.com", "password": ADMIN_PASSWORD},
        )

    assert missing.status_code == 401
    assert missing.json()["code"] == "invalid_mfa_code"
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "invalid_mfa_code"
    assert unicode_code.status_code == 401
    assert unicode_code.json()["code"] == "invalid_mfa_code"
    assert attempts_after_unicode == 3
    assert compromised.status_code == 422
    assert compromised.json()["code"] == "validation_error"
    assert "password" in compromised.json()["fields"]
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "admin"
    assert created.json()["mfa_enabled"] is False
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "email_taken"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["email"] == email
    assert forbidden.status_code == 403
    rows = _audit_rows(seeded.tenant_a)
    assert [row.action for row in rows] == ["admin.created"]
    assert rows[0].actor_id == seeded.owner_id
    assert rows[0].metadata_json == {"role": "admin"}


def test_admin_deactivation_revokes_sessions_and_is_idempotent(seeded: SeededAdmins) -> None:
    email = f"revoked-{uuid4().hex[:8]}@example.com"
    with client_for(seeded.domain_a) as client:
        owner = _login(client, seeded.owner_email)
        created = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            json={
                "email": email,
                "password": ADMIN_PASSWORD,
                "mfa_code": next_step_code(),
            },
        )
        assert created.status_code == 201, created.text
        target_id = created.json()["id"]

        admin_client = client_for(seeded.domain_a)
        admin_client.__enter__()
        try:
            admin_payload = login_with_mfa(admin_client, email, password=ADMIN_PASSWORD)
            admin_access = str(admin_payload["access_token"])
            admin_refresh = admin_client.cookies.get("__Host-rt")
            assert admin_refresh is not None

            self_deactivate = client.post(
                f"/api/v1/admin/users/{seeded.owner_id}/deactivate",
                headers=auth_headers(owner),
            )
            foreign = client.post(
                f"/api/v1/admin/users/{seeded.foreign_user_id}/deactivate",
                headers=auth_headers(owner),
            )
            deactivated = client.post(
                f"/api/v1/admin/users/{target_id}/deactivate",
                headers=auth_headers(owner),
            )
            repeated = client.post(
                f"/api/v1/admin/users/{target_id}/deactivate",
                headers=auth_headers(owner),
            )

            stale_access = admin_client.get(
                "/api/v1/auth/session",
                headers=auth_headers(admin_access),
            )
            admin_client.cookies.clear()
            stale_refresh = admin_client.post(
                "/api/v1/auth/refresh",
                cookies={"__Host-rt": admin_refresh},
            )
        finally:
            admin_client.close()

    assert self_deactivate.status_code == 409
    assert self_deactivate.json()["code"] == "self_deactivation_not_allowed"
    assert foreign.status_code == 404
    assert deactivated.status_code == 204, deactivated.text
    assert repeated.status_code == 204
    assert stale_access.status_code == 403
    assert stale_refresh.status_code == 401
    rows = _audit_rows(seeded.tenant_a)
    assert [row.action for row in rows].count("admin.deactivated") == 1


def test_admin_create_step_up_lockout(seeded: SeededAdmins) -> None:
    email = f"locked-{uuid4().hex[:8]}@example.com"
    with client_for(seeded.domain_a) as client:
        owner = _login(client, seeded.owner_email)
        for _ in range(5):
            response = client.post(
                "/api/v1/admin/users",
                headers=auth_headers(owner),
                json={
                    "email": email,
                    "password": ADMIN_PASSWORD,
                    "mfa_code": "000000",
                },
            )
            assert response.status_code == 401
        locked = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            json={
                "email": email,
                "password": ADMIN_PASSWORD,
                "mfa_code": next_step_code(),
            },
        )

    assert locked.status_code == 429
    assert locked.json()["code"] == "rate_limited"
    assert int(locked.headers["Retry-After"]) > 0
    attempts, locked_until = _mfa_attempts(seeded.tenant_a, seeded.owner_id)
    assert attempts == 5
    assert locked_until is not None


def test_audit_log_filters_keyset_and_permissions(seeded: SeededAdmins) -> None:
    _insert_audit_rows(seeded.tenant_a, seeded.owner_id, 5)
    category_id = uuid4()
    _insert_custom_audit(
        seeded.tenant_a,
        seeded.owner_id,
        action="admin.deactivated",
        entity_type="category",
        entity_id=category_id,
        created_at=datetime.now(UTC) - timedelta(days=2),
    )
    with client_for(seeded.domain_a) as client:
        owner = _login(client, seeded.owner_email)
        first = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(owner),
            params={"limit": 2},
        )
        assert first.status_code == 200, first.text
        cursor = first.json()["next_cursor"]
        assert cursor
        second = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(owner),
            params={"limit": 2, "cursor": cursor},
        )
        filtered = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(owner),
            params={"actor_id": str(seeded.owner_id)},
        )
        by_action = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(owner),
            params={"action": "admin.deactivated"},
        )
        by_entity = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(owner),
            params={"entity_type": "category", "entity_id": str(category_id)},
        )
        by_date = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(owner),
            params={
                "from": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
                "to": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            },
        )
        invalid_entity_filter = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(owner),
            params={"entity_type": "user"},
        )
        cursor_mismatch = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(owner),
            params={"limit": 2, "cursor": cursor, "actor_id": str(uuid4())},
        )
        admin = _login(client, seeded.admin_email)
        forbidden = client.get(
            "/api/v1/admin/audit-log",
            headers=auth_headers(admin),
        )

    assert first.status_code == 200
    assert len(first.json()["items"]) == 2
    assert first.headers["Cache-Control"] == "no-store"
    assert second.status_code == 200
    assert len(second.json()["items"]) == 2
    first_ids = {item["id"] for item in first.json()["items"]}
    second_ids = {item["id"] for item in second.json()["items"]}
    assert not first_ids & second_ids
    assert filtered.status_code == 200
    assert all(item["actor_id"] == str(seeded.owner_id) for item in filtered.json()["items"])
    assert by_action.status_code == 200
    assert [item["action"] for item in by_action.json()["items"]] == ["admin.deactivated"]
    assert by_entity.status_code == 200
    assert [item["entity_id"] for item in by_entity.json()["items"]] == [str(category_id)]
    assert by_date.status_code == 200
    assert [item["entity_id"] for item in by_date.json()["items"]] == [str(category_id)]
    assert invalid_entity_filter.status_code == 422
    assert cursor_mismatch.status_code == 422
    assert forbidden.status_code == 403


def test_concurrent_owner_deactivation_keeps_one_owner(seeded: SeededAdmins) -> None:
    with client_for(seeded.domain_a) as client:
        owner = _login(client, seeded.owner_email)
        owner_b = _login(client, seeded.owner_b_email)

    def deactivate(actor_token: str, target_id: UUID) -> int:
        with client_for(seeded.domain_a) as client:
            response = client.post(
                f"/api/v1/admin/users/{target_id}/deactivate",
                headers=auth_headers(actor_token),
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(deactivate, owner, seeded.owner_b_id)
        second = executor.submit(deactivate, owner_b, seeded.owner_id)
        statuses = [first.result(), second.result()]

    assert sorted(statuses) == [204, 403]

    async def count_owners() -> int:
        assert DATABASE_URL is not None
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                result = await session.execute(
                    select(User).where(
                        User.tenant_id == seeded.tenant_a,
                        User.role == "owner",
                        User.is_active.is_(True),
                    )
                )
                return len(result.scalars().all())
        finally:
            await engine.dispose()

    assert asyncio.run(count_owners()) == 1


def test_admin_list_permissions_and_validation(seeded: SeededAdmins) -> None:
    with client_for(seeded.domain_a) as client:
        user_token = _login(client, seeded.user_email)
        admin_token = _login(client, seeded.admin_email)
        owner = _login(client, seeded.owner_email)
        by_role = client.get(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            params={"role": "admin"},
        )
        invalid_role = client.get(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            params={"role": "invalid"},
        )
        too_large = client.get(
            "/api/v1/admin/users",
            headers=auth_headers(owner),
            params={"limit": 101},
        )
        user_forbidden = client.get(
            "/api/v1/admin/users",
            headers=auth_headers(user_token),
        )
        admin_forbidden = client.get(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
        )

    assert by_role.status_code == 200
    assert [item["role"] for item in by_role.json()["items"]] == ["admin"]
    assert set(by_role.json()["items"][0]) == {
        "id",
        "email",
        "name",
        "role",
        "is_active",
        "mfa_enabled",
        "created_at",
    }
    assert invalid_role.status_code == 422
    assert too_large.status_code == 422
    assert user_forbidden.status_code == 403
    assert admin_forbidden.status_code == 403


def test_audit_log_ip_serialization_and_invalid_cursor(seeded: SeededAdmins) -> None:
    addresses = {"192.0.2.42", "2001:db8::42"}
    for ip in addresses:
        _insert_custom_audit(
            seeded.tenant_a,
            seeded.owner_id,
            action="admin.created",
            entity_type="user",
            entity_id=uuid4(),
            created_at=datetime.now(UTC),
            ip=ip,
        )

    with client_for(seeded.domain_a) as client:
        headers = auth_headers(_login(client, seeded.owner_email))
        response = client.get("/api/v1/admin/audit-log", headers=headers)
        assert response.status_code == 200, response.text
        assert {item["ip"] for item in response.json()["items"]} == addresses

        malformed = ["", "%", "!!e30=", base64.urlsafe_b64encode(b"null").decode()]
        malformed.extend(base64.urlsafe_b64encode(raw).decode() for raw in (b"[]", b"7", b'"text"'))
        for cursor in malformed:
            response = client.get(
                "/api/v1/admin/audit-log",
                headers=headers,
                params={"cursor": cursor},
            )
            assert response.status_code == 422
            assert response.json()["fields"] == {"cursor": "invalid cursor"}


@pytest.mark.parametrize("action", ["create", "deactivate"])
def test_admin_mutation_rechecks_actor_token_generation_under_lock(
    seeded: SeededAdmins,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    assert DATABASE_URL is not None
    database_url = DATABASE_URL
    lock_tenant = AdminUserRepository.lock_tenant

    async def lock_after_revocation(repository: AdminUserRepository) -> None:
        # Revoke the authenticated generation after get_current_user and before row locking.
        engine = create_engine(database_url)
        try:
            async with create_session_factory(engine)() as session:
                await session.execute(
                    update(User).where(User.id == seeded.owner_id).values(token_version=2)
                )
                await session.commit()
        finally:
            await engine.dispose()
        await lock_tenant(repository)

    monkeypatch.setattr(AdminUserRepository, "lock_tenant", lock_after_revocation)
    with client_for(seeded.domain_a) as client:
        headers = auth_headers(_login(client, seeded.owner_email))
        if action == "create":
            response = client.post(
                "/api/v1/admin/users",
                headers=headers,
                json={
                    "email": f"new-admin-{uuid4().hex[:8]}@example.com",
                    "password": ADMIN_PASSWORD,
                    "mfa_code": next_step_code(),
                },
            )
        else:
            response = client.post(
                f"/api/v1/admin/users/{seeded.owner_b_id}/deactivate", headers=headers
            )
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "token_invalid"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert _audit_rows(seeded.tenant_a) == []
