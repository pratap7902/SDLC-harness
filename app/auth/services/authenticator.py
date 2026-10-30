"""Turn a request's headers into an Actor — the only place that decides who a caller is.

1. `Authorization: Bearer <token>` → actor_tokens (any mode).
2. Cloudflare Access (when CF_ACCESS_TEAM_DOMAIN is set): a verified
   Cf-Access-Jwt-Assertion → the email → the canonical person (kind human).
3. AUTH_MODE=header only (local/testing): X-Actor + X-Actor-Kind (human | agent; missing
   → agent, never human). Without X-Actor the caller is anonymous: reads work, writes are
   refused by the write path.
Token mode with none of 1–2 → 401. `system` is refused from every source."""

from typing import Callable, Mapping, Optional

from sqlalchemy.orm import Session

from app.auth.services import cloudflare_access  # noqa: E402
from app.auth.services.token_service import TokenService
from app.core.utils.actor import ACTOR_HEADER, ACTOR_KIND_HEADER, ACTOR_ROLES_HEADER, CALLER_KINDS, Actor
from app.exceptions import ForbiddenException, UnauthorizedException
from config.settings import settings

# Identity sources tried after a bearer token: fn(headers, db, db_factory) → Actor | None.
IDENTITY_PROVIDERS: list = [cloudflare_access.provider]


def auth_mode() -> str:
    return settings.auth.mode(settings.app.APP_ENV)


def bearer(headers: Mapping[str, str]) -> str:
    value = (headers.get("authorization") or "").strip()
    if value[:7].lower() == "bearer ":
        return value[7:].strip()
    return ""


def authenticate(headers: Mapping[str, str], db: Optional[Session] = None, db_factory: Optional[Callable[[], Session]] = None) -> Actor:
    token = bearer(headers)
    if token:
        session = db if db is not None else (db_factory() if db_factory else None)
        if session is None:
            raise UnauthorizedException(message="token auth needs the database")
        try:
            actor = TokenService(session).actor(token)
        finally:
            if db is None and session is not None:
                session.close()
        if actor is None:
            raise UnauthorizedException(message="Unknown, revoked or expired token", error_code="BAD_TOKEN")
        return actor
    for provider in IDENTITY_PROVIDERS:
        actor = provider(headers, db, db_factory)
        if actor is not None:
            return actor
    if auth_mode() != "header":
        raise UnauthorizedException(
            message="Authentication required: send Authorization: Bearer <token> (scripts/mint_token.py)",
            error_code="AUTH_REQUIRED",
        )
    principal = (headers.get(ACTOR_HEADER) or "").strip()
    kind = (headers.get(ACTOR_KIND_HEADER) or "").strip().lower() or "agent"
    if kind not in CALLER_KINDS:
        raise ForbiddenException(
            message=f"X-Actor-Kind: {kind!r} — callers are human or agent; `system` is the service itself",
            error_code="KIND_NOT_ALLOWED",
        )
    roles = tuple(r.strip() for r in (headers.get(ACTOR_ROLES_HEADER) or "").split(",") if r.strip())
    return Actor(principal=principal[:128], kind=kind, roles=roles, via="web" if kind == "human" else "api")
