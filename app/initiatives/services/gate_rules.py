"""Gates, evaluated on read and never stored. Each rule name here is a rule in
blueprint/lifecycle.yaml `gates.*.all_of` (make check pairs them). A rule returns whether
it passes and the refs that fail it, so the UI and the agent see exactly what blocks."""

from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

from app.blueprint.schemas.blueprint import Blueprint
from app.initiatives.services.status_rules import LIVE_AC

SPEC_TYPES = ("draft", "decision", "acceptance_criterion")


@dataclass
class RuleResult:
    name: str
    passed: bool
    failing: List[str] = field(default_factory=list)
    detail: str = ""
    args: Dict = field(default_factory=dict)


@dataclass
class GateResult:
    gate: str
    scope: str
    target: Optional[str]
    status: str  # PASSED | BLOCKED
    human_role: Optional[str]
    text: str
    rules: List[RuleResult]
    note: str = ""

    @property
    def failing_rules(self) -> List[str]:
        return [r.name for r in self.rules if not r.passed]

    def to_dict(self) -> dict:
        out = asdict(self)
        out["failing_rules"] = self.failing_rules
        return out


@dataclass
class Ctx:
    gate: str
    task: Optional[str]  # the task a task-scoped gate is evaluated for
    scope_task: Optional[str]  # narrows an initiative gate to one task's ACs (deploy_guard)
    sha: Optional[str] = None  # the commit being deployed (deploy_guard): evidence must be at it


GATE_RULES: Dict[str, Callable] = {}


def gate_rule(name: str):
    def register(fn):
        GATE_RULES[name] = fn
        return fn

    return register


def _live_acs(g, ctx: Ctx):
    acs = [a for a in g.of_type("acceptance_criterion") if a.status in LIVE_AC]
    if ctx.scope_task:
        covered = set(g.f(ctx.scope_task, "covers") or [])
        acs = [a for a in acs if a.ref in covered]
    return acs


def _task_scope_refs(g, task_ref: str) -> set:
    refs = {task_ref} | set(g.f(task_ref, "covers") or []) | set(g.f(task_ref, "implements") or [])
    return refs


# ── GATE_DRAFT ──────────────────────────────────────────────────────────────


@gate_rule("no_open_decision_in_draft_scope")
def no_open_decision_in_draft_scope(g, ctx, **_):
    failing = [
        d.ref
        for d in g.of_type("decision")
        if d.status == "OPEN" or (d.status == "PROVISIONAL" and g.f(d, "level") == "MUST")
    ]
    return RuleResult("", not failing, failing, "decisions still OPEN (a PROVISIONAL SHOULD passes)" if failing else "")


@gate_rule("no_open_gap_blocking_draft")
def no_open_gap_blocking_draft(g, ctx, **_):
    failing = []
    for gap in g.of_type("gap"):
        if gap.status != "OPEN" or g.f(gap, "level", "MUST") == "SHOULD":
            continue
        blocked = [g.get(b) for b in g.f(gap, "blocks") or []]
        if any(b is not None and b.type in SPEC_TYPES for b in blocked):
            failing.append(gap.ref)
    return RuleResult("", not failing, failing, "OPEN gaps block the spec" if failing else "")


@gate_rule("no_open_review_items_on_spec")
def no_open_review_items_on_spec(g, ctx, **_):
    items = getattr(g, "open_review_items", []) or []
    failing = sorted(
        {i.target_ref for i in items if g.get(i.target_ref) is not None and g.get(i.target_ref).type in SPEC_TYPES}
    )
    return RuleResult("", not failing, failing, "spec records are up for review" if failing else "")


def catalog_state(g, phase: str) -> List[dict]:
    """Every catalog item of a phase with its disposition (derived items answered here)."""
    lifecycle = g.bp.lifecycle
    rows = {row.get("item"): row for row in g.f("initiative", "catalog") or []}
    out = []
    for item in lifecycle.catalogs.get(phase, []):
        if item.derived:
            ok = _derived_catalog(g, item.item)
            out.append(
                {
                    "item": item.item,
                    "phase": phase,
                    "text": item.text,
                    "derived": True,
                    "disposition": "addressed" if ok else "UNASSESSED",
                    "note": "",
                    "refs": "",
                }
            )
        else:
            row = rows.get(item.item) or {}
            out.append(
                {
                    "item": item.item,
                    "phase": phase,
                    "text": item.text,
                    "derived": False,
                    "disposition": row.get("disposition") or "UNASSESSED",
                    "note": row.get("note", ""),
                    "refs": row.get("refs", ""),
                }
            )
    return out


