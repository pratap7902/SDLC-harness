"""All records and typed links of one initiative, loaded once, with the questions every
view asks of them. Statuses are re-derived on load (StatusRules) — the `status` column is
only a cache the write path fills."""

import hashlib
import re
from collections import defaultdict
from typing import Callable, Dict, Iterable, List, Optional, Set

from app.blueprint.schemas.blueprint import Blueprint
from app.initiatives.models.initiative import Initiative
from app.initiatives.models.record import Record
from app.initiatives.models.record_link import RecordLink
from app.initiatives.models.record_revision import RecordRevision

REF_NUM_RE = re.compile(r"-(\d+)$")


def ref_num(ref: str) -> int:
    m = REF_NUM_RE.search(ref or "")
    return int(m.group(1)) if m else 0


def yes(value) -> bool:
    return str(value or "").strip().lower() == "yes"


class RecordGraph:
    def __init__(
        self,
        blueprint: Blueprint,
        initiative: Initiative,
        records: List[Record],
        links: List[RecordLink],
        revisions_loader: Optional[Callable[[], List[RecordRevision]]] = None,
        leases: Iterable[str] = (),
        global_records: Iterable[Record] = (),
        review_items: Iterable = (),
        derive: bool = True,
    ):
        self.bp = blueprint
        self.initiative = initiative
        self.records = [r for r in records if r.type in blueprint.types]
        self.by_ref: Dict[str, Record] = {r.ref: r for r in self.records}
        self.global_by_ref: Dict[str, Record] = {r.ref: r for r in global_records}
        self.leases: Set[str] = set(leases)
        # open ReviewItem rows of this initiative (gate rule no_open_review_items_on_spec)
        self.open_review_items = list(review_items)
        self._revisions_loader = revisions_loader
        self._revisions: Optional[Dict[str, List[RecordRevision]]] = None
        self._outs: Dict[str, List[tuple]] = defaultdict(list)
        self._ins: Dict[str, List[tuple]] = defaultdict(list)
        for link in links:
            self._outs[link.from_ref].append((link.kind, link.to_ref))
            self._ins[link.to_ref].append((link.kind, link.from_ref))
        self._drift_cache: Dict[tuple, object] = {}
        self._gate_cache: Dict[tuple, object] = {}
        if derive:
            from app.initiatives.services.status_rules import StatusRules

            StatusRules(blueprint).derive(self)

    # ── lookups ──────────────────────────────────────────────────────────

    def get(self, ref: str) -> Optional[Record]:
        return self.by_ref.get(ref) or self.global_by_ref.get(ref)

    def of_type(self, type_key: str) -> List[Record]:
        return sorted(
            (r for r in self.records if r.type == type_key), key=lambda r: (ref_num(r.ref), r.ref)
        )

    def f(self, ref_or_record, name: str, default=None):
        record = self.get(ref_or_record) if isinstance(ref_or_record, str) else ref_or_record
        if record is None:
            return default
        value = (record.fields or {}).get(name)
        return default if value is None else value

    def out(self, ref: str, kind: Optional[str] = None) -> List[str]:
        return sorted({to for k, to in self._outs.get(ref, ()) if kind is None or k == kind})

    def in_(self, ref: str, kind: Optional[str] = None) -> List[str]:
        return sorted({src for k, src in self._ins.get(ref, ()) if kind is None or k == kind})

    def edges_out(self, ref: str) -> List[dict]:
        return [{"kind": k, "to": to} for k, to in sorted(self._outs.get(ref, ()))]

    def edges_in(self, ref: str) -> List[dict]:
        return [{"kind": k, "from": src} for k, src in sorted(self._ins.get(ref, ()))]

    def linked(self, ref: str) -> Set[str]:
        """Both directions, any kind — for propagation and mentions."""
        return {to for _, to in self._outs.get(ref, ())} | {
            src for _, src in self._ins.get(ref, ())
        }

    # ── revisions ────────────────────────────────────────────────────────

    def revisions(self, ref: str) -> List[RecordRevision]:
        """Every revision of a record, oldest first."""
        if self._revisions is None:
            self._revisions = defaultdict(list)
            for rev in (self._revisions_loader() if self._revisions_loader else []):
                self._revisions[rev.ref].append(rev)
            for revs in self._revisions.values():
                revs.sort(key=lambda r: (r.rev, r.id or 0))
        return self._revisions.get(ref, [])

    # ── baselines / assignments ──────────────────────────────────────────

    def baselines(self) -> List[Record]:
        return self.of_type("baseline")

    def current_baseline(self) -> Optional[Record]:
        baselines = self.baselines()
        return baselines[-1] if baselines else None

    def baseline_members(self, baseline: Optional[Record] = None) -> Dict[str, dict]:
        baseline = baseline or self.current_baseline()
        if baseline is None:
            return {}
        return {row["ref"]: row for row in (baseline.fields or {}).get("members") or []}

    def assignments(self, role: Optional[str] = None, scope: Optional[str] = None) -> List[Record]:
        """ACTIVE assignments, newest first, optionally for a role and a scope ref."""
        out = [
            a
            for a in self.of_type("assignment")
            if a.status == "ACTIVE"
            and (role is None or self.f(a, "role") == role)
            and (scope is None or scope in (self.f(a, "scope") or []))
        ]
        return sorted(out, key=lambda a: -ref_num(a.ref))

    def person_for(self, role: str, task_ref: Optional[str] = None) -> Optional[str]:
        if task_ref:
            scoped = self.assignments(role, task_ref)
            if scoped:
                return self.f(scoped[0], "person")
        found = self.assignments(role, "initiative")
        return self.f(found[0], "person") if found else None

    def roles_of(self, person: str, task_ref: Optional[str] = None) -> Set[str]:
        return {
            self.f(a, "role")
            for a in self.assignments()
            if self.f(a, "person") == person
            and (
                "initiative" in (self.f(a, "scope") or [])
                or (task_ref and task_ref in (self.f(a, "scope") or []))
            )
        }

    # ── drift / gates (cached per graph) ─────────────────────────────────

    def drift(self, task: Optional[str] = None, baseline: Optional[str] = None):
        key = (task, baseline)
        if key not in self._drift_cache:
            from app.initiatives.services.drift_service import DriftService

            self._drift_cache[key] = DriftService(self.bp).report(self, task=task, baseline=baseline)
        return self._drift_cache[key]

    def gate(self, gate: str, task: Optional[str] = None, scope_task: Optional[str] = None, sha: Optional[str] = None):
        key = (gate, task, scope_task, sha)
        if key not in self._gate_cache:
            from app.initiatives.services.gate_rules import GateRules

            self._gate_cache[key] = GateRules(self.bp).evaluate(self, gate, task=task, scope_task=scope_task, sha=sha)
        return self._gate_cache[key]

    def invalidate(self) -> None:
        self._drift_cache.clear()
        self._gate_cache.clear()

    # ── narratives (fingerprint staleness, as in CIS) ────────────────────

    def scope(self, record: Record) -> List[Record]:
        """The records a narrative on `record` summarises."""
        if record.type in ("initiative", "draft"):
            return [r for r in self.records if self.bp.types[r.type].narrated and r.ref != record.ref]
        return [self.by_ref[n] for n in sorted(self.linked(record.ref)) if n in self.by_ref]

    def facts(self, record: Record) -> Dict[str, str]:
        return {r.ref: r.status for r in self.scope(record)}

    def fingerprint(self, record: Record) -> str:
        facts = sorted(f"{ref}={status}" for ref, status in self.facts(record).items())
        return hashlib.sha1("\n".join(facts).encode()).hexdigest()[:12]

    def stamp(self, record: Record) -> dict:
        return {"fp": self.fingerprint(record), "facts": self.facts(record)}

    def stale_slots(self, record: Record) -> List[str]:
        spec = self.bp.types[record.type]
        written = (record.meta or {}).get("narratives", {})
        stale, current = [], None
        for name, f in spec.fields.items():
            if f.type != "narrative" or not (record.fields or {}).get(name):
                continue
            current = current or self.fingerprint(record)
            if written.get(name, {}).get("fp") != current:
                stale.append(name)
        return stale

    def stale_changes(self, record: Record, slot: str) -> List[str]:
        written = (record.meta or {}).get("narratives", {}).get(slot, {}).get("facts")
        if written is None:
            return []
        now = self.facts(record)
        out = [f"{ref} added [{now[ref]}]" for ref in now if ref not in written]
        out += [f"{ref} removed" for ref in written if ref not in now]
        out += [f"{ref} {written[ref]} → {now[ref]}" for ref in now if ref in written and written[ref] != now[ref]]
        return out

    def all_stale(self) -> List[str]:
        return [f"{r.ref}.{slot}" for r in self.records for slot in self.stale_slots(r)]

    def stale_notes(self) -> Dict[str, str]:
        return {
            f"{r.ref}.{slot}": "; ".join(self.stale_changes(r, slot)[:6])
            for r in self.records
            for slot in self.stale_slots(r)
        }
