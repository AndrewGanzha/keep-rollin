from __future__ import annotations

import asyncio
import io
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text

from app import cli
from app.db import create_engine, create_session_factory
from app.models import Tenant, User
from src.application.services.provisioning import (
    ProvisioningConflictError,
    ProvisionTenantService,
)
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord
from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.security.vapid import public_from_private
from tests.api.test_admin_users_api import client_for

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"


def _dsn() -> str:
    assert DATABASE_URL is not None
    return DATABASE_URL


def _cleanup(slug: str) -> None:
    async def run() -> None:
        engine = create_engine(_dsn())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
                if tenant is None:
                    return
                await session.execute(
                    delete(AuditLogRecord).where(AuditLogRecord.tenant_id == tenant.id)
                )
                await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def _read_tenant(slug: str) -> tuple[UUID, UUID, TenantSettingsRecord]:
    async def run() -> tuple[UUID, UUID, TenantSettingsRecord]:
        engine = create_engine(_dsn())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
                assert tenant is not None
                owner = await session.scalar(
                    select(User).where(User.tenant_id == tenant.id, User.role == "owner")
                )
                assert owner is not None
                settings = await session.scalar(
                    select(TenantSettingsRecord).where(TenantSettingsRecord.tenant_id == tenant.id)
                )
                assert settings is not None
                return tenant.id, owner.id, settings
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_provision_cli_is_idempotent_and_never_reprints_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slug = f"cli-{uuid4().hex[:10]}"
    domain = f"{slug}.test"
    email = f"owner-{slug}@example.com"
    monkeypatch.setenv("PROVISION_DATABASE_URL", _dsn())
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    try:
        first = cli.main(
            [
                "provision-tenant",
                "--name",
                "CLI Tenant",
                "--slug",
                slug,
                "--domain",
                domain,
                "--owner-email",
                email,
            ]
        )
        assert first == 0
        first_output = capsys.readouterr()
        assert "tenant provisioned" in first_output.out
        assert "owner_password (shown once)" in first_output.out

        second = cli.main(
            [
                "provision-tenant",
                "--name",
                "CLI Tenant",
                "--slug",
                slug,
                "--domain",
                domain,
                "--owner-email",
                email,
            ]
        )
        assert second == 0
        second_output = capsys.readouterr()
        assert "already provisioned" in second_output.out
        assert "owner_password" not in second_output.out

        tenant_id, owner_id, settings = _read_tenant(slug)
        assert tenant_id
        assert owner_id
        assert settings.vapid_private_key_enc is not None
        box = SecretBox.from_settings(JWT_SECRET)
        private_key = box.decrypt(
            settings.vapid_private_key_enc,
            context=f"vapid:{tenant_id}",
        )
        assert public_from_private(private_key) == settings.vapid_public_key
    finally:
        _cleanup(slug)


def test_provision_cli_conflict_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slug = f"cli-{uuid4().hex[:10]}"
    domain = f"{slug}.test"
    email = f"owner-{slug}@example.com"
    monkeypatch.setenv("PROVISION_DATABASE_URL", _dsn())
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    try:
        assert (
            cli.main(
                [
                    "provision-tenant",
                    "--name",
                    "CLI Tenant",
                    "--slug",
                    slug,
                    "--domain",
                    domain,
                    "--owner-email",
                    email,
                ]
            )
            == 0
        )
        capsys.readouterr()

        conflict = cli.main(
            [
                "provision-tenant",
                "--name",
                "CLI Tenant",
                "--slug",
                slug,
                "--domain",
                f"other-{domain}",
                "--owner-email",
                email,
            ]
        )
        assert conflict == 2
        assert "conflict" in capsys.readouterr().err.casefold()

        second_slug = f"cli-{uuid4().hex[:10]}"
        second_domain = f"{second_slug}.test"
        second_email = f"owner-{second_slug}@example.com"
        assert (
            cli.main(
                [
                    "provision-tenant",
                    "--name",
                    "CLI Tenant Two",
                    "--slug",
                    second_slug,
                    "--domain",
                    second_domain,
                    "--owner-email",
                    second_email,
                ]
            )
            == 0
        )
        capsys.readouterr()
        split = cli.main(
            [
                "provision-tenant",
                "--name",
                "Split Tenant",
                "--slug",
                slug,
                "--domain",
                second_domain,
                "--owner-email",
                f"split-{uuid4().hex[:8]}@example.com",
            ]
        )
        assert split == 2
        assert "different tenants" in capsys.readouterr().err
        _cleanup(second_slug)

        async def count() -> int:
            engine = create_engine(_dsn())
            factory = create_session_factory(engine)
            try:
                async with factory() as session:
                    result = await session.scalar(
                        select(Tenant).where(Tenant.domain == f"other-{domain}")
                    )
                    return 0 if result is None else 1
            finally:
                await engine.dispose()

        assert asyncio.run(count()) == 0
    finally:
        _cleanup(slug)


