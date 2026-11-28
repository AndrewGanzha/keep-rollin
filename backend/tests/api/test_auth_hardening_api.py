from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

import app.api.auth_deps as auth_deps
from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.application.services.auth import hash_refresh_token
from src.infrastructure.postgres.models.mfa_challenge_record import MfaChallengeRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.password_reset_token_record import (
    PasswordResetTokenRecord,
)
from src.infrastructure.postgres.models.refresh_session_record import RefreshSessionRecord
from src.infrastructure.security.password_hasher import Argon2PasswordHasher
from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.security.totp import code_at
from tests.api.auth_helpers import MFA_SECRET, enable_mfa, login_with_mfa

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"
PASSWORD = "Bike-Rider-2026!"
NEW_PASSWORD = "New-Bike-Rider-2026!"


@dataclass(frozen=True)
class SeededHardening:
    domain_a: str
    domain_b: str
    tenant_a: UUID
    tenant_b: UUID
    owner_id: UUID
    owner_email: str
    admin_email: str
    user_email: str
    inactive_email: str
    unenrolled_owner_id: UUID
    unenrolled_owner_email: str


def seed_hardening() -> SeededHardening:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    hasher = Argon2PasswordHasher()
    tenant_a = Tenant(
        id=uuid4(),
        name="Hardening A",
        slug=f"hardening-a-{suffix}",
        domain=f"hardening-a-{suffix}.test",
        subdomain=f"hardening-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Hardening B",
        slug=f"hardening-b-{suffix}",
        domain=f"hardening-b-{suffix}.test",
        subdomain=f"hardening-b-{suffix}",
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
    inactive = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"inactive-{suffix}@example.com",
        name="Inactive",
        role="user",
        password_hash=password_hash,
        verification_status="approved",
        is_active=False,
        token_version=1,
    )
    unenrolled = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"unenrolled-{suffix}@example.com",
        name="Unenrolled Owner",
        role="owner",
        password_hash=password_hash,
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
                session.add_all([owner, admin, user, inactive, unenrolled])
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededHardening(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_a=tenant_a.id,
        tenant_b=tenant_b.id,
        owner_id=owner.id,
        owner_email=owner.email,
        admin_email=admin.email,
        user_email=user.email,
        inactive_email=inactive.email,
        unenrolled_owner_id=unenrolled.id,
        unenrolled_owner_email=unenrolled.email,
    )


def cleanup(tenant_ids: tuple[UUID, UUID]) -> None:
    assert DATABASE_URL is not None

    async def run() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.fixture
def seeded() -> Iterator[SeededHardening]:
    value = seed_hardening()
    try:
        yield value
    finally:
        cleanup((value.tenant_a, value.tenant_b))


def client_for(
    domain: str,
    *,
    ip_limit: int = 10,
    email_limit: int = 10,
    window_seconds: int = 60,
) -> TestClient:
    assert DATABASE_URL is not None
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
        database_role="keep_rollin_app",
        jwt_secret=JWT_SECRET,
        refresh_cookie_secure=True,
        auth_rate_limit_per_minute=ip_limit,
        auth_rate_limit_email_per_minute=email_limit,
        auth_rate_limit_window_seconds=window_seconds,
    )
    return TestClient(
        create_app(settings),
        base_url=f"https://{domain}",
        headers={
            "Sec-Fetch-Site": "same-origin",
            "Origin": f"https://{domain}",
        },
    )


def _login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def _totp(secret: str = MFA_SECRET) -> str:
    return code_at(secret, timestamp=time.time())


def _wrong_totp() -> str:
    valid = _totp()
    return ("0" if valid[0] != "0" else "1") + valid[1:]


