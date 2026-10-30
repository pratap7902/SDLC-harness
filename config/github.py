from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GithubSettings(BaseSettings):
    """GitHub webhooks (POST /hooks/github). The secret is the one set on the GitHub App (or
    repo webhook); empty → the endpoint refuses every delivery (503), never accepts unsigned."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    GITHUB_WEBHOOK_SECRET: str = Field(default="", validation_alias="GITHUB_WEBHOOK_SECRET")
    # The branch prefix the runner uses: harness/<initiative-id>-<task-ref>
    HARNESS_BRANCH_PREFIX: str = Field(default="harness/", validation_alias="HARNESS_BRANCH_PREFIX")
