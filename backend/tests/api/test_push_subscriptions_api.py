import asyncio
import os
from base64 import urlsafe_b64encode
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.db import configure_session, create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.infrastructure.postgres.models.push_subscription_record import PushSubscriptionRecord
from src.infrastructure.postgres.repositories.push_subscription_repository import (
    MAX_ACTIVE_SUBSCRIPTIONS,
    PushSubscriptionRepository,
)
from src.infrastructure.security.token_service import JwtTokenService
from src.infrastructure.security.vapid import generate_vapid_keypair
from tests.api.auth_helpers import JWT_SECRET

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")
SUBSCRIPTIONS = "/api/v1/me/push-subscriptions"
APP_ROLE = "keep_rollin_app"
WORKER_ROLE = "keep_rollin_worker"
ENDPOINT = "https://fcm.googleapis.com/fcm/send/push-device-token"


@dataclass(frozen=True)
class Account:
    id: UUID
    tenant_id: UUID
    domain: str

    @property
    def headers(self) -> dict[str, str]:
        token = JwtTokenService(secret=JWT_SECRET).create_access(
            user_id=self.id, tenant_id=self.tenant_id, role="user", token_version=1
        )
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def accounts() -> Iterator[tuple[Account, Account, Account]]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    tenants = []
    for _ in range(2):
        name = f"push-{uuid4().hex}"
        tenants.append(Tenant(id=uuid4(), name=name, slug=name, domain=f"{name}.test"))
    users = tuple(Account(uuid4(), tenant.id, tenant.domain) for tenant in (*tenants, tenants[0]))
    owner, foreign, peer = users

    async def seed() -> None:
        try:
            async with sessions.begin() as session:
                session.add_all(tenants)
                await session.flush()
                session.add_all(
                    User(
                        id=account.id,
                        tenant_id=account.tenant_id,
                        name="Subscriber",
                        email=f"{account.id.hex}@example.test",
                    )
                    for account in users
                )
        finally:
            await engine.dispose()

    async def cleanup() -> None:
        try:
            async with sessions.begin() as session:
                await session.execute(delete(Tenant).where(Tenant.id.in_([t.id for t in tenants])))
        finally:
            await engine.dispose()

    asyncio.run(seed())
    try:
        yield owner, peer, foreign
    finally:
        asyncio.run(cleanup())


@pytest.fixture
def keys() -> dict[str, str]:
    return {
        "p256dh": generate_vapid_keypair().public_key,
        "auth": urlsafe_b64encode(b"\x42" * 16).decode().rstrip("="),
    }


def client_for(account: Account, *, same_origin: bool = True) -> TestClient:
    origin = f"https://{account.domain}"
    headers = account.headers
    if same_origin:
        headers.update({"Origin": origin, "Sec-Fetch-Site": "same-origin"})
    return TestClient(
        create_app(Settings(database_url=DATABASE_URL, app_env="test", jwt_secret=JWT_SECRET)),
        base_url=origin,
        headers=headers,
    )


def test_upsert_listing_and_delete_are_private_and_idempotent(
    accounts: tuple[Account, Account, Account], keys: dict[str, str]
) -> None:
    owner, _, _ = accounts
    request: dict[str, object] = {"endpoint": ENDPOINT, "keys": keys, "expirationTime": None}
    with client_for(owner) as client:
        registered = client.post(
            SUBSCRIPTIONS, json=request, headers={"User-Agent": "Test Browser"}
        )
        assert registered.status_code == 200, registered.text
        assert registered.headers["Cache-Control"] == "no-store"
        saved = registered.json()
        assert set(saved) == {
            "id",
            "endpoint_hash",
            "expiration_time",
            "user_agent",
            "created_at",
            "updated_at",
        }
        assert saved["user_agent"] == "Test Browser"
        assert saved["expiration_time"] is None
        assert saved["endpoint_hash"] == sha256(ENDPOINT.encode("ascii")).hexdigest()
        assert ENDPOINT not in registered.text
        assert all(value not in registered.text for value in keys.values())

        request["expirationTime"] = 2_000_000_000_123
        repeated = client.post(SUBSCRIPTIONS, json=request)
        assert repeated.status_code == 200, repeated.text
        refreshed = repeated.json()
        assert refreshed["id"] == saved["id"]
        assert refreshed["created_at"] == saved["created_at"]
        assert datetime.fromisoformat(refreshed["expiration_time"]) == datetime.fromtimestamp(
            2_000_000_000.123, UTC
        )
        listed = client.get(SUBSCRIPTIONS)
        assert listed.json() == [refreshed]
        assert listed.headers["Cache-Control"] == "no-store"

        for _ in range(2):
            removed = client.delete(f"{SUBSCRIPTIONS}/{saved['id']}")
            assert removed.status_code == 204
            assert removed.headers["Cache-Control"] == "no-store"
        assert client.get(SUBSCRIPTIONS).json() == []


