import pytest

from app.config import Settings


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "postgresql://user:pass@127.0.0.1:5432/keep_rollin"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATABASE_TIMEOUT_SECONDS", "1.5")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.database_url == database_url
    assert settings.database_timeout_seconds == 1.5


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_TIMEOUT_SECONDS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.database_url is None
    assert settings.database_timeout_seconds == 2.0
