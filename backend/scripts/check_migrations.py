from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

BACKEND_DIR = Path(__file__).resolve().parents[1]
MAINTENANCE_DB = "postgres"


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL is required for the migration check")
    return value


def with_database(dsn: str, database: str) -> str:
    parsed = urlsplit(dsn)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment))


async def create_database(admin_dsn: str, name: str) -> None:
    connection = await asyncpg.connect(with_database(admin_dsn, MAINTENANCE_DB))
    try:
        await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


async def drop_database(admin_dsn: str, name: str) -> None:
    connection = await asyncpg.connect(with_database(admin_dsn, MAINTENANCE_DB))
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await connection.close()


def run_alembic(dsn: str, *args: str) -> None:
    environment = {**os.environ, "DATABASE_URL": dsn}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
    )


async def main() -> int:
    admin_dsn = database_url()
    name = f"keep_rollin_migration_{uuid.uuid4().hex[:12]}"
    temp_dsn = with_database(admin_dsn, name)
    await create_database(admin_dsn, name)
    try:
        run_alembic(temp_dsn, "upgrade", "head")
        run_alembic(temp_dsn, "downgrade", "base")
        run_alembic(temp_dsn, "upgrade", "head")
    finally:
        await drop_database(admin_dsn, name)
    print("migration check passed: upgrade -> downgrade -> upgrade")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as error:
        print(f"migration check failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