def test_scope_guards_and_shared_browser_endpoint(
    accounts: tuple[Account, Account, Account], keys: dict[str, str]
) -> None:
    owner, peer, foreign = accounts
    payload = {"endpoint": ENDPOINT, "keys": keys}
    with client_for(owner) as client:
        assert client.get(SUBSCRIPTIONS, headers={"Authorization": ""}).status_code == 401
        registered = client.post(SUBSCRIPTIONS, json=payload)
        assert registered.status_code == 200, registered.text
        path = f"{SUBSCRIPTIONS}/{registered.json()['id']}"

        with client_for(owner, same_origin=False) as no_csrf:
            assert no_csrf.post(SUBSCRIPTIONS, json=payload).status_code == 403
            assert no_csrf.delete(path).status_code == 403

        with client_for(peer) as peer_client:
            assert peer_client.get(SUBSCRIPTIONS).json() == []
            assert peer_client.delete(path).status_code == 204
            collision = peer_client.post(SUBSCRIPTIONS, json=payload)
            assert collision.status_code == 409
            assert collision.json()["code"] == "conflict"
            assert registered.json()["id"] not in collision.text

        with client_for(foreign) as foreign_client:
            mismatched = foreign_client.get(SUBSCRIPTIONS, headers=owner.headers)
            assert mismatched.status_code == 403
            assert mismatched.json()["code"] == "tenant_mismatch"
            assert foreign_client.get(SUBSCRIPTIONS).json() == []
            assert foreign_client.delete(path).status_code == 204
            assert foreign_client.post(SUBSCRIPTIONS, json=payload).status_code == 200

        assert client.get(SUBSCRIPTIONS).json() == [registered.json()]
        assert client.delete(path).status_code == 204
        with client_for(peer) as peer_client:
            assert peer_client.post(SUBSCRIPTIONS, json=payload).status_code == 200


def test_invalid_registration_does_not_echo_credentials(
    accounts: tuple[Account, Account, Account], keys: dict[str, str]
) -> None:
    owner, _, _ = accounts
    private_endpoint = "https://fcm.googleapis.com.example.test/fcm/send/push-private-token"
    bad_key = "bad-key-private-value"
    with client_for(owner) as client:
        for payload in (
            {"endpoint": private_endpoint, "keys": keys},
            {"endpoint": ENDPOINT, "keys": {**keys, "p256dh": bad_key}},
            {"endpoint": ENDPOINT, "keys": {**keys, "auth": bad_key}},
            {"endpoint": ENDPOINT, "keys": keys, "expirationTime": True},
            {"endpoint": ENDPOINT, "keys": keys, "expirationTime": 1},
        ):
            error = client.post(SUBSCRIPTIONS, json=payload)
            assert error.status_code == 422, error.text
            assert error.json()["code"] == "validation_error"
            for credential in (ENDPOINT, private_endpoint, bad_key, *keys.values()):
                assert credential not in error.text
        assert client.get(SUBSCRIPTIONS).json() == []


