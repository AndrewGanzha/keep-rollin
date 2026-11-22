import asyncio
import contextlib
import os
import re
import ssl as ssl_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import asyncpg
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
SslArgument = bool | str | ssl_module.SSLContext | None
SSL_QUERY_KEYS = frozenset(
    {
        "sslmode",
        "sslcert",
        "sslkey",
        "sslrootcert",
        "sslcrl",
        "sslpassword",
        "ssl_min_protocol_version",
        "ssl_max_protocol_version",
        "sslnegotiation",
    }
)
SSL_MODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})


@dataclass(frozen=True)
class DsnSettings:
    dsn: str
    ssl: SslArgument = None
    server_settings: dict[str, str] = field(default_factory=dict)


def _tls_version(value: str) -> ssl_module.TLSVersion:
    versions = {
        "TLSv1": ssl_module.TLSVersion.TLSv1,
        "TLSv1.1": ssl_module.TLSVersion.TLSv1_1,
        "TLSv1.2": ssl_module.TLSVersion.TLSv1_2,
        "TLSv1.3": ssl_module.TLSVersion.TLSv1_3,
    }
    try:
        return versions[value]
    except KeyError as error:
        raise ValueError(f"unsupported TLS version: {value}") from error


def _default_root_cert() -> str | None:
    candidates = [Path.home() / ".postgresql" / "root.crt"]
    appdata = os.getenv("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "postgresql" / "root.crt")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _ssl_context(mode: str, params: dict[str, str]) -> ssl_module.SSLContext:
    root_cert = params.get("sslrootcert") or _default_root_cert()
    if mode in ("verify-ca", "verify-full") and not root_cert:
        raise ValueError(f"sslmode={mode} requires sslrootcert")
    context = ssl_module.create_default_context(cafile=root_cert)
    if mode == "require":
        context.check_hostname = False
        if not root_cert:
            context.verify_mode = ssl_module.CERT_NONE
    elif mode == "verify-ca":
        context.check_hostname = False
        context.verify_mode = ssl_module.CERT_REQUIRED

    if "ssl_min_protocol_version" in params:
        context.minimum_version = _tls_version(params["ssl_min_protocol_version"])
    if "ssl_max_protocol_version" in params:
        context.maximum_version = _tls_version(params["ssl_max_protocol_version"])

    cert = params.get("sslcert")
    if cert:
        context.load_cert_chain(
            cert,
            params.get("sslkey"),
            params.get("sslpassword"),
        )
    return context


def parse_dsn(dsn: str) -> DsnSettings:
    """Translate libpq-style query parameters for asyncpg."""
    try:
        parsed = urlsplit(dsn)
        query = parse_qsl(parsed.query, keep_blank_values=True)
    except ValueError:
        raise ValueError("invalid database URL") from None

    ssl_arg: SslArgument = None
    ssl_params: dict[str, str] = {}
    server_settings: dict[str, str] = {}
    kept: list[tuple[str, str]] = []
    for key, value in query:
        lowered = key.lower()
        if lowered in SSL_QUERY_KEYS:
            ssl_params[lowered] = value
            continue
        if lowered in ("application_name", "options"):
            server_settings[lowered] = value
            continue
        kept.append((key, value))

    for key, environment in (
        ("sslrootcert", "PGSSLROOTCERT"),
        ("sslcert", "PGSSLCERT"),
        ("sslkey", "PGSSLKEY"),
        ("sslpassword", "PGSSLPASSWORD"),
        ("ssl_min_protocol_version", "PGSSLMINPROTOCOLVERSION"),
        ("ssl_max_protocol_version", "PGSSLMAXPROTOCOLVERSION"),
    ):
        if key not in ssl_params and os.getenv(environment):
            ssl_params[key] = os.environ[environment]

    if os.getenv("PGSSLCRL"):
        raise ValueError("PGSSLCRL is not supported")
    if "sslcrl" in ssl_params or "sslnegotiation" in ssl_params:
        raise ValueError("sslcrl and sslnegotiation are not supported")

    mode = ssl_params.get("sslmode") or os.getenv("PGSSLMODE")
    if mode is not None:
        mode = mode.lower()
        if mode not in SSL_MODES:
            raise ValueError("unsupported sslmode")
        if mode == "disable":
            ssl_arg = False
        elif mode in ("allow", "prefer"):
            if set(ssl_params) - {"sslmode"}:
                raise ValueError(f"TLS parameters are not supported with sslmode {mode}")
            ssl_arg = mode
        else:
            ssl_arg = _ssl_context(mode, ssl_params)
    elif ssl_params:
        ssl_arg = _ssl_context("require", ssl_params)

    if not parsed.netloc and parsed.path.startswith("/"):
        normalized = f"{parsed.scheme}://{parsed.path}"
        if kept:
            normalized = f"{normalized}?{urlencode(kept)}"
        if parsed.fragment:
            normalized = f"{normalized}#{parsed.fragment}"
    else:
        normalized = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(kept), parsed.fragment)
        )
    return DsnSettings(dsn=normalized, ssl=ssl_arg, server_settings=server_settings)


