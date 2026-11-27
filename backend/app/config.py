import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-only-change-me-keep-rollin-secret"
KEY_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "Keep Rollin API"
    app_version: str = "0.1.0"
    app_env: Literal["local", "test", "production"] = "local"
    database_url: str | None = Field(default=None, repr=False, exclude=True)
    provision_database_url: str | None = Field(default=None, repr=False, exclude=True)
    audit_retention_days: int = Field(default=365, ge=30, le=3650)
    database_role: str = Field(default="keep_rollin_app", pattern=r"^[a-z_][a-z0-9_]*$")
    database_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    platform_domain: str = "platform.test"
    allow_tenant_header: bool = False
    jwt_secret: str = Field(
        default=DEFAULT_JWT_SECRET,
        min_length=32,
        repr=False,
        exclude=True,
    )
    access_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_ttl_days: int = Field(default=30, ge=1, le=90)
    password_work_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    refresh_cookie_name: str = "__Host-rt"
    refresh_cookie_secure: bool = True
    security_key: str | None = Field(default=None, min_length=32, repr=False, exclude=True)
    security_key_id: str = Field(default="primary", pattern=r"^[a-z0-9_-]{1,32}$")
    security_previous_keys: dict[str, str] = Field(default_factory=dict, repr=False, exclude=True)
    password_reset_ttl_seconds: int = Field(default=3600, ge=3600, le=3600)
    auth_rate_limit_per_minute: int = Field(default=10, ge=1, le=1000)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    auth_rate_limit_email_per_minute: int = Field(default=10, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_auth_settings(self) -> "Settings":
        if self.app_env == "production":
            if self.jwt_secret == DEFAULT_JWT_SECRET:
                raise ValueError("JWT_SECRET must be configured in production")
            if len(set(self.jwt_secret)) < 12:
                raise ValueError("JWT_SECRET is too weak; use a random value")
            if self.refresh_cookie_name != "__Host-rt":
                raise ValueError("production refresh cookie must be __Host-rt")
            if not self.refresh_cookie_secure:
                raise ValueError("production refresh cookie must be Secure")
            if self.security_key is None:
                raise ValueError("SECURITY_KEY must be configured in production")
            if self.security_key == self.jwt_secret:
                raise ValueError("SECURITY_KEY must differ from JWT_SECRET")
            self._require_base64_key(self.security_key, "SECURITY_KEY")
            for key_id, key in self.security_previous_keys.items():
                if self.security_key_id == key_id:
                    raise ValueError("previous SECURITY key id must differ from the current id")
                if not KEY_ID_RE.fullmatch(key_id):
                    raise ValueError(f"invalid previous SECURITY key id: {key_id}")
                self._require_base64_key(key, f"SECURITY_PREVIOUS_KEYS[{key_id}]")
        if self.refresh_cookie_name.startswith("__Host-") and not self.refresh_cookie_secure:
            raise ValueError("__Host- cookies require Secure")
        return self

    @staticmethod
    def _require_base64_key(value: str, name: str) -> None:
        import base64
        import binascii
        import zlib

        padded = value + "=" * (-len(value) % 4)
        try:
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"{name} must be base64url encoded") from exc
        if len(raw) != 32:
            raise ValueError(f"{name} must contain exactly 32 bytes")
        # Best-effort rejection of placeholders and repeated patterns. Entropy
        # itself is an operational requirement: keys must come from a CSPRNG.
        if len(set(raw)) < 16 or len(zlib.compress(raw, 9)) < 40:
            raise ValueError(f"{name} must be random key material, not a placeholder")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