def _derived_catalog(g, item: str) -> bool:
    if item == "dri_assigned":
        return bool(g.assignments("dri"))
    if item == "engg_assigned":
        return bool(g.assignments("engg"))
    if item == "requirement_snapshotted":
        return bool(getattr(g.initiative, "snapshot_hash", ""))
    if item == "every_ac_covered_by_a_task":
        covered = {ac for t in g.of_type("task") for ac in g.f(t, "covers") or []}
        acs = [a for a in g.of_type("acceptance_criterion") if a.status in LIVE_AC]
        return bool(g.of_type("task")) and all(a.ref in covered for a in acs)
    if item == "every_task_has_template":
        return bool(g.of_type("task")) and all(g.f(t, "template") for t in g.of_type("task"))
    return False


@gate_rule("catalog_addressed")
def catalog_addressed(g, ctx, phase="draft", **_):
    failing = [row["item"] for row in catalog_state(g, phase) if row["disposition"] == "UNASSESSED"]
    return RuleResult("", not failing, failing, f"{phase} catalog items not addressed" if failing else "")


@gate_rule("every_ac_has_source")
def every_ac_has_source(g, ctx, **_):
    failing = [a.ref for a in _live_acs(g, ctx) if not g.f(a, "source")]
    return RuleResult("", not failing, failing)


@gate_rule("every_decision_covered_by_an_ac")
def every_decision_covered_by_an_ac(g, ctx, **_):
    sourced = {
        s
        for a in g.of_type("acceptance_criterion")
        if a.status in LIVE_AC
        for s in g.f(a, "source") or []
    }
    failing = [d.ref for d in g.of_type("decision") if d.status != "SUPERSEDED" and d.ref not in sourced]
    return RuleResult("", not failing, failing, "decisions no AC is sourced from" if failing else "")


@gate_rule("approval_by_role")
def approval_by_role(g, ctx, role="dri", target="draft", **_):
    want = ctx.task if target == "task" else ("draft" if target == "draft" else None)
    current = [
        a.ref
        for a in g.of_type("approval")
        if g.f(a, "role") == role
        and a.status == "CURRENT"
        and (want is None or want in (g.f(a, "target") or []))
    ]
    stale = [
        a.ref
        for a in g.of_type("approval")
        if g.f(a, "role") == role and a.status == "STALE" and (want is None or want in (g.f(a, "target") or []))
    ]
    if current:
        return RuleResult("", True, [], f"approved: {', '.join(current)}")
    detail = f"no CURRENT {role} approval of {want or target}"
    if stale:
        detail += f" (stale: {', '.join(stale)})"
    return RuleResult("", False, stale, detail)


# ── GATE_PR ─────────────────────────────────────────────────────────────────


@gate_rule("pr_state_in")
def pr_state_in(g, ctx, states=("open", "approved"), **_):
    state = g.f(ctx.task, "pr_state") or "none"
    ok = state in states
    return RuleResult("", ok, [] if ok else [ctx.task], f"pr_state is {state}; needs {' | '.join(states)}")


@gate_rule("no_blocker_finding_open_at_sha")
def no_blocker_finding_open_at_sha(g, ctx, **_):
    sha = g.f(ctx.task, "pr_sha") or ""
    scope = _task_scope_refs(g, ctx.task)
    failing = [
        f.ref
        for f in g.of_type("finding")
        if f.status == "OPEN"
        and g.f(f, "severity") == "blocker"
        and set(g.f(f, "target") or []) & scope
        and (not g.f(f, "at_sha") or g.f(f, "at_sha") == sha)
    ]
    return RuleResult("", not failing, failing)


def runs_at(g, shas) -> list:
    """Test runs whose at_sha is one of `shas` — evidence counts only for the commit it ran on."""
    shas = {s for s in shas if s}
    return [run for run in g.of_type("test_run") if g.f(run, "at_sha") in shas]


@gate_rule("every_covered_ac_has_a_test")
def every_covered_ac_has_a_test(g, ctx, **_):
    sha = g.f(ctx.task, "pr_sha")
    tested = {row.get("ac") for run in runs_at(g, [sha]) for row in g.f(run, "covers") or []}
    covers = [ac for ac in g.f(ctx.task, "covers") or [] if g.get(ac) is not None and g.get(ac).status in LIVE_AC]
    failing = [ac for ac in covers if ac not in tested and g.f(ac, "manual") != "yes"]
    return RuleResult("", not failing, failing, "covered ACs with no test run row" if failing else "")


@gate_rule("drift_explained_for_task")
def drift_explained_for_task(g, ctx, **_):
    report = g.drift(task=ctx.task)
    if report.status == "NO_BASELINE":
        return RuleResult("", False, [], "no approved baseline yet (GATE_DRAFT)")
    failing = [e.ref for e in report.unexplained]
    detail = (
        f"{len(report.entries)} change(s) since {report.baseline_ref}, {len(failing)} unexplained"
    )
    return RuleResult("", not failing, failing, detail)


