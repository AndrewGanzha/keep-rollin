from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_invalid_dsn_keeps_health_and_readiness_safe() -> None:
    settings = Settings(
        database_url="postgresql://postgres@127.0.0.1:5432/keep_rollin?sslmode=typo",
        database_timeout_seconds=0.1,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        health = client.get("/health")
        readiness = client.get("/readyz")

    assert health.status_code == 200
    assert readiness.status_code == 503
    assert readiness.json()["checks"]["database"] == "unavailable"
