from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application settings (.env or the environment)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = Field(default="local", validation_alias="APP_ENV")
    # Optional error tracking: enabled only when a DSN is set.
    SENTRY_DSN: str = Field(default="", validation_alias="SENTRY_DSN")
    # The Vite dev server (frontend agent) calls the API cross-origin.
    CORS_ORIGINS: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="CORS_ORIGINS",
    )
    # Default lease length for next_work claims.
    LEASE_DEFAULT_TTL_MIN: int = Field(default=15, validation_alias="LEASE_DEFAULT_TTL_MIN")

    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