@gate_rule("no_provisional_decision_implemented_at_must_level")
def no_provisional_decision_implemented_at_must_level(g, ctx, **_):
    failing = [
        d
        for d in g.f(ctx.task, "implements") or []
        if g.get(d) is not None and g.get(d).status in ("PROVISIONAL", "OPEN") and g.f(d, "level") == "MUST"
    ]
    return RuleResult("", not failing, failing)


# ── GATE_VALIDATED ──────────────────────────────────────────────────────────


def evidence_shas(g, ctx: Ctx, ac_ref: str) -> set:
    """The commits whose runs may prove `ac_ref`: the deploying sha (deploy_guard), else the
    scoped task's PR head, else the PR head of every task covering the AC."""
    if ctx.sha:
        return {ctx.sha}
    if ctx.scope_task:
        return {g.f(ctx.scope_task, "pr_sha")} - {None, ""}
    return {g.f(t, "pr_sha") for t in g.of_type("task") if ac_ref in (g.f(t, "covers") or [])} - {None, ""}


def latest_run_result(g, ac_ref: str, shas: Optional[set] = None) -> Optional[str]:
    from app.initiatives.services.record_graph import ref_num

    best = None
    runs = g.of_type("test_run") if shas is None else runs_at(g, shas)
    for run in runs:
        for row in g.f(run, "covers") or []:
            if row.get("ac") == ac_ref:
                key = (g.f(run, "run_on") or "", ref_num(run.ref))
                result = row.get("result") or g.f(run, "result")
                if best is None or key > best[0]:
                    best = (key, result)
    return best[1] if best else None


@gate_rule("every_ac_green")
def every_ac_green(g, ctx, **_):
    if not _live_acs(g, ctx):
        return RuleResult("", False, [], "no live acceptance criteria yet")
    failing = [
        a.ref
        for a in _live_acs(g, ctx)
        if g.f(a, "manual") != "yes" and latest_run_result(g, a.ref, evidence_shas(g, ctx, a.ref)) != "GREEN"
    ]
    return RuleResult("", not failing, failing, "ACs whose latest run at the PR head / deploying sha is not GREEN" if failing else "")


@gate_rule("manual_acs_signed_by")
def manual_acs_signed_by(g, ctx, role="qa", **_):
    failing = [a.ref for a in _live_acs(g, ctx) if g.f(a, "manual") == "yes" and not g.f(a, "signed_by")]
    return RuleResult("", not failing, failing, f"manual ACs not signed by {role}" if failing else "")


@gate_rule("no_blocker_finding_open")
def no_blocker_finding_open(g, ctx, **_):
    scope = _task_scope_refs(g, ctx.scope_task) if ctx.scope_task else None
    failing = [
        f.ref
        for f in g.of_type("finding")
        if f.status == "OPEN"
        and g.f(f, "severity") == "blocker"
        and (scope is None or set(g.f(f, "target") or []) & scope)
    ]
    return RuleResult("", not failing, failing)


class GateRules:
    def __init__(self, blueprint: Blueprint):
        self.bp = blueprint

    def evaluate(self, g, gate_key: str, task: Optional[str] = None, scope_task: Optional[str] = None, sha: Optional[str] = None) -> GateResult:
        gate = self.bp.lifecycle.gates[gate_key]
        ctx = Ctx(gate_key, task, scope_task, sha)
        results = []
        for ref in gate.rules:
            result = GATE_RULES[ref.name](g, ctx, **ref.args)
            result.name, result.args = ref.name, dict(ref.args)
            results.append(result)
        note = ""
        if gate.on_pass == "create_baseline":
            # Preconditions are checked when the human approves; once approved (baseline B-n)
            # the gate holds while the approval is CURRENT (draft not REOPENED).
            approval = next(r for r in results if r.name == "approval_by_role")
            passed = approval.passed
            if passed and not all(r.passed for r in results):
                note = "approved; preconditions that fail now are mid-build work, not a reopened draft"
        else:
            passed = all(r.passed for r in results)
        return GateResult(
            gate=gate_key,
            scope=gate.scope,
            target=task,
            status="PASSED" if passed else "BLOCKED",
            human_role=gate.human,
            text=gate.text,
            rules=results,
            note=note,
        )

    def preconditions(self, g, gate_key: str, task: Optional[str] = None) -> List[RuleResult]:
        """The rules other than the human approval — what must hold before a human may approve."""
        result = self.evaluate(g, gate_key, task=task)
        return [r for r in result.rules if r.name != "approval_by_role" and not r.passed]
