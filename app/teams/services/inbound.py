"""Inbound Teams activities (the bot's messaging endpoint, POST /api/teams/messages).

1. Verify: the Bot Connector signs every request with an RS256 JWT
   (`Authorization: Bearer …`): keys from TEAMS_BOT_JWKS_URL, `iss` TEAMS_BOT_ISSUER, `aud`
   the bot's app id, and its `serviceUrl` claim must equal the activity's serviceUrl.
2. Map: `from.aadObjectId` → the canonical person (people directory, source `teams`).
   Not in the directory → refused, nothing written.
3. Act through the SAME human-only service paths as the web UI, as
   Actor(handle, human, via=teams): answer a gap (InboxService.answer_gap — the gap
   records `answered_via: teams`) or uphold a review item (ReviewService.resolve).
4. Replace the card with the outcome (Bot Connector update), so the buttons are gone."""

from typing import Mapping, Optional

from sqlalchemy.orm import Session

from app.core.utils.actor import Actor
from app.core.utils.jwt_rs256 import JwksCache, JwtError, verify
from app.exceptions import BaseAppException, UnauthorizedException
from app.initiatives.services.inbox_service import InboxService
from app.initiatives.services.record_service import RecordService
from app.initiatives.services.review_service import ReviewService
from app.people.services.people_service import PeopleService
from app.teams.services.clients import BotClient, TeamsError
from app.teams.services.notifications import card
from config.settings import settings

_jwks: dict = {}


def _cache() -> JwksCache:
    url = settings.teams.TEAMS_BOT_JWKS_URL
    if url not in _jwks:
        _jwks[url] = JwksCache(url)
    return _jwks[url]


def verify_request(headers: Mapping[str, str], activity: dict) -> dict:
    if not settings.teams.bot_enabled():
        raise UnauthorizedException(message="Teams bot is not configured", error_code="TEAMS_DISABLED")
    auth = headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise UnauthorizedException(message="Bot Framework token required", error_code="BAD_BOT_TOKEN")
    try:
        claims = verify(auth[7:].strip(), _cache(), audience=[settings.teams.TEAMS_BOT_APP_ID], issuer=[settings.teams.TEAMS_BOT_ISSUER])
    except JwtError as e:
        raise UnauthorizedException(message=f"Bot Framework token rejected: {e}", error_code="BAD_BOT_TOKEN") from e
    claimed = (claims.get("serviceurl") or claims.get("serviceUrl") or "").rstrip("/")
    if claimed and claimed != (activity.get("serviceUrl") or "").rstrip("/"):
        raise UnauthorizedException(message="serviceUrl does not match the token", error_code="BAD_BOT_TOKEN")
    return claims


class TeamsInbound:
    def __init__(self, db: Session, bot: Optional[BotClient] = None):
        self.db = db
        self.records = RecordService(db)
        self.bot = bot

    def handle(self, headers: Mapping[str, str], activity: dict) -> dict:
        verify_request(headers, activity)
        data = ((activity.get("value") or {}) if isinstance(activity.get("value"), dict) else {}).get("srs")
        if activity.get("type") != "message" or not isinstance(data, dict):
            return {"handled": False, "why": "not an srs card action"}
        aad = ((activity.get("from") or {}).get("aadObjectId") or "").strip()
        person = PeopleService(self.db).by_identity("teams", aad) if aad else None
        if person is None:
            return self._reply(activity, "You are not in the SDLC people directory, so nothing was recorded. Ask an admin to add you.", handled=False)
        actor = Actor(principal=person.handle, kind="human", via="teams")
        try:
            outcome = self._act(data, actor)
        except BaseAppException as e:
            self.db.rollback()
            return self._reply(activity, f"Not recorded: {e.message}", handled=False)
        return self._replace(activity, outcome)

    def _act(self, data: dict, actor: Actor) -> str:
        action = data.get("action")
        iid = int(data.get("initiative_id") or 0)
        if action == "answer_gap":
            ref, choice = str(data.get("ref") or ""), data.get("choice")
            InboxService(self.records).answer_gap(iid, ref, "", choice, actor)
            return f"{ref} answered “{choice}” by {actor.principal} (via Teams)."
        if action == "uphold_review":
            initiative = self.records.initiative(iid)
            item = ReviewService(self.db, self.records.bp).resolve(initiative, int(data["review_item_id"]), "upheld", "still holds (via Teams)", actor)
            self.records.events.add("review_item_resolved", initiative.id, item.target_ref, actor.name, "", {"id": item.id, "resolution": item.status, "via": "teams"})
            self.db.commit()
            return f"{item.target_ref} upheld by {actor.principal} (via Teams)."
        raise_unknown(action)
        return ""

    def _replace(self, activity: dict, text: str) -> dict:
        bot = self._bot(activity)
        conversation = (activity.get("conversation") or {}).get("id")
        reply_to = activity.get("replyToId")
        if bot and conversation and reply_to:
            try:
                bot.update(conversation, reply_to, card("Done", text, settings.people.PUBLIC_BASE_URL, []))
            except TeamsError:
                pass  # the record is written; a stale card is cosmetic
        return {"handled": True, "result": text}

    def _reply(self, activity: dict, text: str, handled: bool) -> dict:
        bot = self._bot(activity)
        conversation = (activity.get("conversation") or {}).get("id")
        if bot and conversation:
            try:
                bot.send(conversation, {"type": "message", "text": text, "replyToId": activity.get("id")})
            except TeamsError:
                pass
        return {"handled": handled, "result": text}

    def _bot(self, activity: dict) -> Optional[BotClient]:
        return self.bot or BotClient(activity.get("serviceUrl"))


def raise_unknown(action) -> None:
    from app.exceptions import ValidationException

    raise ValidationException(message=f"unknown action {action!r}")
