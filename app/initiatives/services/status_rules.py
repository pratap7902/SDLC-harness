"""Derived statuses. Every type's status is computed from the graph on every load; the
names here are the `rule:` names in blueprint/lifecycle.yaml (make check pairs them).

Rules run in passes, because some read others' results: own-field rules first, then AC
(reads the baseline), then the draft (reads the drift report), approvals (read the task's
drift digest), tasks (read decisions, gaps, test runs, leases), and the initiative last
(reads gates)."""

from dataclasses import dataclass
from typing import Callable, Dict, Tuple

from app.blueprint.schemas.blueprint import Blueprint
from app.initiatives.models.record import Record

LIVE_AC = ("PROPOSED", "APPROVED", "ADDED_AFTER_BASELINE")


@dataclass(frozen=True)
class StatusRuleImpl:
    fn: Callable
    produces: Tuple[str, ...]
    order: int


STATUS_RULES: Dict[str, StatusRuleImpl] = {}


def rule(name: str, produces: Tuple[str, ...], order: int = 1):
    def register(fn):
        STATUS_RULES[name] = StatusRuleImpl(fn, produces, order)
        return fn

    return register


def _int(value) -> int:
    try:
        return int(str(value or "0").strip() or 0)
    except ValueError:
        return 0


# ── pass 1: the record's own fields (and simple edges) ─────────────────────


@rule("assignment_status", ("ACTIVE", "REPLACED"))
def assignment_status(r: Record, g, args) -> str:
    role, scope = g.f(r, "role"), sorted(g.f(r, "scope") or [])
    from app.initiatives.services.record_graph import ref_num

    for other in g.of_type("assignment"):
        if (
            other.ref != r.ref
            and g.f(other, "role") == role
            and sorted(g.f(other, "scope") or []) == scope
            and ref_num(other.ref) > ref_num(r.ref)
        ):
            return "REPLACED"
    return "ACTIVE"


@rule("decision_status", ("OPEN", "PROVISIONAL", "DECIDED", "SUPERSEDED"))
def decision_status(r: Record, g, args) -> str:
    if g.in_(r.ref, "supersedes"):
        return "SUPERSEDED"
    if not g.f(r, "verdict"):
        return "OPEN"
    if str(g.f(r, "provisional", "")).lower() == "yes":
        return "PROVISIONAL"
    return "DECIDED"


@rule("gap_status", ("OPEN", "ANSWERED", "WITHDRAWN"))
def gap_status(r: Record, g, args) -> str:
    if g.f(r, "withdrawn_because"):
        return "WITHDRAWN"
    if g.f(r, "answer"):
        return "ANSWERED"
    return "OPEN"


@rule("finding_status", ("OPEN", "FIXED", "REJECTED", "ACKNOWLEDGED"))
def finding_status(r: Record, g, args) -> str:
    resolution = g.f(r, "resolution")
    return str(resolution).upper() if resolution else "OPEN"


@rule("test_run_status", ("GREEN", "RED", "ERROR"))
def test_run_status(r: Record, g, args) -> str:
    return g.f(r, "result") or "ERROR"


@rule("deploy_status", ("PENDING", "DEPLOYED", "FAILED", "ROLLED_BACK"))
def deploy_status(r: Record, g, args) -> str:
    return g.f(r, "result") or "PENDING"


@rule("baseline_status", ("CURRENT", "SUPERSEDED"))
def baseline_status(r: Record, g, args) -> str:
    current = g.current_baseline()
    return "CURRENT" if current is not None and current.ref == r.ref else "SUPERSEDED"


@rule("field_status", ("*",))
def field_status(r: Record, g, args) -> str:
    value = g.f(r, args.get("field", "status"))
    return str(value).upper() if value else "DRAFT"


# ── pass 2: the baseline ───────────────────────────────────────────────────


@rule("ac_status", ("PROPOSED", "APPROVED", "ADDED_AFTER_BASELINE", "RETIRED"), order=2)
def ac_status(r: Record, g, args) -> str:
    if g.f(r, "retired_because"):
        return "RETIRED"
    baseline = g.current_baseline()
    if baseline is None:
        return "PROPOSED"
    return "APPROVED" if r.ref in g.baseline_members(baseline) else "ADDED_AFTER_BASELINE"


# ── pass 3: the drift report ───────────────────────────────────────────────


@rule("draft_status", ("DRAFTING", "IN_REVIEW", "APPROVED", "REOPENED"), order=3)
def draft_status(r: Record, g, args) -> str:
    if g.current_baseline() is not None:
        return "REOPENED" if g.drift().unexplained else "APPROVED"
    return "IN_REVIEW" if g.f(r, "submitted_rev") else "DRAFTING"


# ── pass 4: approvals (read the draft status and the task's drift digest) ──


