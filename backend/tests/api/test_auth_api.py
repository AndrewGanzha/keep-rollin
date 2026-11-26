from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

import app.api.auth_deps as auth_deps
from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.infrastructure.postgres.models.refresh_session_record import RefreshSessionRecord
from src.infrastructure.security.password_hasher import Argon2PasswordHasher
from tests.api.auth_helpers import enable_mfa, login_with_mfa

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"
PASSWORD = "Bike-Rider-2026!"
OWNER_PERMISSIONS = {
    "catalog.manage",
    "settings.manage",
    "admins.manage",
    "offers.manage",
    "calendar.view",
    "calendar.block",
    "verification.review",
    "tickets.manage",
    "rentals.manage",
    "analytics.view",
    "audit.view",
}
ADMIN_PERMISSIONS = {
    "calendar.view",
    "calendar.block",
    "verification.review",
    "tickets.manage",
    "rentals.manage",
    "analytics.view",
}


@dataclass(frozen=True)
class SeededAuth:
    domain_a: str
    domain_b: str
    tenant_a: UUID
    tenant_b: UUID
    owner_id: UUID
    owner_email: str
    admin_email: str
    legacy_email: str
    long_legacy_email: str
    long_name_email: str


def seed_auth() -> SeededAuth:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    hasher = Argon2PasswordHasher()
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
    owner_email = f"owner-{suffix}@example.com"
    admin_email = f"admin-{suffix}@example.com"
    legacy_email = f"legacy-{suffix}@example.com"
    long_legacy_email = f"{'a' * 130}@example.com"
    long_name_email = f"long-name-{suffix}@example.com"
    owner = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=owner_email,
        name="Owner",
        role="owner",
        password_hash=hasher.hash(PASSWORD),
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    admin = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=admin_email,
        name="Admin",
        role="admin",
        password_hash=hasher.hash(PASSWORD),
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    legacy = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=legacy_email,
        name="Legacy",
        role="user",
        password_hash=None,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    long_legacy = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=long_legacy_email,
        name="",
        role="user",
        password_hash=None,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    long_name = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=long_name_email,
        name="n" * 130,
        role="user",
        password_hash=None,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    enable_mfa(owner)
    enable_mfa(admin)

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all([owner, admin, legacy, long_legacy, long_name])
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededAuth(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_a=tenant_a.id,
        tenant_b=tenant_b.id,
        owner_id=owner.id,
        owner_email=owner_email,
        admin_email=admin_email,
        legacy_email=legacy_email,
        long_legacy_email=long_legacy_email,
        long_name_email=long_name_email,
    )


def cleanup_auth(tenant_ids: tuple[UUID, UUID]) -> None:
    assert DATABASE_URL is not None

    async def cleanup() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(cleanup())


def set_owner_active(tenant_id: UUID, user_id: UUID, *, is_active: bool) -> None:
    assert DATABASE_URL is not None

    async def update_owner() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(
                    update(User)
                    .where(User.tenant_id == tenant_id, User.id == user_id)
                    .values(is_active=is_active)
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(update_owner())


def refresh_session_state(
    tenant_id: UUID,
    token: str,
) -> tuple[UUID, datetime | None, UUID | None]:
    assert DATABASE_URL is not None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def read_state() -> tuple[UUID, datetime | None, UUID | None]:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                result = await session.execute(
                    select(RefreshSessionRecord).where(
                        RefreshSessionRecord.tenant_id == tenant_id,
                        RefreshSessionRecord.token_hash == token_hash,
                    )
                )
                record = result.scalar_one()
                return record.id, record.revoked_at, record.replaced_by_id
        finally:
            await engine.dispose()

    return asyncio.run(read_state())


def expire_refresh_token(tenant_id: UUID, token: str) -> None:
    assert DATABASE_URL is not None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def expire() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(
                    update(RefreshSessionRecord)
                    .where(
                        RefreshSessionRecord.tenant_id == tenant_id,
                        RefreshSessionRecord.token_hash == token_hash,
                    )
                    .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(expire())


@pytest.fixture
def seeded() -> Iterator[SeededAuth]:
    value = seed_auth()
    try:
        yield value
    finally:
        cleanup_auth((value.tenant_a, value.tenant_b))


def client_for(domain: str, *, browser_headers: bool = True) -> TestClient:
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
    headers = (
        {
            "Sec-Fetch-Site": "same-origin",
            "Origin": f"https://{domain}",
        }
        if browser_headers
        else None
    )
    return TestClient(
        create_app(settings),
        base_url=f"https://{domain}",
        headers=headers,
    )


def _login(client: TestClient, email: str) -> dict[str, object]:
    return login_with_mfa(client, email)


def test_register_creates_user_and_secure_cookie(seeded: SeededAuth) -> None:
    email = f"rider-{uuid4().hex[:8]}@example.com"
    with client_for(seeded.domain_a) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "name": "Rider"},
        )

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert payload["user"]["email"] == email
    assert payload["user"]["role"] == "user"
    assert payload["user"]["verification_status"] == "pending"
    assert payload["role"] == "user"
    assert payload["permissions"] == []
    assert payload["expires_in"] == 900
    cookie = response.headers["set-cookie"]
    assert "__Host-rt=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie

    claims = jwt.decode(
        str(payload["access_token"]),
        JWT_SECRET,
        algorithms=["HS256"],
    )
    assert claims["sub"]
    assert claims["tnt"] == str(seeded.tenant_a)
    assert claims["role"] == "user"
    assert claims["ver"] == 1
    assert claims["jti"]
    assert claims["exp"]


