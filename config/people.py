from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PeopleSettings(BaseSettings):
    """The canonical people directory."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # How directory entries from integrations merge into one person. Only `email` today.
    PEOPLE_MATCH_KEY: str = Field(default="email", validation_alias="PEOPLE_MATCH_KEY")
    # Where links in notifications point (the web UI).
    PUBLIC_BASE_URL: str = Field(default="http://localhost:8791", validation_alias="PUBLIC_BASE_URL")
