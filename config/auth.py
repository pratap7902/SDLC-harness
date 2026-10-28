from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Who is calling. `header` (dev, tests): X-Actor names the person or runner,
    X-Actor-Kind says human | agent | system. `token` (bearer tokens → actor_tokens) is
    deferred — see README."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    AUTH_MODE: str = Field(default="header", validation_alias="AUTH_MODE")