def test_purge_audit_cli_dry_run_and_execute(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slug = f"cli-{uuid4().hex[:10]}"
    domain = f"{slug}.test"
    email = f"owner-{slug}@example.com"
    monkeypatch.setenv("PROVISION_DATABASE_URL", _dsn())
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    try:
        assert (
            cli.main(
                [
                    "provision-tenant",
                    "--name",
                    "CLI Tenant",
                    "--slug",
                    slug,
                    "--domain",
                    domain,
                    "--owner-email",
                    email,
                ]
            )
            == 0
        )
        capsys.readouterr()
        tenant_id, _owner_id, _settings = _read_tenant(slug)

        async def age_audit_rows() -> None:
            engine = create_engine(_dsn())
            factory = create_session_factory(engine)
            try:
                async with factory() as session:
                    rows = (
                        await session.execute(
                            select(AuditLogRecord).where(AuditLogRecord.tenant_id == tenant_id)
                        )
                    ).scalars()
                    for row in rows:
                        row.created_at = datetime.now(UTC) - timedelta(days=40)
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(age_audit_rows())

        dry = cli.main(["purge-audit-log", "--older-than-days", "31"])
        assert dry == 0
        assert "dry-run" in capsys.readouterr().out
        assert len(_audit_rows(tenant_id)) == 1

        executed = cli.main(["purge-audit-log", "--older-than-days", "31", "--execute"])
        assert executed == 0
        assert "purged" in capsys.readouterr().out
        assert _audit_rows(tenant_id) == []
    finally:
        _cleanup(slug)


def test_provisioning_rolls_back_on_late_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = f"cli-{uuid4().hex[:10]}"
    domain = f"{slug}.test"
    fixed_id = uuid4()
    occupied_slug = f"occupied-{uuid4().hex[:8]}"

    async def run() -> None:
        engine = create_engine(_dsn())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add(
                    Tenant(
                        id=fixed_id,
                        name="Occupied",
                        slug=occupied_slug,
                        domain=f"{occupied_slug}.test",
                    )
                )
                await session.commit()
            import src.application.services.provisioning as provisioning_module

            monkeypatch.setattr(provisioning_module, "uuid4", lambda: fixed_id)
            async with factory() as session:
                service = ProvisionTenantService(
                    session,
                    secret_box=SecretBox.from_settings(JWT_SECRET),
                )
                with pytest.raises(ProvisioningConflictError):
                    await service.provision(
                        name="Rollback Tenant",
                        slug=slug,
                        domain=domain,
                        owner_email=f"owner-{slug}@example.com",
                    )
            async with factory() as session:
                tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
                assert tenant is None
                settings = await session.scalar(
                    select(TenantSettingsRecord).where(TenantSettingsRecord.tenant_id == fixed_id)
                )
                assert settings is None
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    finally:
        _cleanup(occupied_slug)


def test_purge_rejects_zero_retention(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVISION_DATABASE_URL", _dsn())
    with pytest.raises(SystemExit, match="at least 30"):
        cli.main(["purge-audit-log", "--older-than-days", "0", "--execute"])


def test_concurrent_provisioning_has_one_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    slug = f"cli-{uuid4().hex[:10]}"
    domain = f"{slug}.test"
    email = f"owner-{slug}@example.com"
    monkeypatch.setenv("PROVISION_DATABASE_URL", _dsn())

    async def attempt() -> str:
        engine = create_engine(_dsn())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                service = ProvisionTenantService(
                    session,
                    secret_box=SecretBox.from_settings(JWT_SECRET),
                )
                try:
                    result = await service.provision(
                        name="Concurrent Tenant",
                        slug=slug,
                        domain=domain,
                        owner_email=email,
                    )
                    return "created" if result.created else "idempotent"
                except ProvisioningConflictError:
                    return "conflict"
        finally:
            await engine.dispose()

    async def run() -> list[str]:
        return list(await asyncio.gather(attempt(), attempt()))

    try:
        results = asyncio.run(run())
        assert results.count("created") == 1
        assert all(result in ("created", "idempotent", "conflict") for result in results)
        tenant_id, _owner_id, _settings = _read_tenant(slug)
        assert len(_audit_rows(tenant_id)) == 1
    finally:
        _cleanup(slug)


def test_provisioning_rolls_back_after_late_audit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = f"cli-{uuid4().hex[:10]}"
    domain = f"{slug}.test"

    async def run() -> None:
        engine = create_engine(_dsn())
        factory = create_session_factory(engine)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "CREATE OR REPLACE FUNCTION test_fail_audit() RETURNS trigger "
                        "AS $$ BEGIN RAISE EXCEPTION 'audit fail' USING ERRCODE = '23505'; "
                        "END; $$ LANGUAGE plpgsql"
                    )
                )
                await connection.execute(
                    text(
                        "CREATE TRIGGER test_fail_audit BEFORE INSERT ON audit_log "
                        "FOR EACH ROW EXECUTE FUNCTION test_fail_audit()"
                    )
                )
            async with factory() as session:
                service = ProvisionTenantService(
                    session,
                    secret_box=SecretBox.from_settings(JWT_SECRET),
                )
                with pytest.raises(ProvisioningConflictError):
                    await service.provision(
                        name="Late Failure Tenant",
                        slug=slug,
                        domain=domain,
                        owner_email=f"owner-{slug}@example.com",
                    )
            async with factory() as session:
                assert await session.scalar(select(Tenant).where(Tenant.slug == slug)) is None
                assert (
                    await session.scalar(
                        select(TenantSettingsRecord).where(
                            TenantSettingsRecord.tenant_id.in_(
                                select(Tenant.id).where(Tenant.slug == slug)
                            )
                        )
                    )
                    is None
                )
        finally:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DROP TRIGGER IF EXISTS test_fail_audit ON audit_log")
                )
                await connection.execute(text("DROP FUNCTION IF EXISTS test_fail_audit()"))
            await engine.dispose()

    asyncio.run(run())


