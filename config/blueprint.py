from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BlueprintSettings(BaseSettings):
    """Where the engineer-edited structure (record types, vocabularies, lifecycle) is
    loaded from."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BLUEPRINT_DIR: Path = Field(
        default=Path(__file__).resolve().parent.parent / "blueprint",
        validation_alias="BLUEPRINT_DIR",
    )
