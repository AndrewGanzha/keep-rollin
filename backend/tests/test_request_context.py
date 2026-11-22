import logging
from collections.abc import AsyncIterator
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response as FastAPIResponse
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.logging import JsonFormatter
from app.main import create_app
from app.tenancy import LookupKind, TenantCandidate, TenantResolver

TENANT_A = UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = UUID("22222222-2222-2222-2222-222222222222")


class FakeResolver(TenantResolver):
    def __init__(self, mapping: dict[tuple[LookupKind, str], UUID]) -> None:
        self.mapping = mapping

    async def resolve(self, candidate: TenantCandidate) -> UUID | None:
        return self.mapping.get((candidate.kind, candidate.value))


class Payload(BaseModel):
    path: int


def tenant_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/_test/tenant")
    async def tenant(request: Request) -> dict[str, str]:
        return {"tenant_id": str(request.state.tenant_id)}

    @router.get("/api/v1/_test/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("details that must not leak")

    @router.get("/api/v1/_test/validate")
    async def validate(value: int = Query()) -> dict[str, int]:
        return {"value": value}

    @router.post("/api/v1/_test/body")
    async def body(payload: Payload) -> dict[str, int]:
        return {"path": payload.path}

    @router.get("/api/v1/_test/http-500")
    async def http_500() -> None:
        raise HTTPException(status_code=500, detail="secret status detail")

    @router.get("/api/v1/_test/http-401")
    async def http_401() -> None:
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @router.get("/api/v1/_test/http-405")
    async def http_405() -> None:
        raise HTTPException(status_code=405, headers={"Allow": "GET"})

    @router.get("/api/v1/_test/http-503")
    async def http_503() -> None:
        raise HTTPException(status_code=503, detail="secret dependency detail")

    @router.get("/api/v1/_test/http-429")
    async def http_429() -> None:
        raise HTTPException(
            status_code=429,
            detail="slow down",
            headers={"Retry-After": "10"},
        )

    @router.get("/api/v1/_test/http-499")
    async def http_499() -> None:
        raise HTTPException(status_code=499)

    @router.get("/api/v1/_test/http-413")
    async def http_413() -> None:
        raise HTTPException(status_code=413)

    @router.get("/api/v1/_test/http-415")
    async def http_415() -> None:
        raise HTTPException(status_code=415)

    @router.get("/api/v1/_test/duplicate-headers")
    async def duplicate_headers() -> FastAPIResponse:
        response = FastAPIResponse("ok")
        response.raw_headers.extend(
            [
                (b"set-cookie", b"first=1"),
                (b"set-cookie", b"second=2"),
            ]
        )
        return response

    return router


def make_client(
    *,
    base_url: str = "http://tenant-a.test",
    allow_tenant_header: bool = True,
    app_env: Literal["local", "test", "production"] = "test",
    resolver: TenantResolver | None = None,
    raise_server_exceptions: bool = False,
) -> TestClient:
    settings = Settings(
        database_url=None,
        app_env=app_env,
        platform_domain="platform.test",
        allow_tenant_header=allow_tenant_header,
    )
    app = create_app(
        settings,
        resolver
        or FakeResolver(
            {
                ("domain", "tenant-a.test"): TENANT_A,
                ("domain", "tenant-b.test"): TENANT_B,
                ("subdomain", "tenant-a"): TENANT_A,
                ("domain", "exact.platform.test"): TENANT_A,
            }
        ),
    )
    app.include_router(tenant_router())
    return TestClient(
        app,
        base_url=base_url,
        raise_server_exceptions=raise_server_exceptions,
    )


def test_health_preserves_request_id() -> None:
    with make_client(base_url="http://unknown.test") as client:
        response = client.get("/health", headers={"X-Request-Id": "req-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-123"


def test_invalid_request_id_is_replaced() -> None:
    with make_client() as client:
        response = client.get("/health", headers={"X-Request-Id": "bad id with spaces"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] != "bad id with spaces"
    assert len(response.headers["X-Request-Id"]) == 32


def test_health_with_trailing_slash_is_not_tenant_blocked() -> None:
    with make_client(base_url="http://unknown.test") as client:
        response = client.get("/health/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/health")


def test_root_path_health_is_not_tenant_blocked() -> None:
    settings = Settings(database_url=None, allow_tenant_header=False)
    app = create_app(settings)
    app.include_router(tenant_router())

    with TestClient(app, base_url="http://unknown.test", root_path="/service") as client:
        response = client.get("/service/health")

    assert response.status_code == 200


def test_root_path_prefix_boundary_is_not_stripped() -> None:
    settings = Settings(database_url=None, allow_tenant_header=False)
    app = create_app(settings)
    app.include_router(tenant_router())

    with TestClient(app, base_url="http://unknown.test", root_path="/he") as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_root_path_with_trailing_slash_keeps_probe_exempt() -> None:
    settings = Settings(database_url=None, allow_tenant_header=False)
    app = create_app(settings)
    app.include_router(tenant_router())

    with TestClient(app, base_url="http://unknown.test", root_path="/service/") as client:
        response = client.get("/service//readyz/", follow_redirects=False)

    assert response.status_code == 307


def test_root_path_named_health_keeps_health_exempt() -> None:
    settings = Settings(database_url=None, allow_tenant_header=False)
    app = create_app(settings)
    app.include_router(tenant_router())

    with TestClient(app, base_url="http://unknown.test", root_path="/health/") as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_root_path_named_readyz_keeps_readiness_exempt() -> None:
    settings = Settings(database_url=None, allow_tenant_header=False)
    app = create_app(settings)
    app.include_router(tenant_router())

    with TestClient(app, base_url="http://unknown.test", root_path="/readyz/") as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


def test_unknown_host_returns_problem() -> None:
    with make_client(base_url="http://unknown.test") as client:
        response = client.get("/api/v1/_test/tenant", headers={"X-Request-Id": "req-404"})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "tenant_not_found"
    assert response.json()["trace_id"] == "req-404"


def test_known_host_resolves_tenant() -> None:
    with make_client(base_url="http://tenant-a.test") as client:
        response = client.get("/api/v1/_test/tenant")

    assert response.status_code == 200
    assert response.json() == {"tenant_id": str(TENANT_A)}


def test_platform_subdomain_resolves_tenant() -> None:
    with make_client(base_url="http://tenant-a.platform.test") as client:
        response = client.get("/api/v1/_test/tenant")

    assert response.status_code == 200
    assert response.json() == {"tenant_id": str(TENANT_A)}


def test_exact_domain_wins_over_platform_subdomain() -> None:
    with make_client(base_url="http://exact.platform.test") as client:
        response = client.get("/api/v1/_test/tenant")

    assert response.status_code == 200
    assert response.json() == {"tenant_id": str(TENANT_A)}


def test_tenant_header_is_available_only_when_enabled() -> None:
    with make_client(
        base_url="http://unknown.test",
        allow_tenant_header=True,
    ) as client:
        enabled = client.get("/api/v1/_test/tenant", headers={"X-Tenant": "tenant-b.test"})

    with make_client(
        base_url="http://unknown.test",
        allow_tenant_header=False,
    ) as client:
        disabled = client.get("/api/v1/_test/tenant", headers={"X-Tenant": "tenant-b.test"})

    with make_client(
        base_url="http://unknown.test",
        allow_tenant_header=True,
        app_env="production",
    ) as client:
        production = client.get("/api/v1/_test/tenant", headers={"X-Tenant": "tenant-b.test"})

    assert enabled.status_code == 200
    assert enabled.json() == {"tenant_id": str(TENANT_B)}
    assert disabled.status_code == 404
    assert production.status_code == 404


def test_domain_lookup_does_not_fall_back_to_subdomain() -> None:
    resolver = FakeResolver({("subdomain", "tenant-a"): TENANT_A})
    with make_client(base_url="http://tenant-a", resolver=resolver) as client:
        response = client.get("/api/v1/_test/tenant")

    assert response.status_code == 404
    assert response.json()["code"] == "tenant_not_found"


def test_subdomain_lookup_does_not_fall_back_to_domain() -> None:
    resolver = FakeResolver({("domain", "tenant-a.test"): TENANT_A})
    with make_client(base_url="http://tenant-a.test.platform.test", resolver=resolver) as client:
        response = client.get("/api/v1/_test/tenant")

    assert response.status_code == 404
    assert response.json()["code"] == "tenant_not_found"


def test_missing_resolver_returns_service_unavailable() -> None:
    settings = Settings(database_url=None, allow_tenant_header=False)
    app = create_app(settings, tenant_resolver=None)
    app.include_router(tenant_router())

    with TestClient(app, base_url="http://tenant-a.test") as client:
        response = client.get("/api/v1/_test/tenant")

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


def test_unhandled_error_returns_problem_without_details() -> None:
    with make_client() as client:
        response = client.get("/api/v1/_test/boom", headers={"X-Request-Id": "req-500"})

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.json()["trace_id"] == "req-500"
    assert "details that must not leak" not in response.text


def test_validation_error_returns_fields() -> None:
    with make_client() as client:
        response = client.get("/api/v1/_test/validate?value=not-a-number")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "value" in response.json()["fields"]


def test_validation_error_keeps_body_field_name() -> None:
    with make_client() as client:
        response = client.post("/api/v1/_test/body", json={"path": "not-a-number"})

    assert response.status_code == 422
    assert "path" in response.json()["fields"]


def test_http_500_hides_detail() -> None:
    with make_client() as client:
        response = client.get("/api/v1/_test/http-500")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "secret status detail" not in response.text


def test_http_exception_preserves_headers() -> None:
    with make_client() as client:
        unauthorized = client.get("/api/v1/_test/http-401")
        method_not_allowed = client.get("/api/v1/_test/http-405")

    assert unauthorized.status_code == 401
    assert unauthorized.headers["WWW-Authenticate"] == "Bearer"
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.headers["Allow"] == "GET"


def test_http_503_keeps_service_unavailable_and_hides_detail() -> None:
    with make_client() as client:
        response = client.get("/api/v1/_test/http-503")

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert "secret dependency detail" not in response.text


def test_http_429_keeps_rate_limited_code_and_header() -> None:
    with make_client() as client:
        response = client.get("/api/v1/_test/http-429")

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert response.headers["Retry-After"] == "10"


def test_non_standard_http_status_does_not_crash() -> None:
    with make_client() as client:
        response = client.get("/api/v1/_test/http-499")

    assert response.status_code == 499
    assert response.json()["code"] == "internal_error"


def test_access_log_is_linked_to_request_id() -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("app.access")
    handler = Capture()
    logger.addHandler(handler)
    try:
        with make_client() as client:
            client.get("/health", headers={"X-Request-Id": "req-log"})
    finally:
        logger.removeHandler(handler)

    matching = [record for record in records if getattr(record, "request_id", None) == "req-log"]
    assert matching
    assert getattr(matching[-1], "status_code", None) == 200


def test_resolver_error_is_safe() -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    class ExplodingResolver(TenantResolver):
        async def resolve(self, candidate: TenantCandidate) -> UUID | None:
            raise RuntimeError("resolver secret marker")

    logger = logging.getLogger("app.errors")
    handler = Capture()
    logger.addHandler(handler)
    try:
        with make_client(resolver=ExplodingResolver()) as client:
            response = client.get("/api/v1/_test/tenant", headers={"X-Request-Id": "req-503"})
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert "resolver secret marker" not in response.text
    assert all("resolver secret marker" not in record.getMessage() for record in records)


def test_streaming_response_keeps_session_open_until_body_finishes() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.committed = False
            self.closed = False
            self.info: dict[str, object] = {}

        async def commit(self) -> None:
            self.committed = True

        async def close(self) -> None:
            self.closed = True

    class FakeFactory:
        def __init__(self, session: FakeSession) -> None:
            self.session = session

        def __call__(self) -> AsyncSession:
            return cast(AsyncSession, self.session)

    session = FakeSession()
    factory = cast(async_sessionmaker[AsyncSession], FakeFactory(session))
    settings = Settings(
        database_url=None,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
    )
    app = create_app(
        settings,
        tenant_resolver=FakeResolver({("domain", "tenant-a.test"): TENANT_A}),
        session_factory=factory,
    )

    @app.get("/api/v1/_test/stream")
    async def stream() -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            assert session.closed is False
            yield b"one"
            assert session.closed is False
            yield b"two"

        return StreamingResponse(body(), media_type="text/plain")

    with TestClient(app, base_url="http://tenant-a.test") as client:
        response = client.get("/api/v1/_test/stream")

    assert response.status_code == 200
    assert response.text == "onetwo"
    assert session.committed is True
    assert session.closed is True


def test_duplicate_response_headers_are_preserved() -> None:
    with make_client() as client:
        response = client.get("/api/v1/_test/duplicate-headers")

    assert response.status_code == 200
    assert response.headers.get_list("set-cookie") == ["first=1", "second=2"]


def test_http_413_and_415_have_contract_codes() -> None:
    with make_client() as client:
        too_large = client.get("/api/v1/_test/http-413")
        unsupported = client.get("/api/v1/_test/http-415")

    assert too_large.status_code == 413
    assert too_large.json()["code"] == "payload_too_large"
    assert unsupported.status_code == 415
    assert unsupported.json()["code"] == "unsupported_media_type"


def test_access_log_serializes_tenant_id() -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("app.access")
    handler = Capture()
    logger.addHandler(handler)
    try:
        with make_client(base_url="http://tenant-a.test") as client:
            client.get("/api/v1/_test/tenant", headers={"X-Request-Id": "req-tenant-log"})
    finally:
        logger.removeHandler(handler)

    matching = [
        record for record in records if getattr(record, "request_id", None) == "req-tenant-log"
    ]
    assert matching
    rendered = JsonFormatter().format(matching[-1])
    assert f'"tenant_id": "{TENANT_A}"' in rendered
