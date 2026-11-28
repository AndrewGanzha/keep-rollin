import base64
import hashlib

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_JWT_SECRET, Settings

JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"
SECURITY_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(b"keep-rollin-test-security-key").digest()
).decode("ascii")


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=DEFAULT_JWT_SECRET,
        )


def test_production_rejects_low_entropy_jwt_secret() -> None:
    weak_secret = "a" * 40
    with pytest.raises(ValidationError) as raised:
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=weak_secret,
        )

    assert weak_secret not in str(raised.value)


def test_production_requires_host_refresh_cookie() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=JWT_SECRET,
            refresh_cookie_name="rt",
        )


def test_production_requires_secure_refresh_cookie() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=JWT_SECRET,
            refresh_cookie_name="__Host-rt",
            refresh_cookie_secure=False,
        )


def test_host_prefixed_cookie_requires_secure_in_any_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="test",
            jwt_secret=JWT_SECRET,
            refresh_cookie_name="__Host-rt",
            refresh_cookie_secure=False,
        )


def test_production_accepts_contract_cookie_settings() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret=JWT_SECRET,
        security_key=SECURITY_KEY,
        refresh_cookie_name="__Host-rt",
        refresh_cookie_secure=True,
    )

    assert settings.refresh_cookie_name == "__Host-rt"
    assert settings.refresh_cookie_secure is True
    assert "security_key" not in settings.model_dump()
    assert SECURITY_KEY not in repr(settings)


def test_production_requires_high_entropy_base64_security_key() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=JWT_SECRET,
            security_key="short",
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=JWT_SECRET,
            security_key="a" * 32,
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=JWT_SECRET,
            security_key=JWT_SECRET,
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=JWT_SECRET,
            security_key=base64.urlsafe_b64encode(b"z" * 32).decode("ascii"),
        )


def test_production_rejects_previous_key_id_with_colon() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret=JWT_SECRET,
            security_key=SECURITY_KEY,
            security_previous_keys={"bad:id": SECURITY_KEY},
        )
