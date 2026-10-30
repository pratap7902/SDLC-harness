"""The single write path. REST, MCP, the intake and the human endpoints all go through
`RecordService.write`, so every record has passed the blueprint, carries who wrote it (and
as what: human | agent | system) and why, and the drift report can be a pure query.

write(scope, ops, actor, batch_id)
  0 require_actor            1 idempotency (batch_id + ops hash)
  2 resolve refs, mint       3 base_rev / concurrent-write check
  5 merge fields             6 validate (shape, refs exist)
  7 actor:human fields       8 post-baseline `because` (after derivation)
  9 apply + revisions        10 typed links + mentions
  11 side effects (approval → baseline, drift digest)
  12 propagate review items  13 close review items
  14 narrative stamps        15 events     16 commit + store the batch result
Everything runs in one transaction; any error rolls the whole batch back and every op's
errors come back at once."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.blueprint.schemas.blueprint import EXTERNAL_PREFIX
from app.blueprint.services.blueprint_loader import get_blueprint
from app.blueprint.services.record_validator import BATCH_REF_RE, RecordValidator
from app.core.database import get_primary_db
from app.core.utils.actor import Actor
from app.core.utils.time import utcnow
from app.exceptions import ConflictException, NotFoundException, ValidationException
from app.initiatives.models.initiative import Initiative
from app.initiatives.models.record import Record
from app.initiatives.models.record_revision import RecordRevision
from app.initiatives.models.write_batch import WriteBatch
from app.initiatives.repositories.event_repository import EventRepository
from app.initiatives.repositories.initiative_repository import InitiativeRepository
from app.initiatives.repositories.lease_repository import LeaseRepository
from app.initiatives.repositories.record_link_repository import RecordLinkRepository
from app.initiatives.repositories.record_repository import RecordRepository
from app.initiatives.repositories.record_revision_repository import (
    RecordRevisionRepository,
)
from app.initiatives.repositories.ref_counter_repository import RefCounterRepository
from app.initiatives.repositories.review_item_repository import ReviewItemRepository
from app.initiatives.repositories.write_batch_repository import WriteBatchRepository
from app.initiatives.schemas.write import OpResult, WriteOp, WriteResult
from app.initiatives.services.drift_service import DriftService, spec_moved
from app.initiatives.services.gate_rules import GateRules
from app.initiatives.services.record_graph import RecordGraph
from app.initiatives.services.review_service import DEAD, ReviewService, mentions_in

GLOBAL_SLUG = "_global"
SYSTEM_ACTOR = "srs"
CONCURRENT_WRITE_WINDOW = timedelta(minutes=15)
TEXT_FIELD_TYPES = ("string", "markdown", "narrative", "bullets", "rows")
APPROVAL_TARGETS = {"dri": "draft", "engg": "task", "qa": "acceptance_criterion"}


@dataclass
class _Plan:
    index: int
    op: WriteOp
    type_key: str
    ref: str
    existing: Optional[Record]
    before_fields: Dict[str, Any]
    fields: Dict[str, Any]
    title: str
    cause_refs: List[str] = field(default_factory=list)
    record: Optional[Record] = None
    revision: Optional[RecordRevision] = None
    action: str = "unchanged"
    links_changed: bool = False
    status_before: str = ""


def require_actor(actor: Optional[str]) -> str:
    """Every write names who made it. Anonymous writes are refused."""
    actor = (actor or "").strip()
    if not actor:
        raise ValidationException(
            message="Who is writing? Send an X-Actor header (REST and MCP) — e.g. "
            '"headers": {"X-Actor": "runner-sdk"} in .mcp.json.'
        )
    return actor[:128]


def _hash_ops(ops: List[WriteOp]) -> str:
    body = json.dumps([op.canonical() for op in ops], sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


class RecordService:
    def __init__(self, db: Annotated[Session, Depends(get_primary_db)]):
        self.db = db
        self.bp = get_blueprint()
        self.validator = RecordValidator(self.bp)
        self.initiatives = InitiativeRepository(db)
        self.records = RecordRepository(db)
        self.links = RecordLinkRepository(db)
        self.revisions = RecordRevisionRepository(db)
        self.counters = RefCounterRepository(db)
        self.batches = WriteBatchRepository(db)
        self.events = EventRepository(db)
        self.reviews = ReviewItemRepository(db)

    # ── reads ────────────────────────────────────────────────────────────

    def initiative(self, key: Union[int, str]) -> Initiative:
        """By id (what REST and MCP address); the slug is only accepted from in-process
        callers (the global scope's sentinel, the intake right after minting)."""
        if key == GLOBAL_SLUG or key == 0:
            return Initiative(id=0, slug=GLOBAL_SLUG, title="Global (standards, learnings)", spec_snapshot={}, snapshot_hash="")
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            initiative = self.initiatives.get_by_id(int(key))
        else:
            initiative = self.initiatives.get_by_slug(key)
        if initiative is None:
            known = ", ".join(f"{i.id} ({i.slug})" for i in self.initiatives.list_ordered())
            raise NotFoundException(message=f"No initiative {key}. Known: {known or 'none yet'}")
        return initiative

    def graph(self, initiative: Initiative, derive: bool = True) -> RecordGraph:
        now = utcnow()
        leases = [lease.item_key for lease in LeaseRepository(self.db).active(now)]
        return RecordGraph(
            self.bp,
            initiative,
            self.records.list_for(initiative.id),
            self.links.list_for(initiative.id),
            revisions_loader=lambda: self.revisions.list_for_initiative(initiative.id),
            leases=leases,
            global_records=self.records.list_for(0) if initiative.id != 0 else [],
            review_items=self.reviews.open_for(initiative.id),
            derive=derive,
        )

    def get(self, initiative: Initiative, ref: str) -> Record:
        record = self.records.get_by_ref(initiative.id, ref)
        if record is None:
            raise NotFoundException(message=f"No record '{ref}' in {initiative.slug}")
        return record

    def history(self, record: Record) -> List[RecordRevision]:
        return self.revisions.list_for_record(record.id)

    def find(
        self,
        graph: RecordGraph,
        type_: Optional[str] = None,
        status: Optional[str] = None,
        query: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[Record]:
        needle = (query or "").lower()
        out = []
        for r in graph.records:
            if since and r.updated_at.isoformat() < since:
                continue
            if type_ and r.type != type_:
                continue
            if status and r.status != status:
                continue
            if needle and needle not in f"{r.ref} {r.title} {json.dumps(r.fields, default=str)}".lower():
                continue
            out.append(r)
        if since:
            out.sort(key=lambda r: r.updated_at, reverse=True)
        return out

    # ── writes ───────────────────────────────────────────────────────────

    def write(self, slug: str, ops: List[WriteOp], actor: Actor, batch_id: Optional[str] = None) -> WriteResult:
        """Apply every op or none. Validation errors come back per op (ok=False)."""
        require_actor(actor.name)
        if not ops:
            raise ValidationException(message="ops: at least one op")
        batch_id = (batch_id or "").strip() or str(uuid4())
        ops_hash = _hash_ops(ops)
        initiative = self.initiative(slug)
        prior = self.batches.get(batch_id)
        if prior is not None:
            return self._replay(prior, initiative, actor, ops_hash, batch_id)
        try:
            result = self._write(initiative, ops, actor, batch_id)
            if not result.ok:
                self.db.rollback()
                return result
            self.batches.add(
                WriteBatch(
                    batch_id=batch_id,
                    initiative_id=initiative.id,
                    actor=actor.name,
                    actor_kind=actor.kind,
                    ops_hash=ops_hash,
                    result=result.to_dict(),
                )
            )
            self.db.commit()
            return result
        except IntegrityError:
            # A concurrent request stored the same batch_id first: answer as its replay.
            self.db.rollback()
            prior = self.batches.get(batch_id)
            if prior is None:
                raise
            return self._replay(prior, initiative, actor, ops_hash, batch_id)
        except Exception:
            self.db.rollback()
            raise

    def _replay(self, prior: WriteBatch, initiative: Initiative, actor: Actor, ops_hash: str, batch_id: str) -> WriteResult:
        """A batch_id is idempotent per (initiative, actor, ops): the same caller resending the
        same ops gets the stored result; anything else is a 409, never someone else's result."""
        if prior.initiative_id != initiative.id or prior.actor != actor.name or prior.ops_hash != ops_hash:
            what = (
                "in another initiative"
                if prior.initiative_id != initiative.id
                else "by another caller"
                if prior.actor != actor.name
                else "with different ops"
            )
            raise ConflictException(
                message=f"batch_id {batch_id} was already used {what} — use a new batch_id",
                error_code="BATCH_ID_REUSED",
            )
        replay = WriteResult.from_dict(prior.result)
        replay.replayed = True
        return replay

    def _fail(self, batch_id: str, results: List[OpResult]) -> WriteResult:
        for r in results:
            if not r.errors:
                r.action, r.rev, r.status = "not saved", None, None
            else:
                r.action = "error"
        return WriteResult(ok=False, batch_id=batch_id, results=results)

    def _write(self, initiative: Initiative, ops: List[WriteOp], actor: Actor, batch_id: str) -> WriteResult:
        before = self.graph(initiative)
        self._leases = {lease.item_key: lease for lease in LeaseRepository(self.db).active(utcnow())}
        gates_before = self.gate_summary(before)
        baseline_before = before.current_baseline()
        stale_before = set(before.all_stale())
        results = [OpResult(index=i, ref=op.ref, type=op.type) for i, op in enumerate(ops)]

        # 2 — resolve every op to (type, ref), minting refs; `#n` resolves against these
        resolved: List[Optional[Tuple[str, str]]] = []
        minted: Dict[str, str] = {}
        batch_refs: Dict[str, str] = {}
        seen_refs: Dict[str, int] = {}
        for i, op in enumerate(ops):
            out = self._resolve(initiative, op)
            if isinstance(out, list):
                results[i].errors += out
                resolved.append(None)
                continue
            type_key, ref, was_minted = out
            if ref in seen_refs:
                results[i].errors.append(f"ref: {ref} is already written by op {seen_refs[ref]} of this batch — merge them")
                resolved.append(None)
                continue
            seen_refs[ref] = i
            resolved.append((type_key, ref))
            results[i].ref, results[i].type = ref, type_key
            batch_refs[f"#{i}"] = ref
            if was_minted:
                minted[f"#{i}"] = ref
        created_refs = {ref for i, (t, ref) in enumerate(r for r in resolved if r) if before.get(ref) is None}

        # 3–7 — merge and validate each op against the state before the batch
        plans: List[Optional[_Plan]] = []
        for i, op in enumerate(ops):
            if resolved[i] is None:
                plans.append(None)
                continue
            type_key, ref = resolved[i]
            plan, errors = self._prepare(initiative, before, i, op, type_key, ref, batch_refs, created_refs, actor)
            results[i].errors += errors
            plans.append(plan)
        if any(r.errors for r in results):
            return self._fail(batch_id, results)

        # 9 — apply fields
        now = utcnow()
        for plan in plans:
            self._apply(initiative, plan, actor, now)
        self.db.flush()
        # 10 — typed links, mentions, op.link/unlink, op.because
        for plan in plans:
            plan.links_changed = self._apply_links(initiative, plan, batch_refs, before, actor)
        # revisions (status filled in once derived)
        for plan in plans:
            self._revise(plan, actor, batch_id, now)
        self.db.flush()

        # derive, then 11 — side effects of approvals
        after = self.graph(initiative)
        baseline_ref = None
        for plan in plans:
            if plan.type_key == "approval" and plan.action == "created":
                baseline_ref = self._approval_side_effects(initiative, after, plan, actor, batch_id) or baseline_ref
        if any(p.type_key == "approval" and p.action == "created" for p in plans):
            self.db.flush()
            after = self.graph(initiative)

        # 8 + status-conditioned rules, against the derived state after the batch
        for plan in plans:
            record = after.by_ref.get(plan.ref) or plan.record
            results[plan.index].errors += self.validator.rule_errors(plan.type_key, record.status, record.fields or {})
            results[plan.index].errors += self._cause_errors(after, plan, baseline_before, before, actor)
        if any(r.errors for r in results):
            return self._fail(batch_id, results)

        for plan in plans:
            record = after.by_ref.get(plan.ref) or plan.record
            if plan.revision is not None:
                plan.revision.status = record.status
            results[plan.index].action = plan.action
            results[plan.index].rev = record.head_rev
            results[plan.index].status = record.status

        # 12–13 — review queue
        review = ReviewService(self.db, self.bp)
        written = {p.ref for p in plans}
        for plan in plans:
            if plan.action == "updated":
                review.resolve_target(initiative, plan.ref, "revised", plan.op.note or "edited while up for review", actor.name)
            elif plan.op.reviewed and actor.kind == "human":
                review.resolve_target(initiative, plan.ref, "upheld", plan.op.note, actor.name)
            elif plan.op.reviewed:
                # "Still holds" from an agent is advice: the item stays open for a human.
                review.annotate_target(initiative, plan.ref, actor.name, plan.op.note)
        for record in after.records:
            if record.status in DEAD:
                review.resolve_target(initiative, record.ref, "revised", f"now {record.status}", actor.name)
        causes = []
        for plan in plans:
            if plan.action not in ("created", "updated"):
                continue
            record = after.by_ref[plan.ref]
            moved = ReviewService.material_change(
                self.bp.types[plan.type_key],
                plan.before_fields if plan.existing is not None else {},
                record.fields or {},
                plan.status_before,
                record.status,
            )
            if moved:
                causes.append((record, moved))
        queued = review.propagate(initiative, after, causes, written, actor.name)

        # 14 — narrative fingerprints for narratives written (or reviewed) in this batch
        for plan in plans:
            spec = self.bp.types[plan.type_key]
            slots = [
                n
                for n, f in spec.fields.items()
                if f.type == "narrative" and (plan.op.fields.get(n) is not None or (plan.op.reviewed and (plan.record.fields or {}).get(n)))
            ]
            if slots:
                meta = dict(plan.record.meta or {})
                narratives = dict(meta.get("narratives") or {})
                for slot in slots:
                    narratives[slot] = after.stamp(plan.record)
                meta["narratives"] = narratives
                plan.record.meta = meta

        # 15 — events, gates before/after
        for plan in plans:
            self.events.add(
                "record_written",
                initiative.id,
                plan.ref,
                actor.name,
                batch_id,
                {"type": plan.type_key, "rev": plan.record.head_rev, "action": plan.action, "actor_kind": actor.kind},
            )
        if baseline_ref:
            self.events.add("baseline_created", initiative.id, baseline_ref, SYSTEM_ACTOR, batch_id, {})
        for q in queued:
            self.events.add("review_item_queued", initiative.id, q.target, actor.name, batch_id, {"cause": q.cause, "route_to": q.route_to})
        after.invalidate()
        gates_after = self.gate_summary(after)
        gates_changed = [
            {"gate": key[0], "task": key[1], "before": gates_before.get(key, "—"), "after": value}
            for key, value in gates_after.items()
            if gates_before.get(key) != value
        ]
        for change in gates_changed:
            self.events.add("gate_changed", initiative.id, change["gate"] + (f":{change['task']}" if change["task"] else ""), actor.name, batch_id, change)
        # Derivation set record.status on every loaded record: the commit stores that cache
        # for all of them (no revision — a status is never written, only derived).
        self.db.flush()
        stale = sorted(set(after.all_stale()) - stale_before)
        return WriteResult(
            ok=True,
            batch_id=batch_id,
            results=results,
            minted=minted,
            review_items=[q.line() for q in queued],
            stale=stale,
            gates_changed=gates_changed,
            baseline=baseline_ref,
        )

    def gate_summary(self, g: RecordGraph) -> Dict[tuple, str]:
        if g.initiative.id == 0:
            return {}
        out = {("GATE_DRAFT", None): g.gate("GATE_DRAFT").status, ("GATE_VALIDATED", None): g.gate("GATE_VALIDATED").status}
        for task in g.of_type("task"):
            out[("GATE_PR", task.ref)] = g.gate("GATE_PR", task=task.ref).status
        return out

    # ── 2: resolve ───────────────────────────────────────────────────────

    def _resolve(self, initiative: Initiative, op: WriteOp):
        if op.ref:
            type_key = self.bp.type_of_ref(op.ref)
            if type_key is None:
                prefixes = ", ".join(f"{p}-n" for p in self.bp.prefixes())
                singletons = ", ".join(f"'{s}'" for s in self.bp.singletons())
                return [f"ref: '{op.ref}' matches nothing — use {prefixes}, {singletons}"]
            if op.type and op.type != type_key:
                return [f"type: '{op.ref}' is a {type_key}, not a {op.type}"]
            if self._scope_error(initiative, type_key):
                return [self._scope_error(initiative, type_key)]
            if self.bp.types[type_key].ref_kind == "prefix" and self.records.get_by_ref(initiative.id, op.ref) is None:
                return [f"ref: {op.ref} does not exist in {initiative.slug} — omit ref and give type to mint one"]
            return type_key, op.ref, False
        spec = self.bp.types.get(op.type or "")
        if spec is None:
            return [f"type: give a ref, or a type to mint one; types: {', '.join(self.bp.types)}"]
        if self._scope_error(initiative, spec.key):
            return [self._scope_error(initiative, spec.key)]
        if spec.ref_kind == "singleton":
            return spec.key, spec.ref_value, False
        n = self.counters.next(initiative.id, spec.ref_value)
        return spec.key, f"{spec.ref_value}-{n}", True

    def _scope_error(self, initiative: Initiative, type_key: str) -> str:
        scope = self.bp.types[type_key].scope
        if scope == "global" and initiative.id != 0:
            return f"type: a {type_key} lives in the global scope — write it to initiative 0 (POST /api/global/records)"
        if scope != "global" and initiative.id == 0:
            return f"type: a {type_key} belongs to an initiative, not the global scope (0)"
        return ""

    # ── 3–7: prepare one op ──────────────────────────────────────────────

    def _sub(self, value: str, batch_refs: Dict[str, str]) -> str:
        return batch_refs.get(value, value) if BATCH_REF_RE.match(value or "") else value

    def _prepare(self, initiative, before: RecordGraph, index, op: WriteOp, type_key, ref, batch_refs, created_refs, actor: Actor):
        spec = self.bp.types[type_key]
        existing = self.records.get_by_ref(initiative.id, ref)
        errors: List[str] = []
        rule = self.bp.lifecycle.status_rules.get(type_key) if self.bp.lifecycle else None
        if op.status:
            errors.append(
                f"status: derived, never typed — a {type_key}'s status comes from rule "
                f"'{rule.rule if rule else '?'}': {rule.text if rule else ''}"
            )
        if type_key == "baseline":
            # Only _create_baseline (a dri approval's side effect) mints B-n — never an op.
            errors.append("type: baselines are written by the service when the DRI approves the draft")
        if existing is not None and actor.kind == "agent":
            errors += self._lease_errors(initiative, type_key, ref, actor)
        if type_key == "approval" and existing is not None:
            errors.append("approval: approvals are immutable — approve again to record a new one")
        if existing is not None and op.base_rev is not None and op.base_rev != existing.head_rev:
            errors.append(
                f"base_rev: record is at rev {existing.head_rev}, you sent {op.base_rev} — re-read and merge"
            )
        elif existing is not None and op.base_rev is None and op.fields and actor.kind == "agent":
            # Parallel agents writing whole fields clobber each other; a human edit is deliberate.
            recent = (utcnow() - CONCURRENT_WRITE_WINDOW).isoformat(timespec="seconds")
            stamps = (existing.meta or {}).get("stamps", {})
            clobbered = [
                name
                for name, value in op.fields.items()
                if (stamp := stamps.get(name))
                and stamp.get("by") != actor.name
                and str(stamp.get("at", "")) > recent
                and (existing.fields or {}).get(name) != value
            ]
            if clobbered:
                who = stamps[clobbered[0]]["by"]
                errors.append(
                    f"base_rev: {', '.join(clobbered)} changed by {who} in the last "
                    f"{int(CONCURRENT_WRITE_WINDOW.total_seconds() // 60)} min (record now rev "
                    f"{existing.head_rev}) — re-read it and send `base_rev` with your write"
                )
        if op.reviewed and not (op.note or "").strip():
            errors.append("note: required with reviewed — say what you checked it against")

        before_fields = dict(existing.fields or {}) if existing is not None else {}
        fields = dict(before_fields)
        for name, value in (op.fields or {}).items():
            f = spec.fields.get(name)
            if value is None:
                fields.pop(name, None)
                continue
            if f is not None and f.type == "refs" and isinstance(value, list):
                value = [self._sub(v, batch_refs) if isinstance(v, str) else v for v in value]
            fields[name] = value

        title = (op.title or "").strip() or (existing.title if existing is not None else "")
        if not title:
            if spec.ref_kind == "singleton":
                title = initiative.title if type_key == "initiative" else f"{spec.title}"
            elif spec.line and isinstance(fields.get(spec.line), str):
                line = " ".join(fields[spec.line].split())
                title = line if len(line) <= 120 else line[:119] + "…"

        errors += self.validator.validate(type_key, ref, title, None, fields)

        # refs must resolve: a record in scope, a global record, one created in this batch, or external:
        for f in spec.refs_fields():
            for i, item in enumerate(fields.get(f.name) or []):
                if not isinstance(item, str) or item.startswith(EXTERNAL_PREFIX):
                    continue
                if BATCH_REF_RE.match(item):
                    errors.append(f"{f.name}[{i}]: '{item}' is not an op of this batch")
                elif item == ref:
                    errors.append(f"{f.name}[{i}]: a record cannot name itself")
                elif before.get(item) is None and item not in created_refs:
                    errors.append(f"{f.name}[{i}]: {item} does not exist in {initiative.slug}")
        because = [self._sub(b, batch_refs) for b in op.because or []]
        for i, b in enumerate(because):
            if self.bp.type_of_ref(b) not in ("gap", "decision", "finding"):
                errors.append(f"because[{i}]: '{b}' — name a gap (G-n), a decision (D-n) or a finding (F-n)")
            elif before.get(b) is None and b not in created_refs:
                errors.append(f"because[{i}]: {b} does not exist in {initiative.slug}")

        # 7 — actor: human. Rules are judged on the stricter of before and after, and a field
        # whose change would switch a rule off (MUST → SHOULD, escalated yes → no, a blocker
        # downgraded) is itself human-only: for agents the guard only ratchets up.
        if actor.kind != "human":
            judged_before, judged_after = before_fields, fields
            if existing is not None and spec.author_rules():
                author = {"created_by_kind": self._author_kind(existing)}
                judged_before, judged_after = {**before_fields, **author}, {**fields, **author}
            human = (
                spec.human_fields(judged_after)
                | spec.human_fields(judged_before)
                | spec.ratchet_fields(judged_before, judged_after)
            )
            for name in sorted(set(op.fields or {}) & human):
                if (op.fields or {}).get(name) != before_fields.get(name):
                    errors.append(f"{name}: human-only (agents ask, humans answer) — raise a gap, or ask in the web UI")
        # ADRs: superseded, never edited
        status_before = before.by_ref[ref].status if ref in before.by_ref else ""
        if type_key == "decision" and existing is not None and status_before == "DECIDED":
            if "verdict" in (op.fields or {}) and op.fields["verdict"] != before_fields.get("verdict"):
                errors.append(
                    f"verdict: {ref} is DECIDED — ADRs are superseded, never edited: write a new "
                    f"decision with supersedes: [{ref}] and because: [the gap or finding behind it]"
                )
        if type_key == "approval" and existing is None and not errors:
            errors += self._approval_errors(initiative, before, fields, actor)

        cause_refs = list(because)
        if "because" in spec.fields and fields.get("because") != before_fields.get("because"):
            cause_refs += list(fields.get("because") or [])
        plan = _Plan(
            index=index,
            op=op,
            type_key=type_key,
            ref=ref,
            existing=existing,
            before_fields=before_fields,
            fields=fields,
            title=title,
            cause_refs=sorted(set(cause_refs)),
            status_before=status_before,
        )
        plan.op.because = because
        return plan, errors

    def _author_kind(self, record: Record) -> str:
        revs = self.revisions.list_for_record(record.id)
        return revs[0].actor_kind if revs else ""

    def _lease_errors(self, initiative: Initiative, type_key: str, ref: str, actor: Actor) -> List[str]:
        """A leased work item is written by its holder only, among agents (humans and the
        service's own integrations are not lease-bound)."""
        suffix = f":{initiative.id}:{ref}"
        for key, lease in (getattr(self, "_leases", None) or {}).items():
            singleton = key == f"{type_key}:{initiative.id}" and self.bp.types[type_key].ref_kind == "singleton"
            if not (key.endswith(suffix) or singleton):
                continue
            if lease.holder.split("/")[0] != actor.principal:
                return [
                    f"ref: {ref} is leased by {lease.holder} until {lease.expires_at.isoformat(timespec='seconds')} "
                    f"({key}) — claim it when it is free, or ask the holder"
                ]
        return []

    def _approval_errors(self, initiative, g: RecordGraph, fields, actor: Actor) -> List[str]:
        targets = fields.get("target") or []
        role = fields.get("role")
        if len(targets) != 1:
            return ["target: exactly one record — the draft, a task, or a manual AC"]
        target = targets[0]
        target_type = self.bp.type_of_ref(target)
        want = APPROVAL_TARGETS.get(role)
        if want is None:
            return [f"role: {role} does not approve anything; approvers are {', '.join(APPROVAL_TARGETS)}"]
        if target_type != want:
            return [f"target: a {role} approves a {want}, not a {target_type}"]
        task_ref = target if target_type == "task" else None
        held = g.roles_of(actor.principal, task_ref)
        if role not in held:
            who = g.person_for(role, task_ref)
            return [
                f"role: {actor.principal or '?'} is not the {role} of {initiative.slug}"
                + (f" (the {role} is {who})" if who else f" (no {role} is assigned)")
            ]
        rules = GateRules(self.bp)
        if role == "dri":
            if g.get("draft") is None:
                return ["target: there is no draft to approve yet"]
            failing = rules.preconditions(g, "GATE_DRAFT")
            if failing:
                return [
                    "GATE_DRAFT is not ready: "
                    + "; ".join(f"{r.name}" + (f" ({', '.join(r.failing)})" if r.failing else "") for r in failing)
                ]
        if role == "engg":
            sha = fields.get("at_sha")
            pr_sha = g.f(target, "pr_sha")
            if sha and sha != pr_sha:
                return [f"at_sha: {target}'s PR head is {pr_sha or 'unknown'}, you approved {sha} — reload the drift report"]
            failing = rules.preconditions(g, "GATE_PR", task=target)
            if failing:
                return [
                    f"GATE_PR ({target}) is not ready: "
                    + "; ".join(f"{r.name}" + (f" ({', '.join(r.failing)})" if r.failing else "") for r in failing)
                ]
        if role == "qa" and g.f(target, "manual") != "yes":
            return [f"target: {target} is not a manual AC"]
        return []

    # ── 9–10: apply ──────────────────────────────────────────────────────

    def _apply(self, initiative: Initiative, plan: _Plan, actor: Actor, now) -> None:
        spec = self.bp.types[plan.type_key]
        if plan.existing is None:
            plan.record = self.records.add(
                Record(
                    initiative_id=initiative.id,
                    type=plan.type_key,
                    ref=plan.ref,
                    title=plan.title,
                    status="",
                    fields=self.bp.ordered_fields(plan.type_key, plan.fields),
                    meta={},
                    head_rev=1,
                    created_by=actor.name,
                    updated_by=actor.name,
                    created_at=now,
                    updated_at=now,
                )
            )
            plan.action = "created"
            changed = sorted(plan.fields)
        else:
            plan.record = plan.existing
            changed = sorted(
                k for k in set(plan.before_fields) | set(plan.fields) if plan.before_fields.get(k) != plan.fields.get(k)
            )
            if changed or plan.title != plan.existing.title:
                plan.record.title = plan.title
                plan.record.fields = self.bp.ordered_fields(plan.type_key, plan.fields)
                plan.action = "updated"
        if changed:
            meta = dict(plan.record.meta or {})
            stamps = dict(meta.get("stamps") or {})
            for name in changed:
                if name in plan.fields:
                    stamps[name] = {"by": actor.name, "kind": actor.kind, "at": now.isoformat(timespec="seconds")}
                else:
                    stamps.pop(name, None)
            meta["stamps"] = {k: stamps[k] for k in spec.fields if k in stamps}
            plan.record.meta = meta

    def _apply_links(self, initiative, plan: _Plan, batch_refs, before: RecordGraph, actor: Actor) -> bool:
        spec = self.bp.types[plan.type_key]
        record = plan.record
        current = self.links.out_of(initiative.id, record.ref)
        have = {(link.kind, link.to_ref) for link in current}
        want_typed = set()
        for f in spec.refs_fields():
            for item in record.fields.get(f.name) or []:
                if isinstance(item, str) and not item.startswith(EXTERNAL_PREFIX):
                    want_typed.add((f.link_kind, item))
        typed_kinds = {f.link_kind for f in spec.refs_fields()}
        known = set(before.by_ref) | set(before.global_by_ref) | set(batch_refs.values())
        text = {
            name: value
            for name, value in (record.fields or {}).items()
            if name in spec.fields and spec.fields[name].type in TEXT_FIELD_TYPES
        }
        want_mentions = {("mentions", r) for r in mentions_in(text) if r in known and r != record.ref}
        changed = False
        for kind, to in sorted(want_typed - have):
            changed |= self.links.ensure(initiative.id, record.ref, to, kind, actor.name)
        for kind, to in sorted(have):
            if kind in typed_kinds and (kind, to) not in want_typed:
                changed |= self.links.remove(initiative.id, record.ref, to, kind)
            if kind == "mentions" and (kind, to) not in want_mentions:
                changed |= self.links.remove(initiative.id, record.ref, to, kind)
        for kind, to in sorted(want_mentions - have):
            self.links.ensure(initiative.id, record.ref, to, kind, actor.name)  # mentions alone are not a change
        for b in plan.op.because or []:
            changed |= self.links.ensure(initiative.id, record.ref, b, "because", actor.name)
        for target in plan.op.link or []:
            target = self._sub(target, batch_refs)
            changed |= self.links.ensure(initiative.id, record.ref, target, "relates", actor.name)
        for target in plan.op.unlink or []:
            target = self._sub(target, batch_refs)
            changed |= self.links.remove(initiative.id, record.ref, target, "relates")
        return changed

    def _revise(self, plan: _Plan, actor: Actor, batch_id: str, now) -> None:
        record = plan.record
        if plan.action == "unchanged":
            if plan.links_changed:
                plan.action = "updated"
            elif (plan.op.note or "").strip() or plan.op.reviewed or plan.op.because:
                plan.action = "reviewed" if plan.op.reviewed else "noted"
            else:
                return
        if plan.existing is not None:
            record.head_rev += 1
            record.updated_by, record.updated_at = actor.name, now
        links = [f"{link.kind}:{link.to_ref}" for link in self.links.out_of(record.initiative_id, record.ref)]
        plan.revision = self.revisions.snapshot(
            record, sorted(links), actor.name, actor.kind, batch_id, plan.op.note, plan.cause_refs
        )

    # ── 11: side effects ─────────────────────────────────────────────────

    def _approval_side_effects(self, initiative, g: RecordGraph, plan: _Plan, actor: Actor, batch_id: str) -> Optional[str]:
        """The service completes the approval (approved_rev / at_sha / drift_digest) and, for
        a dri approval of the draft, writes baseline B-n: the frozen spec."""
        record = plan.record
        fields = dict(record.fields or {})
        role, target = fields.get("role"), (fields.get("target") or [None])[0]
        baseline_ref = None
        if role == "dri":
            draft = g.get("draft")
            fields["approved_rev"] = str(draft.head_rev)
            baseline_ref = self._create_baseline(initiative, g, record, draft, actor, batch_id)
        elif role == "engg":
            fields.setdefault("at_sha", g.f(target, "pr_sha"))
            fields["drift_digest"] = g.drift(task=target).digest
        elif role == "qa":
            fields["approved_rev"] = str(g.get(target).head_rev)
        record.fields = self.bp.ordered_fields("approval", fields)
        if plan.revision is not None:
            plan.revision.fields = dict(record.fields)
            plan.revision.note = (plan.revision.note + " · " if plan.revision.note else "") + "completed by the service"
        return baseline_ref

    def _create_baseline(self, initiative, g: RecordGraph, approval: Record, draft: Record, actor: Actor, batch_id: str) -> str:
        members = [draft]
        members += [d for d in g.of_type("decision") if d.status != "SUPERSEDED"]
        members += [a for a in g.of_type("acceptance_criterion") if a.status != "RETIRED"]
        members += g.of_type("gap")
        n = self.counters.next(initiative.id, "B")
        ref = f"B-{n}"
        now = utcnow()
        fields = {
            "label": f"{ref} — draft rev {draft.head_rev} approved by {actor.principal}",
            "approval": [approval.ref],
            "draft_rev": str(draft.head_rev),
            "approved_by": actor.principal,
            "members": [{"ref": m.ref, "type": m.type, "rev": str(m.head_rev)} for m in members],
            "snapshot": {
                m.ref: {
                    "type": m.type,
                    "title": m.title,
                    # the status each member has once this baseline exists
                    "status": {"draft": "APPROVED", "acceptance_criterion": "APPROVED"}.get(m.type, m.status),
                    "rev": m.head_rev,
                    "fields": dict(m.fields or {}),
                }
                for m in members
            },
        }
        record = self.records.add(
            Record(
                initiative_id=initiative.id,
                type="baseline",
                ref=ref,
                title=fields["label"],
                status="CURRENT",
                fields=self.bp.ordered_fields("baseline", fields),
                meta={},
                head_rev=1,
                created_by=SYSTEM_ACTOR,
                updated_by=SYSTEM_ACTOR,
                created_at=now,
                updated_at=now,
            )
        )
        self.links.ensure(initiative.id, ref, approval.ref, "from", SYSTEM_ACTOR)
        self.revisions.snapshot(record, [f"from:{approval.ref}"], SYSTEM_ACTOR, "system", batch_id, f"created by {approval.ref}", [])
        return ref

    # ── 8: post-baseline cause ───────────────────────────────────────────

    def _cause_errors(self, after: RecordGraph, plan: _Plan, baseline, before: RecordGraph, actor: Actor) -> List[str]:
        """After a baseline, the spec moves only with a reason: a material edit to a member, a
        new AC, or a decision taken, needs `because` that resolves to a human-answered gap,
        or a decision / finding whose explanation chain ends in a human act. A human's own edit
        is its own provenance; `system` is not exempt (it never edits the spec)."""
        spec = self.bp.types[plan.type_key]
        if baseline is None or not spec.post_baseline_cause or actor.kind == "human":
            return []
        record = after.by_ref.get(plan.ref) or plan.record
        members = before.baseline_members(baseline)
        fields = record.fields or {}
        if plan.existing is None:
            if plan.type_key == "decision" and not fields.get("verdict"):
                return []  # an open question changes nothing yet
            moved = [f"new {plan.type_key}"]
        else:
            moved = spec_moved(self.bp, plan.type_key, plan.before_fields, fields)
        if not moved:
            return []
        if not plan.cause_refs:
            where = "a member of" if plan.ref in members else "added after"
            return [
                f"because: spec change after baseline {baseline.ref} needs `because` (a gap answer, a "
                f"decision, a finding) — {plan.ref} is {where} the baseline; moved: {'; '.join(moved)}"
            ]
        drift = DriftService(self.bp)
        out = []
        for ref in plan.cause_refs:
            why = drift.cause_ok(after, ref)
            if not why.ok:
                out.append(f"because: {ref} does not explain a spec change — {why.why}")
        return out


def parse_op(raw: Dict[str, Any]) -> WriteOp:
    """A JSON op (REST / MCP) → WriteOp; unknown keys are refused so typos surface."""
    allowed = set(WriteOp.__dataclass_fields__)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValidationException(
            message=f"op: unknown key(s) {', '.join(unknown)} — an op is {{ref?, type?, title?, fields, link?, "
            "unlink?, note?, base_rev?, because?, reviewed?}}; field values go INSIDE `fields`"
        )
    data = dict(raw)
    for key in ("link", "unlink", "because"):
        if isinstance(data.get(key), str):
            data[key] = [data[key]]
        data[key] = list(data.get(key) or [])
    data["fields"] = dict(data.get("fields") or {})
    data["note"] = str(data.get("note") or "")
    return WriteOp(**data)


REF_RE = re.compile(r"^[A-Z]+-\d+$")