def split_dsn(dsn: str) -> tuple[str, SslArgument]:
    parsed = parse_dsn(dsn)
    return parsed.dsn, parsed.ssl


def to_async_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql://"):
        return f"postgresql+asyncpg://{dsn[len('postgresql://') :]}"
    if dsn.startswith("postgres://"):
        return f"postgresql+asyncpg://{dsn[len('postgres://') :]}"
    return dsn


def create_engine(dsn: str) -> AsyncEngine:
    parsed = parse_dsn(dsn)
    connect_args: dict[str, Any] = {}
    if parsed.ssl is not None:
        connect_args["ssl"] = parsed.ssl
    if parsed.server_settings:
        connect_args["server_settings"] = parsed.server_settings
    return create_async_engine(
        to_async_dsn(parsed.dsn),
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def configure_session(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    database_role: str,
) -> None:
    session.info["tenant_id"] = str(tenant_id) if tenant_id else None
    session.info["db_role"] = database_role


def _reject_role(connection: Connection, message: str) -> None:
    connection.invalidate()
    raise ValueError(message)


@event.listens_for(Session, "after_begin")
def apply_session_context(
    session: Session,
    transaction: SessionTransaction,
    connection: Connection,
) -> None:
    role = session.info.get("db_role")
    if role:
        role_text = str(role)
        if not ROLE_RE.fullmatch(role_text):
            raise ValueError("invalid database role")
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role_text}"')
        unsafe = connection.execute(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
        if unsafe:
            _reject_role(connection, "database role must not be SUPERUSER or BYPASSRLS")
        owns_tables = connection.execute(
            text(
                "SELECT count(*) FROM pg_class "
                "WHERE relname IN ('tenant', 'user') "
                "AND relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)"
            )
        ).scalar_one()
        if owns_tables:
            _reject_role(connection, "database role must not own tenant or user tables")
        rls_active = connection.execute(
            text("SELECT row_security_active('tenant') AND row_security_active('user')")
        ).scalar_one()
        if not rls_active:
            _reject_role(connection, "RLS is not active for database role")

    tenant_id: Any = session.info.get("tenant_id")
    if tenant_id:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
    else:
        connection.execute(text("SELECT set_config('app.tenant_id', '', true)"))


async def engine_ready(engine: AsyncEngine | None, timeout_seconds: float) -> bool:
    if engine is None:
        return False
    try:
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def database_ready(dsn: str | None, timeout_seconds: float) -> bool:
    """Return True when a real SELECT 1 succeeds within one overall deadline."""
    if not dsn:
        return False

    try:
        parsed = parse_dsn(dsn)
    except Exception:
        return False
    connect_kwargs: dict[str, Any] = {"timeout": timeout_seconds}
    if parsed.ssl is not None:
        connect_kwargs["ssl"] = parsed.ssl
    if parsed.server_settings:
        connect_kwargs["server_settings"] = parsed.server_settings

    connection: asyncpg.Connection | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            connection = await asyncpg.connect(parsed.dsn, **connect_kwargs)
            await connection.execute("SELECT 1")
    except Exception:
        # Readiness fails closed for every driver or transport error. CancelledError
        # is a BaseException and still propagates to the caller.
        return False
    finally:
        if connection is not None:
            with contextlib.suppress(Exception):
                connection.terminate()

    return True
