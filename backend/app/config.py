from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Keep Rollin API"
    app_version: str = "0.1.0"
    app_env: Literal["local", "test", "production"] = "local"
    database_url: str | None = Field(default=None, repr=False)
    database_timeout_seconds: float = Field(default=2.0, gt=0, le=30)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