def _access_token(
    *,
    user_id: UUID,
    tenant_id: UUID,
    role: str = "owner",
    token_version: int = 1,
) -> str:
    return cast(
        str,
        jwt.encode(
            {
                "sub": str(user_id),
                "tnt": str(tenant_id),
                "role": role,
                "ver": token_version,
                "jti": str(uuid4()),
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            JWT_SECRET,
            algorithm="HS256",
        ),
    )


def _read_mfa_state(tenant_id: UUID, user_id: UUID) -> tuple[int, datetime | None, bool]:
    assert DATABASE_URL is not None

    async def run() -> tuple[int, datetime | None, bool]:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                result = await session.execute(
                    select(
                        User.mfa_failed_attempts,
                        User.mfa_locked_until,
                        User.mfa_enabled,
                    ).where(User.tenant_id == tenant_id, User.id == user_id)
                )
                row = result.one()
                return row.mfa_failed_attempts, row.mfa_locked_until, row.mfa_enabled
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _read_reset_token(tenant_id: UUID, user_id: UUID) -> str:
    return _read_reset_tokens(tenant_id, user_id)[-1]


def _read_reset_tokens(tenant_id: UUID, user_id: UUID) -> list[str]:
    assert DATABASE_URL is not None

    async def run() -> list[str]:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                result = await session.execute(
                    select(PasswordResetTokenRecord)
                    .where(
                        PasswordResetTokenRecord.tenant_id == tenant_id,
                        PasswordResetTokenRecord.user_id == user_id,
                    )
                    .order_by(PasswordResetTokenRecord.created_at)
                )
                records = list(result.scalars().all())
                box = SecretBox.from_settings(JWT_SECRET)
                tokens: list[str] = []
                for record in records:
                    assert record.token_secret_enc is not None
                    tokens.append(
                        box.decrypt(
                            record.token_secret_enc,
                            context=f"reset:{tenant_id}:{user_id}",
                        )
                    )
                return tokens
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _age_reset_requests(tenant_id: UUID, user_id: UUID, *, expected_messages: int) -> None:
    assert DATABASE_URL is not None

    async def run() -> None:
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine).begin() as session:
                event_ids = await session.scalars(
                    select(OutboxMessageRecord.id).where(
                        OutboxMessageRecord.tenant_id == tenant_id,
                        OutboxMessageRecord.user_id == user_id,
                        OutboxMessageRecord.event_type == "auth.password_reset",
                    )
                )
                assert len(event_ids.all()) == expected_messages
                await session.execute(
                    update(PasswordResetTokenRecord)
                    .where(
                        PasswordResetTokenRecord.tenant_id == tenant_id,
                        PasswordResetTokenRecord.user_id == user_id,
                    )
                    .values(created_at=datetime.now(UTC) - timedelta(minutes=2))
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def _count_challenges(tenant_id: UUID) -> int:
    assert DATABASE_URL is not None

    async def run() -> int:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                result = await session.execute(
                    select(MfaChallengeRecord).where(MfaChallengeRecord.tenant_id == tenant_id)
                )
                return len(result.scalars().all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _insert_refresh_session(tenant_id: UUID, user_id: UUID, raw_token: str) -> None:
    assert DATABASE_URL is not None
    session_id = uuid4()

    async def run() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add(
                    RefreshSessionRecord(
                        id=session_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        token_hash=hash_refresh_token(raw_token),
                        family_id=session_id,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                        user_agent="test",
                        ip="127.0.0.1",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def _insert_reset_token(
    tenant_id: UUID,
    user_id: UUID,
    raw_token: str,
    *,
    expires_at: datetime,
    consumed: bool = False,
) -> None:
    assert DATABASE_URL is not None

    async def run() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add(
                    PasswordResetTokenRecord(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                        token_secret_enc=None,
                        expires_at=expires_at,
                        consumed_at=datetime.now(UTC) if consumed else None,
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_staff_login_requires_enrollment_then_confirm(seeded: SeededHardening) -> None:
    stale_access = _access_token(
        user_id=seeded.unenrolled_owner_id,
        tenant_id=seeded.tenant_a,
        role="owner",
    )
    old_refresh = "pre-mfa-refresh-token"
    _insert_refresh_session(seeded.tenant_a, seeded.unenrolled_owner_id, old_refresh)
    with client_for(seeded.domain_a) as client:
        challenge = _login(client, seeded.unenrolled_owner_email)
        assert challenge["mfa_setup_required"] is True
        assert challenge["mfa_required"] is False
        assert challenge["access_token"] is None
        assert challenge["mfa_token"]
        assert "__Host-rt" not in challenge
        assert client.cookies.get("__Host-rt") is None

        setup = client.post(
            "/api/v1/auth/mfa/setup",
            json={"mfa_token": challenge["mfa_token"]},
        )
        assert setup.status_code == 200, setup.text
        secret = setup.json()["secret"]
        assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")

        confirm = client.post(
            "/api/v1/auth/mfa/confirm",
            json={
                "mfa_token": challenge["mfa_token"],
                "code": code_at(secret, timestamp=time.time()),
            },
        )
        assert confirm.status_code == 200, confirm.text
        payload = confirm.json()
        assert payload["user"]["role"] == "owner"
        assert len(payload["recovery_codes"]) == 10
        assert payload["access_token"]
        assert client.cookies.get("__Host-rt")

        session = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert session.status_code == 200
        assert session.json()["mfa_enabled"] is True

        stale = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {stale_access}"},
        )
        assert stale.status_code == 401
        assert stale.json()["code"] == "token_invalid"

        client.cookies.clear()
        stale_refresh = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": old_refresh},
        )
        assert stale_refresh.status_code == 401

        replay = client.post(
            "/api/v1/auth/mfa/confirm",
            json={
                "mfa_token": challenge["mfa_token"],
                "code": code_at(secret, timestamp=time.time()),
            },
        )
        assert replay.status_code == 401
        assert replay.json()["code"] == "token_invalid"


def test_staff_verify_with_totp_recovery_and_replay_protection(
    seeded: SeededHardening,
) -> None:
    with client_for(seeded.domain_a) as client:
        recovery_codes = _enroll_recovery_codes(client, seeded.unenrolled_owner_email)
        assert len(recovery_codes) == 10

    with client_for(seeded.domain_a) as client:
        first = _login(client, seeded.owner_email)
        assert first["mfa_required"] is True
        assert first["access_token"] is None
        verified = client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": first["mfa_token"], "code": _totp()},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["access_token"]
        reused_challenge = client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": first["mfa_token"], "code": _totp()},
        )
        assert reused_challenge.status_code == 401
        assert reused_challenge.json()["code"] == "token_invalid"

    with client_for(seeded.domain_a) as client:
        recovery_login = _login(client, seeded.unenrolled_owner_email)
        recovery = client.post(
            "/api/v1/auth/mfa/verify",
            json={
                "mfa_token": recovery_login["mfa_token"],
                "code": recovery_codes[0],
            },
        )
        assert recovery.status_code == 200, recovery.text
        assert recovery.json()["access_token"]

        reuse_login = _login(client, seeded.unenrolled_owner_email)
        reused_code = client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": reuse_login["mfa_token"], "code": recovery_codes[0]},
        )
        assert reused_code.status_code == 401
        assert reused_code.json()["code"] == "invalid_mfa_code"


def _enroll_recovery_codes(
    client: TestClient,
    email: str,
) -> list[str]:
    challenge = _login(client, email)
    setup = client.post(
        "/api/v1/auth/mfa/setup",
        json={"mfa_token": challenge["mfa_token"]},
    )
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    confirm = client.post(
        "/api/v1/auth/mfa/confirm",
        json={
            "mfa_token": challenge["mfa_token"],
            "code": code_at(secret, timestamp=time.time()),
        },
    )
    assert confirm.status_code == 200, confirm.text
    return cast(list[str], confirm.json()["recovery_codes"])


def test_mfa_lockout_survives_error_response(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a) as client:
        challenge = _login(client, seeded.owner_email)
        for _ in range(5):
            failed = client.post(
                "/api/v1/auth/mfa/verify",
                json={"mfa_token": challenge["mfa_token"], "code": _wrong_totp()},
            )
            assert failed.status_code == 401
            assert failed.json()["code"] == "invalid_mfa_code"
        locked = client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": challenge["mfa_token"], "code": _wrong_totp()},
        )

    assert locked.status_code == 429
    assert locked.json()["code"] == "rate_limited"
    assert int(locked.headers["Retry-After"]) > 0
    attempts, locked_until, enabled = _read_mfa_state(seeded.tenant_a, seeded.owner_id)
    assert attempts == 5
    assert locked_until is not None
    assert enabled is True


def test_concurrent_mfa_verify_has_one_winner(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a) as client:
        challenge = _login(client, seeded.owner_email)
    code = _totp()

    def verify() -> int:
        with client_for(seeded.domain_a) as client:
            response = client.post(
                "/api/v1/auth/mfa/verify",
                json={"mfa_token": challenge["mfa_token"], "code": code},
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: verify(), range(2)))

    assert sorted(statuses) == [200, 401]


