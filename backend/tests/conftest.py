from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(database_url=None, database_timeout_seconds=0.1))
    with TestClient(app) as test_client:
        yield test_client
