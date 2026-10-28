"""Who is calling, and as what. Every write names a person or runner (`actor`) and a
kind (`human` | `agent` | `system`); the kind decides what the write path lets through
(`actor: human` fields, approvals)."""

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from app.exceptions import ForbiddenException

ACTOR_HEADER = "x-actor"
ACTOR_KIND_HEADER = "x-actor-kind"
KINDS = ("human", "agent", "system")


@dataclass(frozen=True)
class Actor:
    principal: str  # the person or runner (X-Actor)
    kind: str  # human | agent | system
    agent: str = ""  # which agent / skill, when given

    @property
    def name(self) -> str:
        """`<who>/<which agent>` — what revisions and events record."""
        return actor_of(self.principal, self.agent)


def actor_of(principal: Optional[str], agent: Optional[str] = None) -> str:
    """`<who>/<which agent>`. Empty when nobody is named; RecordService refuses such a write."""
    principal = (principal or "").strip()
    agent = (agent or "").strip()
    if not principal:
        return ""
    return f"{principal}/{agent}" if agent else principal


def kind_of(header_kind: Optional[str], agent: Optional[str]) -> str:
    """AUTH_MODE=header: X-Actor-Kind when sent; else `agent` when an agent label is
    given; else `human` (the web UI)."""
    kind = (header_kind or "").strip().lower()
    if kind in KINDS:
        return kind
    return "agent" if (agent or "").strip() else "human"


def actor_from_request(request: Request, agent: Optional[str] = None) -> Actor:
    principal = request.headers.get(ACTOR_HEADER, "")
    return Actor(
        principal=principal.strip(),
        kind=kind_of(request.headers.get(ACTOR_KIND_HEADER), agent),
        agent=(agent or "").strip(),
    )


def require_human(actor: Actor) -> Actor:
    """Human-only operations (answer a gap, rule a decision, approve, sign, promote)."""
    if actor.kind != "human":
        raise ForbiddenException(
            message=f"Human-only operation: {actor.name or 'this caller'} is a "
            f"{actor.kind}. Agents ask (raise a gap); humans answer in the web UI.",
            error_code="HUMAN_ONLY",
        )
    return actor