def test_register_accepts_documented_email_phone_password_payload(seeded: SeededAuth) -> None:
    email = f"phone-{uuid4().hex[:8]}@example.com"
    with client_for(seeded.domain_a) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "phone": "+79990000000", "password": PASSWORD},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["user"]["email"] == email
    assert payload["user"]["name"] == email.split("@", 1)[0]


def test_compromised_password_is_rejected(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"weak-{uuid4().hex[:8]}@example.com",
                "password": "password123",
                "name": "Rider",
            },
        )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "validation_error"
    assert "password" in response.json()["fields"]


def test_duplicate_email_and_short_password(seeded: SeededAuth) -> None:
    email = f"dup-{uuid4().hex[:8]}@example.com"
    with client_for(seeded.domain_a) as client:
        first = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "name": "Rider"},
        )
        duplicate = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "name": "Rider"},
        )
        short = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"short-{uuid4().hex[:8]}@example.com",
                "password": "short",
                "name": "R",
            },
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "email_taken"
    assert short.status_code == 422
    assert short.headers["content-type"] == "application/problem+json"
    assert short.json()["code"] == "validation_error"
    assert "password" in short.json()["fields"]


def test_overlong_email_is_rejected_before_database_access(seeded: SeededAuth) -> None:
    emails = (
        f"{'a' * 250}@example.com",
        f"{'İ' * 200}@example.com",
    )
    with client_for(seeded.domain_a) as client:
        responses = []
        for email in emails:
            responses.append(
                client.post(
                    "/api/v1/auth/register",
                    json={"email": email, "password": PASSWORD, "name": "Rider"},
                )
            )
            responses.append(
                client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": PASSWORD},
                )
            )

    for response in responses:
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert "email" in response.json()["fields"]


def test_nul_bytes_are_rejected_before_database_access(seeded: SeededAuth) -> None:
    email = f"nul-{uuid4().hex[:8]}@example.com"
    with client_for(seeded.domain_a) as client:
        bad_email = client.post(
            "/api/v1/auth/register",
            json={"email": f"{email}\x00", "password": PASSWORD, "name": "Rider"},
        )
        bad_password = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": f"{PASSWORD}\x00", "name": "Rider"},
        )
        bad_name = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "name": "Rider\x00"},
        )
        bad_login = client.post(
            "/api/v1/auth/login",
            json={"email": f"{seeded.owner_email}\x00", "password": PASSWORD},
        )

    for response, field in (
        (bad_email, "email"),
        (bad_password, "password"),
        (bad_name, "name"),
        (bad_login, "email"),
    ):
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert field in response.json()["fields"]


def test_login_session_and_tenant_mismatch(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        wrong = client.post(
            "/api/v1/auth/login",
            json={"email": seeded.owner_email, "password": "wrong-password"},
        )
        login = _login(client, seeded.owner_email)
        session = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )

    assert wrong.status_code == 401
    assert wrong.json()["code"] == "invalid_credentials"
    assert login["role"] == "owner"
    owner_permissions = cast(list[str], login["permissions"])
    assert set(owner_permissions) == OWNER_PERMISSIONS
    assert session.status_code == 200
    assert session.headers["Cache-Control"] == "no-store"
    assert session.json()["role"] == "owner"
    assert session.json()["tenant_id"] == str(seeded.tenant_a)
    assert session.json()["offer_accepted"] is False

    with client_for(seeded.domain_b) as other:
        mismatch = other.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
    assert mismatch.status_code == 403
    assert mismatch.json()["code"] == "tenant_mismatch"


