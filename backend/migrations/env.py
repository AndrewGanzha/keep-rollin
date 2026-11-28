from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import Settings
from app.db import DsnSettings, parse_dsn, to_async_dsn
from app.models import Base
from src.infrastructure.postgres import models as catalog_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> tuple[str, DsnSettings]:
    value = os.getenv("DATABASE_URL") or Settings().database_url
    if not value:
        raise RuntimeError("DATABASE_URL is required for Alembic migrations")
    parsed = parse_dsn(value)
    return to_async_dsn(parsed.dsn), parsed


def run_migrations_offline() -> None:
    url, _dsn = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration: dict[str, Any] = config.get_section(config.config_ini_section, {})
    url, parsed = get_url()
    configuration["sqlalchemy.url"] = url
    connect_args: dict[str, Any] = {}
    if parsed.ssl is not None:
        connect_args["ssl"] = parsed.ssl
    if parsed.server_settings:
        connect_args["server_settings"] = parsed.server_settings
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