def _audit_rows(tenant_id: UUID) -> list[AuditLogRecord]:
    async def run() -> list[AuditLogRecord]:
        engine = create_engine(_dsn())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                result = await session.execute(
                    select(AuditLogRecord).where(AuditLogRecord.tenant_id == tenant_id)
                )
                return list(result.scalars().all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_provisioned_owner_can_log_in_with_the_exact_stdin_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slug = f"cli-{uuid4().hex[:10]}"
    domain = f"{slug}.test"
    email = f"{'a' * 130}@example.com"
    password = "  Private passphrase 54!  "
    monkeypatch.setenv("PROVISION_DATABASE_URL", _dsn())
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{password}\n"))
    try:
        assert (
            cli.main(
                [
                    "provision-tenant",
                    "--name",
                    "CLI Tenant",
                    "--slug",
                    slug,
                    "--domain",
                    f"{domain.upper()}.",
                    "--owner-email",
                    email,
                    "--owner-password-stdin",
                ]
            )
            == 0
        )
        assert password not in capsys.readouterr().out
        with client_for(domain) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": password},
            )
        assert response.status_code == 200, response.text
        assert response.json()["mfa_setup_required"] is True
    finally:
        _cleanup(slug)


@pytest.mark.parametrize(
    ("host", "email", "password"),
    [
        ("two words.test", "owner@example.com", "Private passphrase 54!"),
        ("example.test?redirect", "owner@example.com", "Private passphrase 54!"),
        ("valid.test", f"{'a' * 255}@example.com", "Private passphrase 54!"),
        ("valid.test", "owner@example.com", "a" * 129),
        ("valid.test", "owner@example.com", "Private passphrase 54!\x00"),
    ],
)
def test_invalid_provisioning_inputs_leave_no_tenant(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    host: str,
    email: str,
    password: str,
) -> None:
    slug = f"cli-{uuid4().hex[:10]}"
    monkeypatch.setenv("PROVISION_DATABASE_URL", _dsn())
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{password}\n"))

    async def tenant_exists() -> bool:
        engine = create_engine(_dsn())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                return (
                    await session.scalar(select(Tenant.id).where(Tenant.slug == slug)) is not None
                )
        finally:
            await engine.dispose()

    try:
        result = cli.main(
            [
                "provision-tenant",
                "--name",
                "CLI Tenant",
                "--slug",
                slug,
                "--domain",
                host,
                "--owner-email",
                email,
                "--owner-password-stdin",
            ]
        )
        assert result == 1
        output = capsys.readouterr()
        assert "provisioning failed" in output.err
        assert password not in output.err
        assert not asyncio.run(tenant_exists())
    finally:
        _cleanup(slug)