def test_refresh_rotation_reuse_revokes_family(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        _login(client, seeded.owner_email)
        original = client.cookies.get("__Host-rt")
        assert original is not None

        rotated = client.post("/api/v1/auth/refresh")
        assert rotated.status_code == 200
        new_token = client.cookies.get("__Host-rt")
        assert new_token is not None and new_token != original

        client.cookies.clear()
        replay = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": original},
        )
        assert replay.status_code == 401
        assert replay.json()["code"] == "session_revoked"

        revoked_new = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": new_token},
        )
    assert revoked_new.status_code == 401
    assert revoked_new.json()["code"] == "session_revoked"


def test_replay_of_previous_generation_revokes_concurrent_rotation(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        _login(client, seeded.owner_email)
        first_generation = client.cookies.get("__Host-rt")
        assert first_generation is not None
        rotated = client.post("/api/v1/auth/refresh")
        assert rotated.status_code == 200
        second_generation = client.cookies.get("__Host-rt")
        assert second_generation is not None

    def refresh_with(token: str) -> tuple[int, str | None]:
        with client_for(seeded.domain_a) as thread_client:
            response = thread_client.post(
                "/api/v1/auth/refresh",
                cookies={"__Host-rt": token},
            )
            return int(response.status_code), response.cookies.get("__Host-rt")

    with ThreadPoolExecutor(max_workers=2) as executor:
        replay_future = executor.submit(refresh_with, first_generation)
        rotation_future = executor.submit(refresh_with, second_generation)
        replay_status, _ = replay_future.result()
        rotation_status, third_generation = rotation_future.result()

    assert replay_status == 401
    assert rotation_status in (200, 401)
    if rotation_status == 200:
        assert third_generation is not None
        with client_for(seeded.domain_a) as client:
            after_replay = client.post(
                "/api/v1/auth/refresh",
                cookies={"__Host-rt": third_generation},
            )
        assert after_replay.status_code == 401
        assert after_replay.json()["code"] == "session_revoked"


def test_logout_revokes_current_logical_session(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        _login(client, seeded.owner_email)
        cookie = client.cookies.get("__Host-rt")
        assert cookie is not None
        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 204
        refresh = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": cookie},
        )
    assert refresh.status_code == 401


def test_logout_with_stale_generation_revokes_active_session(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        _login(client, seeded.owner_email)
        first_generation = client.cookies.get("__Host-rt")
        assert first_generation is not None
        rotated = client.post("/api/v1/auth/refresh")
        assert rotated.status_code == 200
        second_generation = client.cookies.get("__Host-rt")
        assert second_generation is not None

        client.cookies.clear()
        logout = client.post(
            "/api/v1/auth/logout",
            cookies={"__Host-rt": first_generation},
        )
        assert logout.status_code == 204
        refresh = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": second_generation},
        )
    assert refresh.status_code == 401


def test_expired_previous_generation_does_not_revoke_family(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        _login(client, seeded.owner_email)
        first_generation = client.cookies.get("__Host-rt")
        assert first_generation is not None
        rotated = client.post("/api/v1/auth/refresh")
        assert rotated.status_code == 200
        second_generation = client.cookies.get("__Host-rt")
        assert second_generation is not None

        before = refresh_session_state(seeded.tenant_a, first_generation)
        second_id, _, _ = refresh_session_state(seeded.tenant_a, second_generation)
        assert before[2] == second_id
        expire_refresh_token(seeded.tenant_a, first_generation)
        replay = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": first_generation},
        )
        still_active = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": second_generation},
        )
        after = refresh_session_state(seeded.tenant_a, first_generation)

    assert replay.status_code == 401
    assert replay.json()["code"] == "token_invalid"
    assert still_active.status_code == 200
    assert before[1] is not None
    assert after == before


