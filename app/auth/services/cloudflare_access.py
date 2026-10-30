"""Cloudflare Access as an identity provider (production web UI).

Access sits in front of the service and adds `Cf-Access-Jwt-Assertion`, an RS256 JWT
signed by the team's keys (https://<team>/cdn-cgi/access/certs), with `aud` = the Access
application's AUD tag and `email` = who signed in. We verify the JWT and map the email to
the canonical person (people directory) → Actor(handle, human). The
`Cf-Access-Authenticated-User-Email` header is never trusted on its own.

Enabled when CF_ACCESS_TEAM_DOMAIN (e.g. your-team.cloudflareaccess.com) and CF_ACCESS_AUD
are set. Service tokens (machine clients) carry no email: they get 403 here and should
use a bearer token instead."""

from typing import Callable, Mapping, Optional

from sqlalchemy.orm import Session

from app.core.utils.actor import Actor
from app.core.utils.jwt_rs256 import JwksCache, JwtError, verify
from app.exceptions import ForbiddenException, UnauthorizedException
from config.settings import settings

HEADER = "cf-access-jwt-assertion"
_caches: dict = {}


def jwks_for(team: str) -> JwksCache:
    if team not in _caches:
        _caches[team] = JwksCache(f"https://{team}/cdn-cgi/access/certs")
    return _caches[team]


def provider(headers: Mapping[str, str], db: Optional[Session], db_factory: Optional[Callable[[], Session]]) -> Optional[Actor]:
    team = (settings.auth.CF_ACCESS_TEAM_DOMAIN or "").strip().removeprefix("https://").rstrip("/")
    token = headers.get(HEADER) or ""
    if not team or not token:
        return None
    try:
        claims = verify(token, jwks_for(team), audience=[settings.auth.CF_ACCESS_AUD], issuer=[f"https://{team}"])
    except JwtError as e:
        raise UnauthorizedException(message=f"Cloudflare Access assertion rejected: {e}", error_code="BAD_ACCESS_JWT") from e
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise ForbiddenException(message="Cloudflare Access identity has no email (a service token?) — use a bearer token", error_code="NO_EMAIL")
    from app.people.services.people_service import PeopleService

    session = db if db is not None else db_factory()
    try:
        person = PeopleService(session).by_email(email)
    finally:
        if db is None:
            session.close()
    if person is None or not person.active:
        raise ForbiddenException(message=f"{email} is not in the people directory — ask an admin to add you", error_code="NOT_IN_DIRECTORY")
    return Actor(principal=person.handle, kind="human", via="web")
