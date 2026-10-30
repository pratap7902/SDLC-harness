from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KnowledgeSettings(BaseSettings):
    """The Outline knowledge base (REST API). Secrets come from the environment. Empty
    OUTLINE_API_KEY → the kb tools say the KB is not configured."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    OUTLINE_URL: str = Field(default="", validation_alias="OUTLINE_URL")  # e.g. https://wiki.example.com
    OUTLINE_API_KEY: str = Field(default="", validation_alias="OUTLINE_API_KEY")
    # Cloudflare Access service token in front of Outline (optional)
    OUTLINE_CF_ACCESS_CLIENT_ID: str = Field(default="", validation_alias="OUTLINE_CF_ACCESS_CLIENT_ID")
    OUTLINE_CF_ACCESS_CLIENT_SECRET: str = Field(default="", validation_alias="OUTLINE_CF_ACCESS_CLIENT_SECRET")

    def enabled(self) -> bool:
        return bool(self.OUTLINE_URL and self.OUTLINE_API_KEY)
