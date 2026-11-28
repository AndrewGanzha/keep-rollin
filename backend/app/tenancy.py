from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.config import Settings
from app.db import configure_session

INFRA_PATHS = frozenset({"/health", "/readyz", "/metrics", "/openapi.json"})
DOC_PATHS = ("/docs", "/redoc")

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
LookupKind = Literal["domain", "subdomain"]


@dataclass(frozen=True)
class TenantCandidate:
    value: str
    kind: LookupKind


class TenantResolver(Protocol):
    async def resolve(self, candidate: TenantCandidate) -> UUID | None:
        """Return the tenant ID for a typed host candidate or None."""


class DatabaseTenantResolver:
    """Resolve tenants through the narrow SECURITY DEFINER database lookup."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        database_role: str,
    ) -> None:
        self.session_factory = session_factory
        self.database_role = database_role

    async def resolve(self, candidate: TenantCandidate) -> UUID | None:
        async with self.session_factory() as session:
            configure_session(session, tenant_id=None, database_role=self.database_role)
            result = await session.execute(
                text("SELECT public.resolve_tenant(:host, :lookup_kind)"),
                {"host": candidate.value, "lookup_kind": candidate.kind},
            )
            value = result.scalar_one_or_none()
            return UUID(str(value)) if value is not None else None


def is_infra_path(path: str) -> bool:
    normalized = f"/{path.strip('/')}"
    if normalized in INFRA_PATHS:
        return True
    return any(normalized == prefix or normalized.startswith(f"{prefix}/") for prefix in DOC_PATHS)


def is_infra_request(request: Request) -> bool:
    path = request.url.path
    root_path = str(request.scope.get("root_path", ""))
    if root_path and (path == root_path or path.startswith(f"{root_path}/")):
        path = path[len(root_path) :]
    return is_infra_path(path)


def normalize_host(value: str) -> str:
    """Lowercase a host, strip a port and remove a trailing dot."""
    host = value.strip().lower()
    if host.startswith("["):
        closing = host.find("]")
        if closing != -1:
            return host[: closing + 1]
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host.rstrip(".")


def normalize_platform_domain(value: str) -> str:
    return normalize_host(value).lstrip(".")


def tenant_candidates(request: Request, settings: Settings) -> list[TenantCandidate]:
    """Return typed exact-host and platform-subdomain candidates in lookup order."""
    if settings.allow_tenant_header and settings.app_env in ("local", "test"):
        header_value = request.headers.get("X-Tenant")
        if header_value:
            host = normalize_host(header_value)
            if not host:
                return []
            kind: LookupKind = "domain" if "." in host else "subdomain"
            return [TenantCandidate(host, kind)]

    raw_host = request.headers.get("Host")
    if not raw_host:
        return []
    host = normalize_host(raw_host)
    if not host:
        return []

    candidates = [TenantCandidate(host, "domain")]
    platform = normalize_platform_domain(settings.platform_domain)
    if platform and host.endswith(f".{platform}"):
        subdomain = host[: -(len(platform) + 1)]
        if subdomain:
            candidates.append(TenantCandidate(subdomain, "subdomain"))
    return candidates