@rule("approval_status", ("CURRENT", "STALE"), order=4)
def approval_status(r: Record, g, args) -> str:
    targets = g.f(r, "target") or []
    target = g.get(targets[0]) if targets else None
    if target is None:
        return "STALE"
    if target.type == "draft":
        baseline = g.current_baseline()
        made = set(g.in_(r.ref, "from"))
        ok = baseline is not None and baseline.ref in made and target.status != "REOPENED"
        return "CURRENT" if ok else "STALE"
    if target.type == "task":
        if g.f(r, "at_sha") != g.f(target, "pr_sha"):
            return "STALE"
        return "CURRENT" if g.f(r, "drift_digest") == g.drift(task=target.ref).digest else "STALE"
    approved_rev = g.f(r, "approved_rev")
    return "CURRENT" if not approved_rev or str(target.head_rev) == str(approved_rev) else "STALE"


# ── pass 5: tasks ──────────────────────────────────────────────────────────


def covered_green(g, task: Record, ac_ref: str, sha: str) -> bool:
    for run in g.of_type("test_run"):
        if g.f(run, "at_sha") != sha or g.f(run, "result") != "GREEN":
            continue
        for row in g.f(run, "covers") or []:
            if row.get("ac") == ac_ref and row.get("result", "GREEN") in ("", "GREEN"):
                return True
    return False


@rule("task_status", ("READY", "IN_PROGRESS", "IN_REVIEW", "BLOCKED", "STUCK", "DONE"), order=5)
def task_status(r: Record, g, args, _seen=None) -> str:
    seen = set(_seen or ()) | {r.ref}
    pr_state = g.f(r, "pr_state") or "none"
    sha = g.f(r, "pr_sha") or ""
    live_covers = [
        ac for ac in g.f(r, "covers") or [] if g.get(ac) is not None and g.get(ac).status in LIVE_AC
    ]
    if pr_state == "merged" and all(covered_green(g, r, ac, sha) for ac in live_covers):
        return "DONE"
    handoff = g.bp.lifecycle.handoff if g.bp.lifecycle else {}
    if pr_state != "merged" and (
        _int(g.f(r, "ci_attempts")) >= handoff.get("ci_attempts", 3)
        or _int(g.f(r, "review_rounds")) >= handoff.get("review_rounds", 3)
    ):
        return "STUCK"
    for dep in g.f(r, "depends_on") or []:
        other = g.get(dep)
        if other is None or dep in seen:
            continue
        if task_status(other, g, args, seen) != "DONE":
            return "BLOCKED"
    for d in g.f(r, "implements") or []:
        decision = g.get(d)
        if decision is not None and decision.status == "OPEN" and g.f(decision, "level") == "MUST":
            return "BLOCKED"
    for gap in g.of_type("gap"):
        if gap.status == "OPEN" and r.ref in (g.f(gap, "blocks") or []) and g.f(gap, "level", "MUST") != "SHOULD":
            return "BLOCKED"
    if pr_state in ("open", "approved"):
        return "IN_REVIEW"
    if pr_state == "draft" or f"task:{g.initiative.id}:{r.ref}" in g.leases:
        return "IN_PROGRESS"
    return "READY"


# ── pass 6: the initiative ─────────────────────────────────────────────────


@rule("initiative_phase", ("UNASSIGNED", "DRAFT", "PLAN", "BUILD", "VALIDATE", "SHIP", "CLOSED"), order=6)
def initiative_phase(r: Record, g, args) -> str:
    if g.f(r, "closed_because"):
        return "CLOSED"
    if not g.assignments("dri") or not g.assignments("engg"):
        return "UNASSIGNED"
    if g.gate("GATE_DRAFT").status != "PASSED":
        return "DRAFT"
    tasks = g.of_type("task")
    live_acs = [a for a in g.of_type("acceptance_criterion") if a.status in LIVE_AC]
    covered = {ac for t in tasks for ac in g.f(t, "covers") or []}
    if not tasks or any(a.ref not in covered for a in live_acs):
        return "PLAN"
    if any(t.status != "DONE" for t in tasks):
        return "BUILD"
    if g.gate("GATE_VALIDATED").status != "PASSED":
        return "VALIDATE"
    return "SHIP"


class StatusRules:
    """Derives every record's status in place (record.status), pass by pass."""

    def __init__(self, blueprint: Blueprint):
        self.bp = blueprint

    def derive(self, graph) -> None:
        lifecycle = self.bp.lifecycle
        if lifecycle is None:
            return
        plan = []
        for record in graph.records:
            spec = lifecycle.status_rules.get(record.type)
            if spec is None or spec.rule not in STATUS_RULES:
                continue
            impl = STATUS_RULES[spec.rule]
            plan.append((impl.order, record, impl, spec.args))
        for order in sorted({p[0] for p in plan}):
            graph.invalidate()  # drift/gates read statuses: never reuse a result from an earlier pass
            for _, record, impl, args in [p for p in plan if p[0] == order]:
                record.status = impl.fn(record, graph, args)
        graph.invalidate()
        for record in graph.global_by_ref.values():
            spec = lifecycle.status_rules.get(record.type)
            if spec is not None and spec.rule in STATUS_RULES:
                record.status = STATUS_RULES[spec.rule].fn(record, graph, spec.args)
