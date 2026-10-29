from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ENVS = ("local", "testing")


class AuthSettings(BaseSettings):
    """Who is calling.

    `token` — `Authorization: Bearer <token>`; the token (actor_tokens) decides the actor,
      its kind (human | agent) and roles. No token, or an unknown / revoked / expired one,
      is 401 on every /api and /mcp request (fail closed).
    `header` — dev and tests only: X-Actor names the person or runner, X-Actor-Kind says
      human | agent. A missing kind is `agent`, never `human`. A bearer token, when sent,
      still wins. Refused outside APP_ENV=local/testing.

    AUTH_MODE unset → `header` under APP_ENV=local/testing, else `token`. The kind `system`
    is never claimable by a caller (header or token): only the service writes as system."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    AUTH_MODE: str = Field(default="", validation_alias="AUTH_MODE")
    # Cloudflare Access in front of the web UI (prod): the IdentityProvider verifies the
    # Cf-Access-Jwt-Assertion and maps the email to a person. Empty → disabled.
    CF_ACCESS_TEAM_DOMAIN: str = Field(default="", validation_alias="CF_ACCESS_TEAM_DOMAIN")
    CF_ACCESS_AUD: str = Field(default="", validation_alias="CF_ACCESS_AUD")

    def mode(self, app_env: str) -> str:
        mode = (self.AUTH_MODE or "").strip().lower() or ("header" if app_env in LOCAL_ENVS else "token")
        if mode not in ("header", "token"):
            raise RuntimeError(f"AUTH_MODE={mode!r}: use token (or header under APP_ENV=local/testing)")
        if mode == "header" and app_env not in LOCAL_ENVS:
            raise RuntimeError(
                f"AUTH_MODE=header trusts X-Actor headers and is for APP_ENV=local/testing only "
                f"(APP_ENV={app_env}) — use AUTH_MODE=token"
            )
        return mode