def test_concurrent_invalid_mfa_attempts_persist_counter(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a) as client:
        challenge = _login(client, seeded.owner_email)

    def fail() -> int:
        with client_for(seeded.domain_a) as client:
            response = client.post(
                "/api/v1/auth/mfa/verify",
                json={"mfa_token": challenge["mfa_token"], "code": _wrong_totp()},
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(lambda _: fail(), range(5)))

    assert statuses == [401] * 5
    attempts, locked_until, _enabled = _read_mfa_state(seeded.tenant_a, seeded.owner_id)
    assert attempts == 5
    assert locked_until is not None


def test_access_token_requires_staff_mfa(seeded: SeededHardening) -> None:
    assert DATABASE_URL is not None
    token = _access_token(user_id=seeded.unenrolled_owner_id, tenant_id=seeded.tenant_a)
    with client_for(seeded.domain_a) as client:
        response = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 401
    assert response.json()["code"] == "token_invalid"


def test_admin_login_requires_mfa_and_challenge_is_not_bearer(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a) as client:
        challenge = _login(client, seeded.admin_email)
        assert challenge["mfa_required"] is True
        assert challenge["access_token"] is None
        bearer = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {challenge['mfa_token']}"},
        )
        assert bearer.status_code == 401
        assert bearer.json()["code"] == "token_invalid"

        verified = client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": challenge["mfa_token"], "code": _totp()},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["role"] == "admin"
        assert verified.json()["access_token"]


