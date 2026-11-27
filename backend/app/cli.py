from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import Settings
from app.db import create_engine, create_session_factory
from src.application.services.provisioning import (
    ProvisioningConflictError,
    ProvisioningError,
    ProvisionTenantService,
)
from src.application.services.uploads import StorageUnavailableError
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.repositories.audit_repository import AuditRepository
from src.infrastructure.postgres.repositories.file_repository import FileRepository
from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.storage.s3 import build_upload_storage


def _settings() -> Settings:
    return Settings()


def _secret_box(settings: Settings) -> SecretBox:
    return SecretBox.from_settings(
        settings.security_key or settings.jwt_secret,
        key_id=settings.security_key_id,
        previous_keys=settings.security_previous_keys,
    )


def _privileged_dsn(args: argparse.Namespace, settings: Settings) -> str:
    value = args.database_url or os.getenv("PROVISION_DATABASE_URL")
    if not value:
        value = settings.provision_database_url
    if not value:
        raise SystemExit(
            "PROVISION_DATABASE_URL or --database-url is required for privileged CLI operations"
        )
    return value


async def _provision_tenant(args: argparse.Namespace) -> int:
    settings = _settings()
    dsn = _privileged_dsn(args, settings)
    supplied_password = None
    if args.owner_password_stdin:
        supplied_password = sys.stdin.readline().removesuffix("\n").removesuffix("\r")
        if not supplied_password:
            raise SystemExit("owner password on stdin is empty")
    engine = create_engine(dsn)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            result = await ProvisionTenantService(
                session,
                secret_box=_secret_box(settings),
            ).provision(
                name=args.name,
                slug=args.slug,
                domain=args.domain,
                owner_email=args.owner_email,
                owner_name=args.owner_name,
                password=supplied_password,
            )
    finally:
        await engine.dispose()

    if result.created:
        print(f"tenant provisioned: {result.tenant_id}")
        print(f"owner: {result.owner_id}")
        print(f"vapid_public_key: {result.vapid_public_key}")
        if supplied_password is None and result.password is not None:
            print("owner_password (shown once):")
            print(result.password)
    else:
        print(f"tenant already provisioned: {result.tenant_id}")
    return 0


async def _purge_audit_log(args: argparse.Namespace) -> int:
    settings = _settings()
    dsn = _privileged_dsn(args, settings)
    days = settings.audit_retention_days if args.older_than_days is None else args.older_than_days
    if days < 30:
        raise SystemExit("--older-than-days must be at least 30")
    cutoff = datetime.now(UTC) - timedelta(days=days)
    engine = create_engine(dsn)
    factory = create_session_factory(engine)
    total = 0
    try:
        async with factory() as session:
            existing = await session.scalar(
                select(func.count())
                .select_from(AuditLogRecord)
                .where(AuditLogRecord.created_at < cutoff)
            )
            existing = int(existing or 0)
            if not args.execute:
                print(f"dry-run: {existing} audit rows older than {cutoff.isoformat()}")
                return 0
            repository = AuditRepository(session)
            while True:
                deleted = await repository.purge_before(
                    cutoff=cutoff,
                    batch_size=args.batch_size,
                )
                await session.commit()
                total += deleted
                if deleted < args.batch_size:
                    break
    finally:
        await engine.dispose()
    print(f"purged {total} audit rows older than {cutoff.isoformat()}")
    return 0


async def _purge_orphan_uploads(args: argparse.Namespace) -> int:
    settings = _settings()
    dsn = _privileged_dsn(args, settings)
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    engine = create_engine(dsn)
    total = 0
    try:
        async with create_session_factory(engine)() as session:
            repository = FileRepository(session)
            if not args.execute:
                print(f"dry-run: {await repository.count_orphans(cutoff)} orphan uploads")
                return 0
            storage = await asyncio.to_thread(build_upload_storage, settings)
            while candidates := await repository.lock_orphans(cutoff, limit=args.batch_size):
                for record in candidates:
                    record.is_ready = False
                    record.is_purging = True
                # Durable non-ready state prevents a new link after object deletion starts.
                await session.commit()
                for record in candidates:
                    await storage.delete(record.object_key, public=record.purpose == "lot_photo")
                    if await repository.delete_claimed_orphan(record.id):
                        total += 1
                    await session.commit()
    finally:
        await engine.dispose()
    print(f"purged {total} orphan uploads")
    return 0


def _add_common_database_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database-url", default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    provision = subparsers.add_parser("provision-tenant")
    _add_common_database_arg(provision)
    provision.add_argument("--name", required=True)
    provision.add_argument("--slug", required=True)
    provision.add_argument("--domain", required=True)
    provision.add_argument("--owner-email", required=True)
    provision.add_argument("--owner-name", default=None)
    provision.add_argument("--owner-password-stdin", action="store_true")
    provision.set_defaults(handler=_provision_tenant)

    purge = subparsers.add_parser("purge-audit-log")
    _add_common_database_arg(purge)
    purge.add_argument("--older-than-days", type=int, default=None)
    purge.add_argument("--batch-size", type=int, default=1000)
    purge.add_argument("--execute", action="store_true")
    purge.set_defaults(handler=_purge_audit_log)
    uploads = subparsers.add_parser("purge-orphan-uploads")
    _add_common_database_arg(uploads)
    uploads.add_argument("--batch-size", type=int, default=100)
    uploads.add_argument("--execute", action="store_true")
    uploads.set_defaults(handler=_purge_orphan_uploads)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "batch_size", 1) < 1:
        parser.error("--batch-size must be positive")
    try:
        return int(asyncio.run(args.handler(args)))
    except ProvisioningConflictError as exc:
        print(f"provisioning conflict: {exc}", file=sys.stderr)
        return 2
    except ProvisioningError as exc:
        print(f"provisioning failed: {exc}", file=sys.stderr)
        return 1
    except StorageUnavailableError:
        print("object storage unavailable", file=sys.stderr)
        return 1
    except Exception as exc:
        # Unexpected database/driver errors may embed parameters or DSNs.
        print(f"cli failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
