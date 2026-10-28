"""Who a human item lands on: domain → role (lifecycle.yaml routing.by_domain) → the
initiative's ACTIVE assignment for that role (task-scoped first) → person. Unroutable →
the fallback role (dri). Derived on read, never stored on the record."""

from dataclasses import dataclass
from typing import Optional

from app.initiatives.models.record import Record

TYPE_ROLE = {"task": "engg", "test_run": "engg", "finding": "engg", "deploy": "engg", "draft": "dri", "acceptance_criterion": "dri"}


@dataclass
class Route:
    person: Optional[str]
    role: str
    domain: Optional[str]
    fallback: bool = False

    def to_dict(self) -> dict:
        return {"person": self.person, "role": self.role, "domain": self.domain, "fallback": self.fallback}


class Router:
    def __init__(self, graph):
        self.g = graph
        self.routing = graph.bp.lifecycle.routing if graph.bp.lifecycle else {}

    def role_for_domain(self, domain: Optional[str]) -> Optional[str]:
        return (self.routing.get("by_domain") or {}).get(domain or "")

    def route(self, record: Record, cause: Optional[Record] = None) -> Route:
        domain = self.g.f(record, "domain") or (self.g.f(cause, "domain") if cause is not None else None)
        role = self.role_for_domain(domain) if domain else TYPE_ROLE.get(record.type)
        role = role or self.routing.get("fallback", "dri")
        task_ref = record.ref if record.type == "task" else None
        if task_ref is None:
            blocked_tasks = [b for b in self.g.f(record, "blocks") or [] if self.g.bp.type_of_ref(b) == "task"]
            task_ref = blocked_tasks[0] if blocked_tasks else None
        person = self.g.person_for(role, task_ref)
        if person:
            return Route(person, role, domain)
        fallback = self.routing.get("fallback", "dri")
        return Route(self.g.person_for(fallback), fallback, domain, fallback=True)

    def for_role(self, role: str, task_ref: Optional[str] = None) -> Route:
        person = self.g.person_for(role, task_ref)
        if person:
            return Route(person, role, None)
        fallback = self.routing.get("fallback", "dri")
        return Route(self.g.person_for(fallback), fallback, None, fallback=True)