def test_concurrent_registration_preserves_active_quota(
    accounts: tuple[Account, Account, Account], keys: dict[str, str]
) -> None:
    owner, _, _ = accounts
    overlap = Barrier(2, timeout=10)

    def register(suffix: str) -> int:
        with client_for(owner) as client:
            overlap.wait()
            response = client.post(
                SUBSCRIPTIONS, json={"endpoint": f"{ENDPOINT}-{suffix}", "keys": keys}
            )
            return int(response.status_code)

    with client_for(owner) as client:
        for index in range(MAX_ACTIVE_SUBSCRIPTIONS - 1):
            response = client.post(
                SUBSCRIPTIONS, json={"endpoint": f"{ENDPOINT}-{index}", "keys": keys}
            )
            assert response.status_code == 200, response.text
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(register, "first")
            second = pool.submit(register, "second")
            assert sorted((first.result(timeout=15), second.result(timeout=15))) == [200, 409]
        assert len(client.get(SUBSCRIPTIONS).json()) == MAX_ACTIVE_SUBSCRIPTIONS
        refreshed = client.post(SUBSCRIPTIONS, json={"endpoint": f"{ENDPOINT}-0", "keys": keys})
        assert refreshed.status_code == 200, refreshed.text


@pytest.mark.asyncio
async def test_expiry_reactivation_and_stale_invalidation_are_scoped(
    accounts: tuple[Account, Account, Account], keys: dict[str, str]
) -> None:
    assert DATABASE_URL is not None
    owner, peer, foreign = accounts
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    record = PushSubscriptionRecord
    payload = {"endpoint": ENDPOINT, "keys": keys}
    try:
        with client_for(owner) as client:
            registered = client.post(SUBSCRIPTIONS, json=payload)
            assert registered.status_code == 200, registered.text
            identity = UUID(registered.json()["id"])
            async with sessions.begin() as session:
                configure_session(session, tenant_id=owner.tenant_id, database_role=WORKER_ROLE)
                repo = PushSubscriptionRepository(session)
                (first,) = await repo.list_active(owner.id)
                assert (first.id, first.endpoint, first.p256dh, first.auth) == (
                    identity,
                    ENDPOINT,
                    keys["p256dh"],
                    keys["auth"],
                )
                assert await repo.list_active(peer.id) == []
                assert not await repo.invalidate(peer.id, identity, version=first.version)

            updated = client.post(SUBSCRIPTIONS, json=payload)
            assert updated.status_code == 200
            assert updated.json()["id"] == str(identity)
            async with sessions.begin() as session:
                configure_session(session, tenant_id=foreign.tenant_id, database_role=APP_ROLE)
                assert await session.scalar(select(record.id).where(record.id == identity)) is None
                assert not await PushSubscriptionRepository(session).invalidate(
                    owner.id, identity, version=first.version
                )

            with pytest.raises(DBAPIError) as denied:
                async with sessions.begin() as session:
                    configure_session(session, tenant_id=owner.tenant_id, database_role=WORKER_ROLE)
                    await session.execute(
                        update(record).where(record.id == identity).values(auth=keys["auth"])
                    )
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"

            async with sessions.begin() as session:
                configure_session(session, tenant_id=owner.tenant_id, database_role=WORKER_ROLE)
                repo = PushSubscriptionRepository(session)
                (refreshed,) = await repo.list_active(owner.id)
                assert refreshed.version != first.version
                assert not await repo.invalidate(owner.id, identity, version=first.version)
                assert await repo.invalidate(owner.id, identity, version=refreshed.version)

            assert client.get(SUBSCRIPTIONS).json() == []
            reactivated = client.post(SUBSCRIPTIONS, json=payload)
            assert reactivated.status_code == 200
            assert reactivated.json()["id"] == str(identity)
            async with sessions.begin() as session:
                configure_session(session, tenant_id=owner.tenant_id, database_role=APP_ROLE)
                await session.execute(
                    update(record)
                    .where(record.id == identity)
                    .values(expiration_time=datetime.now(UTC) - timedelta(seconds=1))
                )
                assert await PushSubscriptionRepository(session).list_active(owner.id) == []

            assert client.get(SUBSCRIPTIONS).json() == []
            assert client.post(SUBSCRIPTIONS, json=payload).json()["id"] == str(identity)
    finally:
        await engine.dispose()
