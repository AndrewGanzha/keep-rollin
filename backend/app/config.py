from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-only-change-me-keep-rollin-secret"


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
    database_url: str | None = Field(default=None, repr=False)
    database_role: str = Field(default="keep_rollin_app", pattern=r"^[a-z_][a-z0-9_]*$")
    database_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    platform_domain: str = "platform.test"
    allow_tenant_header: bool = False
    jwt_secret: str = Field(
        default=DEFAULT_JWT_SECRET,
        min_length=32,
        repr=False,
    )
    access_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_ttl_days: int = Field(default=30, ge=1, le=90)
    password_work_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    refresh_cookie_name: str = "__Host-rt"
    refresh_cookie_secure: bool = True

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
        if self.refresh_cookie_name.startswith("__Host-") and not self.refresh_cookie_secure:
            raise ValueError("__Host- cookies require Secure")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
