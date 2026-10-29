"""The drift report: given approved baseline B-k, what is different in the spec now, and
for each difference, which human decision authorised it?

It rests only on what the write path already stores — the baseline's members and frozen
snapshot, every revision after it (actor, actor_kind, cause_refs), and the typed links
(`supersedes`, `because`, `source`, `blocks`, `implements`, `covers`). Nothing extra is
logged. The final PR reviewer reads this report (task-scoped) and nothing else; GATE_PR
needs `unexplained == []` and an engg approval pinned to `digest`.
"""

import difflib
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from app.blueprint.schemas.blueprint import Blueprint
from app.core.utils.time import iso
from app.initiatives.models.record import Record
from app.initiatives.models.record_revision import RecordRevision
from app.initiatives.services.record_graph import ref_num

DRAFT_SECTIONS = ("hld", "lld", "scope_in", "scope_out", "test_strategy")
SPEC_TYPES = ("draft", "decision", "acceptance_criterion")
TRACKED_TYPES = SPEC_TYPES + ("gap", "initiative")
LIVE_AC = ("PROPOSED", "APPROVED", "ADDED_AFTER_BASELINE")


def clip(value, limit: int = 160) -> str:
    if isinstance(value, list):
        value = "; ".join(str(v) for v in value)
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(f"- {v}" if isinstance(v, str) else json.dumps(v, sort_keys=True) for v in value)
    return str(value)


def spec_moved(bp: Blueprint, type_key: str, before: Optional[dict], after: dict) -> List[str]:
    """Material fields whose value differs — first fills and removals included (unlike the
    review queue's material_change, a first fill of `lld` after a baseline IS drift)."""
    before = before or {}
    out = []
    for name, f in bp.types[type_key].fields.items():
        if not f.material:
            continue
        old, new = before.get(name), after.get(name)
        if (old in (None, "", [])) and (new in (None, "", [])):
            continue
        if old == new:
            continue
        if isinstance(old, list) or isinstance(new, list):
            old_set = {json.dumps(v, sort_keys=True) for v in old or []}
            new_set = {json.dumps(v, sort_keys=True) for v in new or []}
            out.append(f"{name} (+{len(new_set - old_set)} −{len(old_set - new_set)})")
        elif not old:
            out.append(f"{name}: (empty) → “{clip(new)}”")
        elif not new:
            out.append(f"{name}: “{clip(old)}” → (removed)")
        else:
            out.append(f"{name}: “{clip(old)}” → “{clip(new)}”")
    return out


@dataclass
class Explanation:
    ref: Optional[str]
    ok: bool
    why: str


@dataclass
class DriftEntry:
    id: str
    kind: str  # see KINDS
    ref: str
    type: str
    rev: int
    at: str
    actor: str
    actor_kind: str
    summary: str
    what_moved: List[str] = field(default_factory=list)
    because: List[str] = field(default_factory=list)
    explained: bool = False
    explanation: List[Explanation] = field(default_factory=list)
    related: List[str] = field(default_factory=list)
    detail: Dict = field(default_factory=dict)
    in_scope: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


KINDS = {
    "gap_answered": "a human answered a gap",
    "decision_superseded": "a new decision replaced an approved one",
    "decision_added": "a decision taken after the baseline",
    "decision_changed": "an approved decision's verdict moved",
    "decision_confirmed": "a human confirmed a provisional verdict",
    "ac_added": "an acceptance criterion added after the baseline",
    "ac_changed": "an approved criterion's text moved",
    "ac_retired": "a human retired a criterion",
    "draft_edited": "a draft section moved",
    "requirement_repinned": "a human re-pinned the requirement snapshot",
}