def test_expired_logout_does_not_revoke_family(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        _login(client, seeded.owner_email)
        first_generation = client.cookies.get("__Host-rt")
        assert first_generation is not None
        rotated = client.post("/api/v1/auth/refresh")
        assert rotated.status_code == 200
        second_generation = client.cookies.get("__Host-rt")
        assert second_generation is not None

        expire_refresh_token(seeded.tenant_a, first_generation)
        client.cookies.clear()
        logout = client.post(
            "/api/v1/auth/logout",
            cookies={"__Host-rt": first_generation},
        )
        still_active = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": second_generation},
        )

    assert logout.status_code == 204
    assert still_active.status_code == 200


def test_legacy_user_without_password_returns_401(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        for email in (
            seeded.legacy_email,
            seeded.long_legacy_email,
            seeded.long_name_email,
        ):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": PASSWORD},
            )
            assert response.status_code == 401
            assert response.json()["code"] == "invalid_credentials"


def test_admin_permissions_and_csrf_guard(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        admin = _login(client, seeded.admin_email)
        assert admin["role"] == "admin"
        permissions = cast(list[str], admin["permissions"])
        assert set(permissions) == ADMIN_PERMISSIONS
        assert "catalog.manage" not in permissions

        bad_origin = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://evil.example"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        malformed_origin = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://[::1"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        wrong_scheme = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"http://{seeded.domain_a}"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        origin_with_path = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://{seeded.domain_a}/login"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        origin_with_query = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://{seeded.domain_a}?next=1"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        zero_port = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://{seeded.domain_a}:0"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        empty_query = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://{seeded.domain_a}?"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        fragment = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://{seeded.domain_a}#login"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        userinfo = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://user:pass@{seeded.domain_a}"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        empty_userinfo = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://@{seeded.domain_a}"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        userinfo_refresh = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": f"https://user:pass@{seeded.domain_a}"},
        )
        userinfo_logout = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": f"https://user:pass@{seeded.domain_a}"},
        )
        duplicate_origin = client.post(
            "/api/v1/auth/login",
            headers=[
                ("Origin", f"https://{seeded.domain_a}"),
                ("Origin", "https://evil.example"),
            ],
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        good_origin = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://{seeded.domain_a}"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        good_origin_with_port = client.post(
            "/api/v1/auth/login",
            headers={"Origin": f"https://{seeded.domain_a}:443"},
            json={"email": seeded.owner_email, "password": PASSWORD},
        )

    assert bad_origin.status_code == 403
    assert malformed_origin.status_code == 403
    assert wrong_scheme.status_code == 403
    assert origin_with_path.status_code == 403
    assert origin_with_query.status_code == 403
    assert zero_port.status_code == 403
    assert empty_query.status_code == 403
    assert fragment.status_code == 403
    assert userinfo.status_code == 403
    assert empty_userinfo.status_code == 403
    assert userinfo_refresh.status_code == 403
    assert userinfo_logout.status_code == 403
    assert duplicate_origin.status_code == 403
    assert good_origin.status_code == 200
    assert good_origin_with_port.status_code == 200


def test_auth_mutations_require_origin_and_fetch_metadata(seeded: SeededAuth) -> None:
    payload = {"email": seeded.owner_email, "password": PASSWORD}
    origin = f"https://{seeded.domain_a}"
    with client_for(seeded.domain_a, browser_headers=False) as client:
        missing = client.post("/api/v1/auth/login", json=payload)
        fetch_only = client.post(
            "/api/v1/auth/login",
            headers={"Sec-Fetch-Site": "none"},
            json=payload,
        )
        origin_only = client.post(
            "/api/v1/auth/login",
            headers={"Origin": origin},
            json=payload,
        )
        both = client.post(
            "/api/v1/auth/login",
            headers={"Origin": origin, "Sec-Fetch-Site": "none"},
            json=payload,
        )
        cross_site = client.post(
            "/api/v1/auth/login",
            headers={"Origin": origin, "Sec-Fetch-Site": "cross-site"},
            json=payload,
        )

    assert missing.status_code == 403
    assert fetch_only.status_code == 403
    assert origin_only.status_code == 403
    assert both.status_code == 200
    assert cross_site.status_code == 403


class BlockingHasher:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = 0
        self.lock = threading.Lock()

    def hash(self, password: str) -> str:
        return "hash"

    def verify(self, password_hash: str, password: str) -> bool:
        with self.lock:
            self.started += 1
        return self.release.wait(5)

    def verify_dummy(self, password: str) -> None:
        pass


