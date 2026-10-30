"""Notifications to Teams. State-based: each run reads every open human item (the inbox)
and turns the ones worth a ping into notifications for the routed person —

  gap_routed          a gap is waiting on you (buttons: one per option)
  review_item_queued  something moved under a record you own (button: Still holds)
  approval_stale      your PR approval went stale (the drift digest or head moved)
  overdue             any of your items passed its SLA (once per item)

— then delivers each to the person's Teams account (people directory identity `teams`).
`deliveries` keeps one row per (dedupe_key, channel): a sent row is never resent; a failed
one retries with exponential backoff until TEAMS_NOTIFY_MAX_ATTEMPTS, then is `dead`.
Run it on a schedule (`make notify`, or POST /api/admin/notifications/run)."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.core.utils.time import utcnow
from app.initiatives.services.inbox_service import InboxService
from app.initiatives.services.record_service import RecordService
from app.people.services.people_service import PeopleService
from app.teams.models.delivery import Delivery
from app.teams.services.clients import BotClient
from config.settings import settings

CHANNEL = "teams"


@dataclass
class Notification:
    kind: str
    person: str
    dedupe_key: str
    initiative_id: int
    subject: str
    title: str
    body: str
    link: str
    actions: List[dict] = field(default_factory=list)  # {"title", "data"} → Action.Submit

    def payload(self) -> dict:
        return {"title": self.title, "body": self.body, "link": self.link, "actions": self.actions}


def card(title: str, body: str, link: str, actions: List[dict], note: str = "") -> dict:
    """An Adaptive Card 1.4 message activity: title, body, a link, Action.Submit buttons
    (their `data` comes back as the activity's `value`)."""
    content = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True},
            {"type": "TextBlock", "text": body, "wrap": True},
        ]
        + ([{"type": "TextBlock", "text": note, "isSubtle": True, "wrap": True}] if note else []),
        "actions": [{"type": "Action.Submit", "title": a["title"][:60], "data": {"srs": a["data"]}} for a in actions]
        + [{"type": "Action.OpenUrl", "title": "Open in the web UI", "url": link}],
    }
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": content}]}


def _url(path: str) -> str:
    return settings.people.PUBLIC_BASE_URL.rstrip("/") + path


def collect(records: RecordService) -> List[Notification]:
    out: List[Notification] = []
    inbox = InboxService(records)
    for initiative in records.initiatives.list_ordered():
        for x in inbox.items_for(records.graph(initiative)):
            person = x.get("person")
            if not person:
                continue
            iid, ref, slug = x["initiative_id"], x["ref"], x["initiative"]
            if x["kind"] == "gap":
                options = x.get("options") or []
                out.append(
                    Notification(
                        "gap_routed", person, f"gap_routed:{iid}:{ref}:{person}", iid, ref,
                        f"{slug} · {ref}: {x.get('question') or x.get('title')}",
                        (x.get("context") or "")[:1200] + (f"\n\nRecommended: **{x['recommendation']}** — {x.get('recommendation_why') or ''}" if x.get("recommendation") else ""),
                        _url("/inbox"),
                        [{"title": f"Answer: {o.get('label') or o.get('key')}", "data": {"action": "answer_gap", "initiative_id": iid, "ref": ref, "choice": o.get("key")}} for o in options if o.get("key")],
                    )
                )
            elif x["kind"] == "review_item":
                out.append(
                    Notification(
                        "review_item_queued", person, f"review_item_queued:{x['review_item_id']}:{person}", iid, x["target"],
                        f"{slug} · {x['title']}", x.get("what_moved") or "", _url(f"/features/{iid}/reviews"),
                        [{"title": "Still holds", "data": {"action": "uphold_review", "initiative_id": iid, "review_item_id": x["review_item_id"]}}],
                    )
                )
            elif x["kind"] == "approval" and x.get("stale_approvals"):
                out.append(
                    Notification(
                        "approval_stale", person, f"approval_stale:{iid}:{ref}:{x.get('digest', '')[:16]}:{x.get('pr_sha') or ''}", iid, ref,
                        f"{slug} · your approval of {ref} went stale", "The PR head or the drift report moved since you approved. Re-read the drift report and approve again.",
                        _url(f"/features/{iid}/tasks/{ref}"),
                    )
                )
            if x.get("overdue"):
                out.append(
                    Notification(
                        "overdue", person, f"overdue:{x['key']}:{person}", iid, ref,
                        f"{slug} · overdue: {x.get('title') or ref}", f"Waiting on you for {x['age_hours']} h (SLA {x['sla_hours']} h).",
                        _url("/inbox"),
                    )
                )
    return out


class Notifier:
    def __init__(self, db: Session, bot_factory: Callable[[], BotClient] = BotClient):
        self.db = db
        self.people = PeopleService(db)
        self.bot_factory = bot_factory

    def run(self, now=None) -> dict:
        now = now or utcnow()
        counts = {"sent": 0, "failed": 0, "skipped_no_teams": 0, "already": 0, "waiting": 0}
        if not settings.teams.bot_enabled():
            return {**counts, "disabled": True}
        bot: Optional[BotClient] = None
        for n in collect(RecordService(self.db)):
            identity = self.people.identity_of(n.person, "teams")
            if identity is None:
                counts["skipped_no_teams"] += 1
                continue
            row = self.db.query(Delivery).filter(Delivery.dedupe_key == n.dedupe_key, Delivery.channel == CHANNEL).one_or_none()
            if row is None:
                row = Delivery(dedupe_key=n.dedupe_key, channel=CHANNEL, person=n.person, kind=n.kind, initiative_id=n.initiative_id, subject=n.subject, payload=n.payload(), status="pending", attempts=0, created_at=now)
                self.db.add(row)
                self.db.flush()
            if row.status in ("sent", "dead"):
                counts["already"] += 1
                continue
            if row.next_attempt_at is not None and row.next_attempt_at > now:
                counts["waiting"] += 1
                continue
            bot = bot or self.bot_factory()
            try:
                conversation = (identity.meta or {}).get("conversation_id")
                if not conversation:
                    conversation = bot.create_conversation(identity.external_id)
                    identity.meta = {**(identity.meta or {}), "conversation_id": conversation}
                row.activity_id = bot.send(conversation, card(n.title, n.body, n.link, n.actions))
                row.conversation_id, row.status, row.sent_at, row.last_error = conversation, "sent", now, None
                row.attempts += 1
                counts["sent"] += 1
            except Exception as e:  # noqa: BLE001 — any failure is a retry, recorded
                row.attempts += 1
                row.last_error = str(e)[:400]
                dead = row.attempts >= settings.teams.TEAMS_NOTIFY_MAX_ATTEMPTS
                row.status = "dead" if dead else "failed"
                row.next_attempt_at = None if dead else now + timedelta(minutes=2 ** row.attempts)
                counts["failed"] += 1
            self.db.commit()
        self.db.commit()
        return counts

    def deliveries(self, status: Optional[str] = None, limit: int = 200) -> List[dict]:
        q = self.db.query(Delivery)
        if status:
            q = q.filter(Delivery.status == status)
        return [
            {
                "id": d.id, "dedupe_key": d.dedupe_key, "channel": d.channel, "person": d.person, "kind": d.kind,
                "initiative_id": d.initiative_id, "subject": d.subject, "status": d.status, "attempts": d.attempts,
                "last_error": d.last_error, "sent_at": d.sent_at.isoformat() if d.sent_at else None,
                "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None,
            }
            for d in q.order_by(Delivery.id.desc()).limit(limit).all()
        ]

