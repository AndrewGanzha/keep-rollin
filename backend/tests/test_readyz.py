import asyncpg
import pytest
from fastapi.testclient import TestClient

import app.api.health as health_module
from app.config import Settings
from app.main import create_app


def test_readyz_is_unavailable_without_database(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "unavailable"},
    }


def test_readyz_is_ok_when_database_is_ready(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_database_ready(dsn: str | None, timeout_seconds: float) -> bool:
        return True

    monkeypatch.setattr(health_module, "database_ready", fake_database_ready)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok"},
    }


def test_readyz_does_not_echo_database_url() -> None:
    app = create_app(
        Settings(
            database_url="postgresql://user:secret@127.0.0.1:1/keep_rollin",
            database_timeout_seconds=0.1,
        )
    )

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert "secret" not in response.text
    assert "127.0.0.1" not in response.text


@pytest.mark.parametrize(
    "error",
    [
        NotImplementedError("unsupported transport"),
        asyncpg.exceptions.InternalClientError("gssapi is unavailable"),
    ],
    ids=["unsupported-transport", "gssapi-unavailable"],
)
def test_readyz_maps_driver_connection_errors_to_503(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    async def failing_connect(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(asyncpg, "connect", failing_connect)
    app = create_app(
        Settings(
            database_url="postgresql://postgres@/keep_rollin?host=/tmp",
            database_timeout_seconds=0.1,
        )
    )

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"
