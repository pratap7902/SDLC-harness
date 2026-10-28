from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReviewSettings(BaseSettings):
    """The review queue: a material change to a record queues what rests on it."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    REVIEW_PROPAGATION: bool = Field(default=True, validation_alias="REVIEW_PROPAGATION")