def test_refresh_rejects_pre_mfa_staff_session(seeded: SeededHardening) -> None:
    assert DATABASE_URL is not None
    raw_token = "pre-mfa-refresh-token"
    session_id = uuid4()

    async def insert() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add(
                    RefreshSessionRecord(
                        id=session_id,
                        tenant_id=seeded.tenant_a,
                        user_id=seeded.unenrolled_owner_id,
                        token_hash=hash_refresh_token(raw_token),
                        family_id=session_id,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                        user_agent="test",
                        ip="127.0.0.1",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(insert())
    with client_for(seeded.domain_a) as client:
        response = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": raw_token},
        )
    assert response.status_code == 401
    assert response.json()["code"] == "token_invalid"


def test_password_forgot_is_non_enumerating_and_reset_revokes_sessions(
    seeded: SeededHardening,
) -> None:
    with client_for(seeded.domain_a) as client:
        login = login_with_mfa(client, seeded.owner_email)
        old_access = str(login["access_token"])
        old_refresh = client.cookies.get("__Host-rt")
        assert old_refresh is not None
        second_refresh = "second-refresh-family"
        _insert_refresh_session(seeded.tenant_a, seeded.owner_id, second_refresh)

        bodies = []
        for email in (seeded.owner_email, "missing@example.com", seeded.inactive_email):
            response = client.post(
                "/api/v1/auth/password/forgot",
                json={"email": email},
            )
            assert response.status_code == 202
            bodies.append(response.json())
        assert bodies[0] == bodies[1] == bodies[2]

        reset_token = _read_reset_token(seeded.tenant_a, seeded.owner_id)
        reset = client.post(
            "/api/v1/auth/password/reset",
            json={"token": reset_token, "password": NEW_PASSWORD},
        )
        assert reset.status_code == 204, reset.text
        assert reset.headers["Cache-Control"] == "no-store"

        reused = client.post(
            "/api/v1/auth/password/reset",
            json={"token": reset_token, "password": NEW_PASSWORD},
        )
        assert reused.status_code == 401
        assert reused.json()["code"] == "token_invalid"

        stale_access = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {old_access}"},
        )
        assert stale_access.status_code == 401
        assert stale_access.json()["code"] == "token_invalid"

        client.cookies.clear()
        stale_refresh = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": old_refresh},
        )
        assert stale_refresh.status_code == 401
        second_stale = client.post(
            "/api/v1/auth/refresh",
            cookies={"__Host-rt": second_refresh},
        )
        assert second_stale.status_code == 401

    with client_for(seeded.domain_a) as client:
        old_password = client.post(
            "/api/v1/auth/login",
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        assert old_password.status_code == 401
        new_login = _login(client, seeded.owner_email, NEW_PASSWORD)
        assert new_login["mfa_required"] is True


def test_concurrent_reset_token_has_one_winner(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a) as client:
        client.post(
            "/api/v1/auth/password/forgot",
            json={"email": seeded.owner_email},
        )
    token = _read_reset_token(seeded.tenant_a, seeded.owner_id)

    def reset(password: str) -> int:
        with client_for(seeded.domain_a) as client:
            response = client.post(
                "/api/v1/auth/password/reset",
                json={"token": token, "password": password},
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(reset, [NEW_PASSWORD, "Other-Bike-Rider-2026!"]))

    assert sorted(statuses) == [204, 401]


def test_two_distinct_reset_tokens_have_one_winner(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a) as client:
        response = client.post("/api/v1/auth/password/forgot", json={"email": seeded.owner_email})
        assert response.status_code == 202
        _age_reset_requests(seeded.tenant_a, seeded.owner_id, expected_messages=1)
        response = client.post("/api/v1/auth/password/forgot", json={"email": seeded.owner_email})
        assert response.status_code == 202
    tokens = _read_reset_tokens(seeded.tenant_a, seeded.owner_id)
    assert len(tokens) == 2

    def reset(item: tuple[str, str]) -> int:
        token, password = item
        with client_for(seeded.domain_a) as client:
            response = client.post(
                "/api/v1/auth/password/reset",
                json={"token": token, "password": password},
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(
            executor.map(
                reset,
                [
                    (tokens[0], NEW_PASSWORD),
                    (tokens[1], "Other-Bike-Rider-2026!"),
                ],
            )
        )

    assert sorted(statuses) == [204, 401]


def test_concurrent_forgot_requests_queue_one_email(seeded: SeededHardening) -> None:
    def request(email: str) -> tuple[int, dict[str, str]]:
        with client_for(seeded.domain_a) as client:
            response = client.post("/api/v1/auth/password/forgot", json={"email": email})
            return response.status_code, cast(dict[str, str], response.json())

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(
            executor.map(
                request,
                [
                    seeded.owner_email,
                    seeded.owner_email.upper(),
                    seeded.owner_email,
                    "missing@example.com",
                ],
            )
        )

    assert all(receipt == receipts[0] for receipt in receipts)
    assert receipts[0][0] == 202
    assert len(_read_reset_tokens(seeded.tenant_a, seeded.owner_id)) == 1
    _age_reset_requests(seeded.tenant_a, seeded.owner_id, expected_messages=1)
    assert request(seeded.owner_email) == receipts[0]
    assert len(_read_reset_tokens(seeded.tenant_a, seeded.owner_id)) == 2
    _age_reset_requests(seeded.tenant_a, seeded.owner_id, expected_messages=2)


def test_expired_and_consumed_reset_tokens_are_rejected(seeded: SeededHardening) -> None:
    expired = "expired-reset-token-1234567890"
    consumed = "consumed-reset-token-1234567890"
    _insert_reset_token(
        seeded.tenant_a,
        seeded.owner_id,
        expired,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    _insert_reset_token(
        seeded.tenant_a,
        seeded.owner_id,
        consumed,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        consumed=True,
    )
    with client_for(seeded.domain_a) as client:
        for token in (expired, consumed):
            response = client.post(
                "/api/v1/auth/password/reset",
                json={"token": token, "password": NEW_PASSWORD},
            )
            assert response.status_code == 401
            assert response.json()["code"] == "token_invalid"


def test_login_rate_limit_returns_retry_after(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a, ip_limit=3, email_limit=100) as client:
        for _ in range(3):
            response = _login(client, seeded.owner_email)
            assert response["mfa_required"] is True
        before = _count_challenges(seeded.tenant_a)
        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        after = _count_challenges(seeded.tenant_a)

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) > 0
    assert after == before
    assert blocked.headers["Cache-Control"] == "no-store"


def test_login_rate_limit_email_bucket_is_independent(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a, ip_limit=100, email_limit=2) as client:
        assert _login(client, seeded.owner_email)["mfa_required"] is True
        assert _login(client, seeded.owner_email)["mfa_required"] is True
        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": seeded.owner_email, "password": PASSWORD},
        )
        other_user = client.post(
            "/api/v1/auth/login",
            json={"email": seeded.user_email, "password": PASSWORD},
        )

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert other_user.status_code == 200
    assert other_user.json()["access_token"]


def test_rate_limited_login_does_not_call_password_hasher(
    seeded: SeededHardening,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SpyHasher:
        def __init__(self) -> None:
            self.calls = 0

        def hash(self, password: str) -> str:
            return "hash"

        def verify(self, password_hash: str, password: str) -> bool:
            self.calls += 1
            return True

        def verify_dummy(self, password: str) -> None:
            self.calls += 1

    spy = SpyHasher()
    monkeypatch.setattr(auth_deps, "get_password_hasher", lambda: spy)
    with client_for(seeded.domain_a, ip_limit=3, email_limit=100) as client:
        for _ in range(3):
            assert _login(client, seeded.owner_email)["mfa_required"] is True
        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": seeded.owner_email, "password": PASSWORD},
        )

    assert blocked.status_code == 429
    assert spy.calls == 3


def test_mfa_challenge_is_tenant_bound(seeded: SeededHardening) -> None:
    with client_for(seeded.domain_a) as client:
        challenge = _login(client, seeded.owner_email)
    with client_for(seeded.domain_b) as other:
        response = other.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": challenge["mfa_token"], "code": _totp()},
        )
    assert response.status_code == 403
    assert response.json()["code"] == "tenant_mismatch"