async def test_password_saturation_returns_503(
    seeded: SeededAuth,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hasher = BlockingHasher()
    monkeypatch.setattr(auth_deps, "get_password_hasher", lambda: hasher)
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
        database_role="keep_rollin_app",
        jwt_secret=JWT_SECRET,
        refresh_cookie_secure=True,
        password_work_timeout_seconds=0.05,
    )
    application = create_app(settings)
    transport = httpx.ASGITransport(app=application)
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=transport,
            base_url=f"https://{seeded.domain_a}",
            headers={
                "Sec-Fetch-Site": "same-origin",
                "Origin": f"https://{seeded.domain_a}",
            },
        ) as client,
    ):

        async def login() -> httpx.Response:
            return await client.post(
                "/api/v1/auth/login",
                json={"email": seeded.owner_email, "password": PASSWORD},
            )

        first = asyncio.create_task(login())
        second = asyncio.create_task(login())
        for _ in range(200):
            if hasher.started == 2:
                break
            await asyncio.sleep(0.01)
        else:
            hasher.release.set()
            await asyncio.gather(first, second)
            raise AssertionError("password workers did not start")
        try:
            saturated = await login()
        finally:
            hasher.release.set()
        successful = await asyncio.gather(first, second)

    assert saturated.status_code == 503
    assert saturated.json()["code"] == "service_unavailable"
    assert [response.status_code for response in successful] == [200, 200]


def test_invalid_email_and_expired_token(seeded: SeededAuth) -> None:
    expired = cast(
        str,
        jwt.encode(
            {
                "sub": str(uuid4()),
                "tnt": str(seeded.tenant_a),
                "role": "owner",
                "ver": 1,
                "jti": str(uuid4()),
                "exp": datetime.now(UTC) - timedelta(seconds=1),
            },
            JWT_SECRET,
            algorithm="HS256",
        ),
    )
    with client_for(seeded.domain_a) as client:
        invalid_email = client.post(
            "/api/v1/auth/register",
            json={"email": "not-an-email", "password": PASSWORD, "name": "Rider"},
        )
        expired_response = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {expired}"},
        )

    assert invalid_email.status_code == 422
    assert invalid_email.json()["code"] == "validation_error"
    assert "email" in invalid_email.json()["fields"]
    assert expired_response.status_code == 401
    assert expired_response.json()["code"] == "token_expired"


def _access_token(
    *,
    seeded: SeededAuth,
    secret: str,
    token_version: int = 1,
) -> str:
    return cast(
        str,
        jwt.encode(
            {
                "sub": str(seeded.owner_id),
                "tnt": str(seeded.tenant_a),
                "role": "owner",
                "ver": token_version,
                "jti": str(uuid4()),
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            secret,
            algorithm="HS256",
        ),
    )


def test_tampered_signature_and_stale_token_version_are_rejected(seeded: SeededAuth) -> None:
    tampered = _access_token(
        seeded=seeded,
        secret="other-secret-keep-rollin-0123456789abcdef",
    )
    stale = _access_token(seeded=seeded, secret=JWT_SECRET, token_version=2)
    with client_for(seeded.domain_a) as client:
        tampered_response = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        stale_response = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {stale}"},
        )

    assert tampered_response.status_code == 401
    assert tampered_response.json()["code"] == "token_invalid"
    assert tampered_response.headers["WWW-Authenticate"] == "Bearer"
    assert stale_response.status_code == 401
    assert stale_response.json()["code"] == "token_invalid"
    assert stale_response.headers["WWW-Authenticate"] == "Bearer"


def test_inactive_user_access_is_rejected(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        login = _login(client, seeded.owner_email)
        set_owner_active(seeded.tenant_a, seeded.owner_id, is_active=False)
        response = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden_role"


def test_concurrent_refresh_has_one_winner(seeded: SeededAuth) -> None:
    with client_for(seeded.domain_a) as client:
        _login(client, seeded.owner_email)
        cookie = client.cookies.get("__Host-rt")
        assert cookie is not None

    def refresh_once() -> int:
        with client_for(seeded.domain_a) as thread_client:
            response = thread_client.post(
                "/api/v1/auth/refresh",
                cookies={"__Host-rt": cookie},
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: refresh_once(), range(2)))

    assert sorted(statuses) == [200, 401]