@dataclass
class DriftReport:
    status: str  # NO_BASELINE | CLEAN | EXPLAINED | UNEXPLAINED
    initiative: str
    task: Optional[str] = None
    baseline_ref: Optional[str] = None
    baseline: Dict = field(default_factory=dict)
    scope_refs: List[str] = field(default_factory=list)
    entries: List[DriftEntry] = field(default_factory=list)
    pending_gaps: List[Dict] = field(default_factory=list)
    pending_decisions: List[Dict] = field(default_factory=list)
    spec_diff: Dict = field(default_factory=dict)
    approved_spec: Dict = field(default_factory=dict)
    current_spec: Dict = field(default_factory=dict)
    other_changes: int = 0
    digest: str = ""
    approvals: List[Dict] = field(default_factory=list)
    until: Optional[str] = None

    @property
    def unexplained(self) -> List[DriftEntry]:
        return [e for e in self.entries if not e.explained]

    def summary(self) -> dict:
        return {
            "changes": len(self.entries),
            "explained": len(self.entries) - len(self.unexplained),
            "unexplained": len(self.unexplained),
            "pending_gaps": len(self.pending_gaps),
            "pending_decisions": len(self.pending_decisions),
            "other_changes": self.other_changes,
        }

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "initiative": self.initiative,
            "task": self.task,
            "baseline": self.baseline or None,
            "until": self.until,
            "scope_refs": self.scope_refs,
            "summary": self.summary(),
            "digest": self.digest,
            "entries": [e.to_dict() for e in self.entries],
            "unexplained": [e.id for e in self.unexplained],
            "pending_gaps": self.pending_gaps,
            "pending_decisions": self.pending_decisions,
            "spec_diff": self.spec_diff,
            "approved_spec": self.approved_spec,
            "current_spec": self.current_spec,
            "approvals": self.approvals,
        }


