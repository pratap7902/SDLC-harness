"""Who is calling, and as what. Every write names a person or runner (`actor`) and a
kind (`human` | `agent` | `system`); the kind decides what the write path lets through
(`actor: human` fields, approvals). Callers authenticate as `human` or `agent` only
(app/auth); `system` is the service itself (baselines, integrations) and is never taken
from a request."""

from dataclasses import dataclass, replace
from typing import Optional, Tuple

from app.exceptions import ForbiddenException

ACTOR_HEADER = "x-actor"
ACTOR_KIND_HEADER = "x-actor-kind"
ACTOR_ROLES_HEADER = "x-actor-roles"
KINDS = ("human", "agent", "system")
CALLER_KINDS = ("human", "agent")


@dataclass(frozen=True)
class Actor:
    principal: str  # the person or runner
    kind: str  # human | agent | system
    agent: str = ""  # which agent / skill, when given
    roles: Tuple[str, ...] = ()  # service roles from the token (admin, ci); not assignments
    via: str = "web"  # the channel a human acted through: web | teams | api

    @property
    def name(self) -> str:
        """`<who>/<which agent>` — what revisions and events record."""
        return actor_of(self.principal, self.agent)

    def with_agent(self, agent: Optional[str]) -> "Actor":
        agent = (agent or "").strip()
        return replace(self, agent=agent) if agent else self


def actor_of(principal: Optional[str], agent: Optional[str] = None) -> str:
    """`<who>/<which agent>`. Empty when nobody is named; RecordService refuses such a write."""
    principal = (principal or "").strip()
    agent = (agent or "").strip()
    if not principal:
        return ""
    return f"{principal}/{agent}" if agent else principal


def require_human(actor: Actor) -> Actor:
    """Human-only operations (answer a gap, rule a decision, approve, sign, promote)."""
    if actor.kind != "human":
        raise ForbiddenException(
            message=f"Human-only operation: {actor.name or 'this caller'} is a "
            f"{actor.kind}. Agents ask (raise a gap); humans answer in the web UI.",
            error_code="HUMAN_ONLY",
        )
    return actor


def require_role(actor: Actor, role: str) -> Actor:
    if role not in actor.roles:
        raise ForbiddenException(
            message=f"{actor.name or 'this caller'} lacks the service role '{role}' (a token role)",
            error_code="ROLE_REQUIRED",
        )
    return actor


SERVICE = Actor(principal="srs", kind="system")
