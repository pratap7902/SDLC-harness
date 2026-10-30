from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TeamsSettings(BaseSettings):
    """Microsoft Teams: the user directory via Microsoft Graph (app-only), notifications and
    inbound button clicks via a Bot Framework bot (Azure Bot resource, single-tenant).
    Secrets come from the environment. Empty TEAMS_TENANT_ID → Teams is off."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    TEAMS_TENANT_ID: str = Field(default="", validation_alias="TEAMS_TENANT_ID")
    # Graph app registration (User.Read.All, application permission, admin-consented)
    TEAMS_GRAPH_CLIENT_ID: str = Field(default="", validation_alias="TEAMS_GRAPH_CLIENT_ID")
    TEAMS_GRAPH_CLIENT_SECRET: str = Field(default="", validation_alias="TEAMS_GRAPH_CLIENT_SECRET")
    # The bot (Azure Bot resource's Microsoft App ID / secret; may be the same app)
    TEAMS_BOT_APP_ID: str = Field(default="", validation_alias="TEAMS_BOT_APP_ID")
    TEAMS_BOT_APP_SECRET: str = Field(default="", validation_alias="TEAMS_BOT_APP_SECRET")
    TEAMS_SERVICE_URL: str = Field(default="https://smba.trafficmanager.net/teams/", validation_alias="TEAMS_SERVICE_URL")
    TEAMS_LOGIN_URL: str = Field(default="https://login.microsoftonline.com", validation_alias="TEAMS_LOGIN_URL")
    TEAMS_GRAPH_URL: str = Field(default="https://graph.microsoft.com/v1.0", validation_alias="TEAMS_GRAPH_URL")
    # Inbound activities: Bot Framework signs them; keys and issuer per the Bot Connector docs
    TEAMS_BOT_JWKS_URL: str = Field(default="https://login.botframework.com/v1/.well-known/keys", validation_alias="TEAMS_BOT_JWKS_URL")
    TEAMS_BOT_ISSUER: str = Field(default="https://api.botframework.com", validation_alias="TEAMS_BOT_ISSUER")
    TEAMS_NOTIFY_MAX_ATTEMPTS: int = Field(default=5, validation_alias="TEAMS_NOTIFY_MAX_ATTEMPTS")

    def enabled(self) -> bool:
        return bool(self.TEAMS_TENANT_ID and self.TEAMS_GRAPH_CLIENT_ID and self.TEAMS_GRAPH_CLIENT_SECRET)

    def bot_enabled(self) -> bool:
        return bool(self.TEAMS_TENANT_ID and self.TEAMS_BOT_APP_ID and self.TEAMS_BOT_APP_SECRET)