class DriftService:
    def __init__(self, blueprint: Blueprint):
        self.bp = blueprint

    # ── public ───────────────────────────────────────────────────────────

    def report(self, g, task: Optional[str] = None, baseline: Optional[str] = None) -> DriftReport:
        slug = getattr(g.initiative, "slug", "")
        baselines = g.baselines()
        chosen = None
        if baseline:
            chosen = next((b for b in baselines if b.ref == baseline), None)
        elif baselines:
            chosen = baselines[-1]
        if chosen is None:
            return DriftReport(status="NO_BASELINE", initiative=slug, task=task)

        later = [b for b in baselines if ref_num(b.ref) > ref_num(chosen.ref)]
        cut = self._cut(g, chosen)
        until = self._cut(g, later[0]) if later else None
        members = g.baseline_members(chosen)
        snapshot = (chosen.fields or {}).get("snapshot") or {}

        entries, pending_gaps, pending_decisions = self._entries(g, members, snapshot, cut, until)
        scope = self._scope(g, task) if task else None
        if scope is not None:
            gap_scope = self._gap_scope(g, entries, scope)
            for e in entries:
                e.in_scope = e.ref in scope or e.ref in gap_scope or e.type == "initiative"
            pending_gaps = [p for p in pending_gaps if set(p["blocks"]) & scope]
            pending_decisions = [p for p in pending_decisions if p["ref"] in scope or set(p["supersedes"]) & scope]
        in_scope = [e for e in entries if e.in_scope]
        other = len(entries) - len(in_scope)

        current_state = self._state_at(g, later[0]) if later else self._state_now(g)
        approved_spec = self._project(snapshot, scope)
        current_spec = self._project(current_state, scope)
        spec_diff = self._spec_diff(snapshot, current_state, g, scope)

        approval_ref = ((chosen.fields or {}).get("approval") or [None])[0]
        info = {
            "ref": chosen.ref,
            "label": (chosen.fields or {}).get("label", ""),
            "status": chosen.status,
            "approval": approval_ref,
            "approved_by": (chosen.fields or {}).get("approved_by", ""),
            "draft_rev": (chosen.fields or {}).get("draft_rev", ""),
            "created_at": iso(chosen.created_at),
            "members": len(members),
        }
        report = DriftReport(
            status="CLEAN",
            initiative=slug,
            task=task,
            baseline_ref=chosen.ref,
            baseline=info,
            scope_refs=sorted(scope) if scope is not None else [],
            entries=in_scope,
            pending_gaps=pending_gaps,
            pending_decisions=pending_decisions,
            spec_diff=spec_diff,
            approved_spec=approved_spec,
            current_spec=current_spec,
            other_changes=other,
            until=later[0].ref if later else None,
        )
        if report.unexplained:
            report.status = "UNEXPLAINED"
        elif report.entries:
            report.status = "EXPLAINED"
        report.digest = self.digest(report)
        if task:
            report.approvals = [
                {
                    "ref": a.ref,
                    "by": a.created_by,
                    "status": a.status,
                    "at_sha": g.f(a, "at_sha"),
                    "drift_digest": g.f(a, "drift_digest"),
                    "matches_digest": g.f(a, "drift_digest") == report.digest,
                    "note": g.f(a, "note", ""),
                    "at": iso(a.created_at),
                }
                for a in g.of_type("approval")
                if task in (g.f(a, "target") or [])
            ]
        return report

    @staticmethod
    def digest(report: DriftReport) -> str:
        """What an engg approval pins: entries + spec diff, canonical JSON."""
        body = {
            "baseline": report.baseline_ref,
            "task": report.task,
            "entries": [
                {k: v for k, v in e.to_dict().items() if k not in ("in_scope",)} for e in report.entries
            ],
            "spec_diff": report.spec_diff,
        }
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

    # ── explanation ──────────────────────────────────────────────────────

    def cause_ok(self, g, ref: str, seen: Optional[Set[str]] = None) -> Explanation:
        """Is `ref` an acceptable reason for a spec change? Only if its chain ends in a HUMAN
        act: a gap a human answered; a decision ruled by a human, approved in a baseline (the
        DRI's act), or whose own `because` is explained; a finding a human raised, or one a
        human resolved as fixed / acknowledged. An agent's own finding explains nothing."""
        seen = set(seen or ()) | {ref}
        record = g.get(ref)
        if record is None:
            return Explanation(ref, False, f"{ref} does not exist")
        if record.type == "gap":
            if record.status == "ANSWERED" and self._set_by_human(g, record, "answer"):
                who = g.f(record, "answered_by") or "a human"
                return Explanation(ref, True, f"answered by {who}: “{clip(g.f(record, 'answer'), 120)}”")
            if record.status == "ANSWERED":
                return Explanation(ref, False, f"{ref}'s answer was not written by a human")
            return Explanation(ref, False, f"{ref} is {record.status} — only an answered gap explains a change")
        if record.type == "finding":
            if record.status == "REJECTED":
                return Explanation(ref, False, f"{ref} was rejected")
            what = f"finding ({g.f(record, 'severity')}): {clip(g.f(record, 'summary'), 120)}"
            revs = g.revisions(record.ref)
            if revs and revs[0].actor_kind == "human":
                return Explanation(ref, True, f"{what} — raised by {revs[0].actor}")
            resolver = self._setter(g, record, "resolution")
            if record.status in ("FIXED", "ACKNOWLEDGED") and resolver is not None and resolver.actor_kind == "human":
                return Explanation(ref, True, f"{what} — {record.status.lower()} by {resolver.actor}")
            return Explanation(
                ref, False, f"{ref} is an agent's finding with no human act behind it (a human must raise or resolve it)"
            )
        if record.type == "decision":
            ok_status = record.status == "DECIDED" or (
                record.status in ("PROVISIONAL", "SUPERSEDED") and g.f(record, "level") == "SHOULD"
            )
            if record.status == "SUPERSEDED":
                ok_status = bool(g.f(record, "verdict"))
            if not ok_status:
                return Explanation(ref, False, f"{ref} is {record.status} — not a ruling yet")
            grounded, why = self._grounded(g, record, seen)
            return Explanation(ref, grounded, why)
        return Explanation(ref, False, f"{ref} is a {record.type}; a change is explained by a gap, a decision or a finding")

    @staticmethod
    def _setter(g, record: Record, name: str) -> Optional[RecordRevision]:
        """The revision that gave `name` its current value (the earliest of the run)."""
        value = (record.fields or {}).get(name)
        setter = None
        for r in reversed(g.revisions(record.ref)):
            if (r.fields or {}).get(name) != value:
                break
            setter = r
        return setter

    def _set_by_human(self, g, record: Record, name: str) -> bool:
        setter = self._setter(g, record, name)
        return setter is not None and setter.actor_kind == "human"

    def _grounded(self, g, decision: Record, seen: Set[str]) -> Tuple[bool, str]:
        verdict = g.f(decision, "verdict")
        setter = self._setter(g, decision, "verdict")
        if setter is not None and setter.actor_kind == "human":
            return True, f"ruled by {setter.actor}: “{clip(verdict, 120)}”"
        for b in g.baselines():
            snap = ((b.fields or {}).get("snapshot") or {}).get(decision.ref)
            if snap and (snap.get("fields") or {}).get("verdict") == verdict:
                return True, f"approved in {b.ref}: “{clip(verdict, 120)}”"
        causes = list((setter.cause_refs if setter is not None else []) or []) or list(g.f(decision, "because") or [])
        causes = [c for c in causes if c not in seen]
        if not causes:
            return False, f"{decision.ref} was decided by an agent with no `because` (no human in the chain)"
        sub = [self.cause_ok(g, c, seen) for c in causes]
        if all(s.ok for s in sub):
            return True, f"“{clip(verdict, 100)}” because " + "; ".join(f"{s.ref} {s.why}" for s in sub)
        bad = [s for s in sub if not s.ok]
        return False, f"{decision.ref}'s own because is not explained (no human in the chain): " + "; ".join(s.why for s in bad)

    def _explain(self, g, rev: RecordRevision, extra: List[str] = ()) -> Tuple[bool, List[str], List[Explanation]]:
        because = sorted(set(rev.cause_refs or []) | set(extra or []))
        if rev.actor_kind == "human":
            return True, because, [Explanation(None, True, f"made by a human ({rev.actor})")]
        if not because:
            return False, because, [Explanation(None, False, "no `because` — an agent changed the spec without a gap answer, decision or finding")]
        explanation = [self.cause_ok(g, ref) for ref in because]
        return all(e.ok for e in explanation), because, explanation

    # ── entries ──────────────────────────────────────────────────────────

    @staticmethod
    def _cut(g, baseline: Record) -> int:
        revs = g.revisions(baseline.ref)
        return revs[0].id if revs else 0

    def _entries(self, g, members, snapshot, cut: int, until: Optional[int]):
        entries: List[DriftEntry] = []
        pending_gaps: List[Dict] = []
        pending_decisions: List[Dict] = []

        def post(r: RecordRevision) -> bool:
            return r.id > cut and (until is None or r.id < until)

        for record in g.records:
            if record.type not in TRACKED_TYPES:
                continue
            revs = g.revisions(record.ref)
            before = [r for r in revs if r.id <= cut]
            after = [r for r in revs if post(r)]
            if record.ref in members and record.ref in snapshot:
                prev = dict((snapshot[record.ref] or {}).get("fields") or {})
            elif before:
                prev = dict(before[-1].fields or {})
            else:
                prev = None
            for r in after:
                fields = dict(r.fields or {})
                entries += self._entries_for_revision(g, record, r, prev, fields, members)
                prev = fields
            # pending: gaps raised after the baseline still OPEN; decisions still OPEN
            if record.ref in members or not after:
                continue
            if record.type == "gap" and record.status == "OPEN":
                pending_gaps.append(
                    {
                        "ref": record.ref,
                        "question": g.f(record, "question", ""),
                        "kind": g.f(record, "kind", ""),
                        "domain": g.f(record, "domain", ""),
                        "blocks": list(g.f(record, "blocks") or []),
                        "asked_by": g.f(record, "asked_by", ""),
                        "at": iso(record.created_at),
                    }
                )
            if record.type == "decision" and record.status == "OPEN" and record.ref not in members:
                pending_decisions.append(
                    {
                        "ref": record.ref,
                        "question": g.f(record, "question", ""),
                        "level": g.f(record, "level", ""),
                        "supersedes": list(g.f(record, "supersedes") or []),
                        "at": iso(record.created_at),
                    }
                )
        entries.sort(key=lambda e: (e.at, ref_num(e.ref), e.rev))
        return entries, pending_gaps, pending_decisions

    def _entry(self, g, record, r, kind, summary, what_moved=(), extra_because=(), related=(), detail=None, explained=None):
        ok, because, explanation = self._explain(g, r, list(extra_because))
        if explained is not None:
            ok, explanation = explained
        return DriftEntry(
            id=f"{kind}:{record.ref}@{r.rev}",
            kind=kind,
            ref=record.ref,
            type=record.type,
            rev=r.rev,
            at=iso(r.created_at),
            actor=r.actor,
            actor_kind=r.actor_kind,
            summary=summary,
            what_moved=list(what_moved),
            because=because,
            explained=ok,
            explanation=explanation,
            related=list(related),
            detail=detail or {},
        )

    def _entries_for_revision(self, g, record, r, prev, fields, members) -> List[DriftEntry]:
        t = record.type
        prev_fields = prev or {}
        if t == "gap":
            if fields.get("answer") and not prev_fields.get("answer"):
                answer = fields.get("answer")
                detail = {
                    "question": fields.get("question", ""),
                    "answer": answer,
                    "choice": fields.get("choice", ""),
                    "answered_by": fields.get("answered_by", ""),
                    "assigned_to": fields.get("assigned_to", ""),
                    "assigned_role": fields.get("assigned_role", ""),
                    "answered_for": fields.get("answered_for", ""),
                    "blocks": list(fields.get("blocks") or []),
                    "resolution": g.f(record, "resolution", ""),
                    "kind": fields.get("kind", ""),
                    "proposed_change": fields.get("proposed_change", ""),
                }
                who = fields.get("answered_by") or r.actor
                assigned = fields.get("assigned_to") or ""
                by = f"{who} · assigned to {assigned}" if assigned and assigned != who else who
                return [
                    self._entry(
                        g,
                        record,
                        r,
                        "gap_answered",
                        f"{record.ref} answered by {by}: “{clip(answer, 140)}”",
                        related=detail["blocks"],
                        detail=detail,
                        explained=(True, [Explanation(None, True, f"a human answer ({who})")]),
                    )
                ]
            return []
        if t == "initiative":
            if fields.get("snapshot_hash") != prev_fields.get("snapshot_hash") and prev is not None:
                return [
                    self._entry(
                        g,
                        record,
                        r,
                        "requirement_repinned",
                        f"requirement re-pinned by {r.actor} (hash {str(fields.get('snapshot_hash'))[:8]})",
                        what_moved=["snapshot_hash"],
                    )
                ]
            return []
        if t == "decision":
            return self._decision_entries(g, record, r, prev, fields, members)
        if t == "acceptance_criterion":
            if prev is None:
                return [
                    self._entry(
                        g,
                        record,
                        r,
                        "ac_added",
                        f"{record.ref} added: “{clip(fields.get('text'), 160)}” (level: {fields.get('level')})",
                        related=list(fields.get("source") or []),
                        detail={"text": fields.get("text"), "level": fields.get("level"), "source": fields.get("source") or []},
                    )
                ]
            if fields.get("retired_because") and not prev_fields.get("retired_because"):
                return [
                    self._entry(
                        g,
                        record,
                        r,
                        "ac_retired",
                        f"{record.ref} retired: {clip(fields.get('retired_because'), 140)}",
                        detail={"text": fields.get("text"), "retired_because": fields.get("retired_because")},
                    )
                ]
            moved = spec_moved(self.bp, t, prev_fields, fields)
            moved = [m for m in moved if not m.startswith("retired_because")]
            if moved:
                return [
                    self._entry(
                        g,
                        record,
                        r,
                        "ac_changed",
                        f"{record.ref} changed: {'; '.join(moved)}",
                        what_moved=moved,
                        detail={"old": prev_fields.get("text"), "new": fields.get("text")},
                    )
                ]
            return []
        if t == "draft":
            moved = spec_moved(self.bp, t, prev_fields, fields)
            if moved:
                sections = [m.split(":")[0].split(" ")[0] for m in moved]
                return [
                    self._entry(
                        g,
                        record,
                        r,
                        "draft_edited",
                        f"draft {', '.join(sections)} edited" + (f" — {r.note}" if r.note else ""),
                        what_moved=moved,
                        detail={"sections": sections},
                    )
                ]
        return []

    def _decision_entries(self, g, record, r, prev, fields, members) -> List[DriftEntry]:
        prev_fields = prev or {}
        verdict, old_verdict = fields.get("verdict"), prev_fields.get("verdict")
        newly_ruled = verdict and not old_verdict
        if prev is None or (newly_ruled and record.ref not in members):
            if not verdict:
                return []  # an open question, not a spec change yet (listed as pending)
            superseded = list(fields.get("supersedes") or [])
            if superseded:
                out = []
                for old_ref in superseded:
                    old = g.get(old_ref)
                    old_v = g.f(old, "verdict", "") if old is not None else ""
                    # the gaps that blocked the old decision carry the human answer behind this one
                    gap_causes = [
                        gp.ref
                        for gp in g.of_type("gap")
                        if old_ref in (g.f(gp, "blocks") or []) and gp.status == "ANSWERED"
                    ]
                    out.append(
                        self._entry(
                            g,
                            record,
                            r,
                            "decision_superseded",
                            f"{record.ref} supersedes {old_ref}: verdict “{clip(old_v, 90)}” → “{clip(verdict, 90)}”",
                            what_moved=[f"verdict: “{clip(old_v)}” → “{clip(verdict)}”"],
                            related=[old_ref] + gap_causes,
                            detail={
                                "superseded": old_ref,
                                "old_verdict": old_v,
                                "new_verdict": verdict,
                                "question": fields.get("question", ""),
                                "level": fields.get("level", ""),
                                "rationale": fields.get("rationale", ""),
                                "related_gaps": gap_causes,
                            },
                        )
                    )
                return out
            return [
                self._entry(
                    g,
                    record,
                    r,
                    "decision_added",
                    f"{record.ref} decided after the baseline: “{clip(fields.get('question'), 80)}” → “{clip(verdict, 90)}”",
                    what_moved=[f"verdict: (new) → “{clip(verdict)}”"],
                    detail={"question": fields.get("question", ""), "verdict": verdict, "level": fields.get("level", "")},
                )
            ]
        was_prov = str(prev_fields.get("provisional", "")).lower() == "yes"
        now_prov = str(fields.get("provisional", "")).lower() == "yes"
        moved = spec_moved(self.bp, "decision", prev_fields, fields)
        if was_prov and not now_prov and not moved and r.actor_kind == "human":
            return [
                self._entry(
                    g,
                    record,
                    r,
                    "decision_confirmed",
                    f"{record.ref} provisional verdict confirmed by {r.actor}: “{clip(verdict, 120)}”",
                    detail={"verdict": verdict},
                )
            ]
        if moved:
            return [
                self._entry(
                    g,
                    record,
                    r,
                    "decision_changed",
                    f"{record.ref} verdict moved: “{clip(old_verdict, 90)}” → “{clip(verdict, 90)}”",
                    what_moved=moved,
                    detail={"old_verdict": old_verdict, "new_verdict": verdict},
                )
            ]
        return []

    # ── task scope ───────────────────────────────────────────────────────

    def _scope(self, g, task: str) -> Set[str]:
        """task.implements ∪ task.covers, expanded through supersede chains, the decisions
        the covered ACs are sourced from, the ACs sourced from / caused by in-scope
        decisions, and the draft when it cites an in-scope decision."""
        scope: Set[str] = {task}
        scope |= set(g.f(task, "implements") or [])
        covers = set(g.f(task, "covers") or [])
        scope |= covers
        for ac in covers:
            scope |= {s for s in g.f(ac, "source") or [] if g.bp.type_of_ref(s) == "decision"}
        changed = True
        while changed:
            changed = False
            for ref in list(scope):
                if g.bp.type_of_ref(ref) != "decision":
                    continue
                for other in set(g.in_(ref, "supersedes")) | set(g.out(ref, "supersedes")):
                    if other not in scope:
                        scope.add(other)
                        changed = True
        decisions = {r for r in scope if g.bp.type_of_ref(r) == "decision"}
        for ac in g.of_type("acceptance_criterion"):
            linked = set(g.f(ac, "source") or []) | set(g.f(ac, "because") or [])
            if linked & decisions:
                scope.add(ac.ref)
        draft = g.get("draft")
        if draft is not None and (
            set(g.out("draft", "mentions")) & decisions or set(g.f(draft, "decisions") or []) & decisions
        ):
            scope.add("draft")
        return scope

    @staticmethod
    def _gap_scope(g, entries: List[DriftEntry], scope: Set[str]) -> Set[str]:
        out = set()
        for gap in g.of_type("gap"):
            if set(g.f(gap, "blocks") or []) & scope:
                out.add(gap.ref)
        for e in entries:
            if e.ref in scope:
                out |= {b for b in e.because if g.bp.type_of_ref(b) == "gap"}
                out |= {b for b in e.related if g.bp.type_of_ref(b) == "gap"}
        return out

    # ── spec projection and diff ─────────────────────────────────────────

    @staticmethod
    def _state_now(g) -> Dict[str, dict]:
        return {
            r.ref: {"type": r.type, "title": r.title, "status": r.status, "rev": r.head_rev, "fields": dict(r.fields or {})}
            for r in g.records
            if r.type in SPEC_TYPES or r.type == "gap"
        }

    @staticmethod
    def _state_at(g, baseline: Record) -> Dict[str, dict]:
        return dict((baseline.fields or {}).get("snapshot") or {})

    @staticmethod
    def _project(state: Dict[str, dict], scope: Optional[Set[str]]) -> dict:
        def keep(ref):
            return scope is None or ref in scope

        draft = state.get("draft") or {}
        sections = {k: (draft.get("fields") or {}).get(k) for k in ("problem",) + DRAFT_SECTIONS}
        decisions = [
            {
                "ref": ref,
                "title": s.get("title", ""),
                "question": (s.get("fields") or {}).get("question", ""),
                "verdict": (s.get("fields") or {}).get("verdict", ""),
                "level": (s.get("fields") or {}).get("level", ""),
                "status": s.get("status", ""),
            }
            for ref, s in sorted(state.items(), key=lambda kv: ref_num(kv[0]))
            if s.get("type") == "decision" and s.get("status") in ("DECIDED", "PROVISIONAL") and keep(ref)
        ]
        criteria = [
            {
                "ref": ref,
                "text": (s.get("fields") or {}).get("text", ""),
                "level": (s.get("fields") or {}).get("level", ""),
                "manual": (s.get("fields") or {}).get("manual", ""),
                "status": s.get("status", ""),
            }
            for ref, s in sorted(state.items(), key=lambda kv: ref_num(kv[0]))
            if s.get("type") == "acceptance_criterion" and s.get("status") in LIVE_AC and keep(ref)
        ]
        return {
            "draft": sections if (scope is None or "draft" in scope) else {},
            "decisions": decisions,
            "criteria": criteria,
        }

    def _spec_diff(self, snapshot: Dict[str, dict], current: Dict[str, dict], g, scope: Optional[Set[str]]) -> dict:
        def keep(ref):
            return scope is None or ref in scope

        draft_diff = {}
        if keep("draft"):
            old_f = ((snapshot.get("draft") or {}).get("fields")) or {}
            new_f = ((current.get("draft") or {}).get("fields")) or {}
            for section in DRAFT_SECTIONS:
                old, new = _as_text(old_f.get(section)), _as_text(new_f.get(section))
                if old == new:
                    continue
                lines = list(
                    difflib.unified_diff(
                        old.splitlines(), new.splitlines(), f"baseline/{section}", f"current/{section}", n=2, lineterm=""
                    )
                )
                draft_diff[section] = {
                    "added": sum(1 for x in lines if x.startswith("+") and not x.startswith("+++")),
                    "removed": sum(1 for x in lines if x.startswith("-") and not x.startswith("---")),
                    "diff": "\n".join(lines),
                }

        def decs(state):
            return {r: s for r, s in state.items() if s.get("type") == "decision"}

        old_d, new_d = decs(snapshot), decs(current)
        superseded, changed, added, unchanged = [], [], [], 0
        for ref, s in sorted(old_d.items(), key=lambda kv: ref_num(kv[0])):
            if not keep(ref):
                continue
            now = new_d.get(ref) or {}
            old_v = (s.get("fields") or {}).get("verdict", "")
            if now.get("status") == "SUPERSEDED":
                by = self._superseded_by(g, ref)
                new_v = ((new_d.get(by) or {}).get("fields") or {}).get("verdict", "") if by else ""
                superseded.append({"old": ref, "new": by, "old_verdict": old_v, "new_verdict": new_v})
            elif (now.get("fields") or {}).get("verdict", "") != old_v:
                changed.append({"ref": ref, "old_verdict": old_v, "new_verdict": (now.get("fields") or {}).get("verdict", "")})
            else:
                unchanged += 1
        replacing = {x["new"] for x in superseded}
        for ref, s in sorted(new_d.items(), key=lambda kv: ref_num(kv[0])):
            if ref in old_d or not keep(ref) or ref in replacing:
                continue
            if s.get("status") in ("DECIDED", "PROVISIONAL"):
                added.append({"ref": ref, "verdict": (s.get("fields") or {}).get("verdict", ""), "status": s.get("status")})

        def acs(state):
            return {r: s for r, s in state.items() if s.get("type") == "acceptance_criterion"}

        old_a, new_a = acs(snapshot), acs(current)
        a_added, a_retired, a_changed, a_unchanged = [], [], [], 0
        for ref, s in sorted(new_a.items(), key=lambda kv: ref_num(kv[0])):
            if not keep(ref):
                continue
            f_new = s.get("fields") or {}
            if ref not in old_a:
                if s.get("status") != "RETIRED":
                    a_added.append({"ref": ref, "text": f_new.get("text", ""), "level": f_new.get("level", ""), "because": f_new.get("because") or []})
                continue
            f_old = old_a[ref].get("fields") or {}
            if s.get("status") == "RETIRED":
                a_retired.append({"ref": ref, "text": f_new.get("text", ""), "retired_because": f_new.get("retired_because", "")})
            elif f_old.get("text") != f_new.get("text"):
                a_changed.append({"ref": ref, "old": f_old.get("text", ""), "new": f_new.get("text", "")})
            else:
                a_unchanged += 1
        return {
            "draft": draft_diff,
            "decisions": {"added": added, "superseded": superseded, "changed": changed, "unchanged": unchanged},
            "criteria": {"added": a_added, "retired": a_retired, "changed": a_changed, "unchanged": a_unchanged},
        }

    @staticmethod
    def _superseded_by(g, ref: str) -> Optional[str]:
        """The newest decision at the end of the supersede chain from `ref`."""
        seen, current = {ref}, ref
        while True:
            newer = [r for r in g.in_(current, "supersedes") if r not in seen]
            if not newer:
                return current if current != ref else None
            current = max(newer, key=ref_num)
            seen.add(current)
