"""The agent interface. A thin adapter: every tool calls the same services the REST API does
and returns compact text (see formatters.py). Every MCP caller is an AGENT (actor_kind
agent): human-only operations — answer a gap, rule a decision, approve, sign, promote —
are deliberately not tools here; humans do them in the web UI."""

import json
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import Context, FastMCP

from app.core import database
from app.core.utils.actor import ACTOR_HEADER, ACTOR_KIND_HEADER, Actor
from app.exceptions import BaseAppException
from app.initiatives.services import drift_render
from app.initiatives.services.activity_service import ActivityService
from app.initiatives.services.deploy_guard import DeployGuard
from app.initiatives.services.inbox_service import InboxService
from app.initiatives.services.initiative_service import InitiativeService, StartFeature
from app.initiatives.services.record_service import RecordService, parse_op
from app.initiatives.services.review_service import ReviewService
from app.initiatives.services.views import record_json
from app.initiatives.services.worklist_service import WorklistService
from app.mcp import formatters as fmt

INSTRUCTIONS = """\
System of record for the SDLC pipeline. You write typed records; statuses, gates, the
worklist and the drift report are derived from them.
Records: initiative · assignment (A-n) · draft · decision (D-n) · gap (G-n) ·
acceptance_criterion (AC-n) · task (T-n) · finding (F-n) · test_run (R-n) · deploy (DEP-n) ·
approval (APR-n, humans only) · baseline (B-n, written by the service).
Loop: next_work → claim → read the context → write → release. get_state shows the gates.
Statuses are DERIVED — never send `status`. Refs in text (`see D-3`) become links.
Three humans touch the work: the DRI approves the draft (baseline B-n), people answer gaps
in their inbox, an engineer approves each task's drift report at its PR head.
After a baseline, the spec (draft sections, decision verdicts, ACs) moves only WITH a
reason: send `because: ["G-4"]` (a gap a human answered, a decision, or a finding). A
DECIDED decision is never edited — write a new one with `supersedes: ["D-3"]`. When you
must deviate from the approved spec, raise a gap (kind deviation, blocks the D/AC/T) and
wait for the human answer; then supersede / add with `because`.
Fields marked HUMAN-ONLY (a gap's answer, an approval, a MUST verdict) refuse agent writes.
Who you are: the X-Actor header; `agent` says which agent or skill. Call blueprint once
before your first write to learn each type's fields."""

mcp = FastMCP("srs", instructions=INSTRUCTIONS, stateless_http=True, json_response=True)

# Tests swap this for their own session (and keep it open).
session_provider = None


def _actor(ctx: Optional[Context], agent: Optional[str]) -> Actor:
    request = getattr(getattr(ctx, "request_context", None), "request", None) if ctx is not None else None
    headers = request.headers if request is not None else {}
    kind = (headers.get(ACTOR_KIND_HEADER) or "").lower()
    # MCP is the agent interface: a caller is never treated as a human here.
    kind = "system" if kind == "system" else "agent"
    return Actor(principal=(headers.get(ACTOR_HEADER) or "").strip(), kind=kind, agent=(agent or "").strip())


@contextmanager
def _services():
    if session_provider is not None:
        db, close = session_provider(), False
    else:
        db, close = database.SessionLocalPrimary(), True
    try:
        yield RecordService(db)
    except BaseAppException as e:
        detail = e.message
        data = e.error_data or {}
        if data.get("results"):
            from app.initiatives.schemas.write import WriteResult

            detail = fmt.write_text(WriteResult.from_dict(data))
        raise ValueError(detail) from e
    finally:
        if close:
            db.close()


def _ops(ops: Union[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if isinstance(ops, str):
        try:
            ops = json.loads(ops)
        except json.JSONDecodeError as e:
            raise ValueError(f"ops: not valid JSON — {e}") from e
    if isinstance(ops, dict):
        ops = [ops]
    return list(ops or [])


@mcp.tool()
def blueprint(type: Optional[str] = None) -> str:
    """Record types with their fields, limits, HUMAN-ONLY flags, typed links, rules and the
    gates. Pass `type` for one type only."""
    with _services() as records:
        if type and type not in records.bp.types:
            raise ValueError(f"No type '{type}'. Types: {', '.join(records.bp.types)}")
        return fmt.blueprint_text(records.bp, type)


@mcp.tool()
def initiatives() -> str:
    """List initiatives: slug — title [phase] people."""
    with _services() as records:
        rows = InitiativeService(records).list()
        return "\n".join(
            f"{i['slug']} — {i['title']} [{i['phase']}] dri {i['dri'] or '—'} · engg {i['engg'] or '—'}" for i in rows
        ) or "none yet — create_initiative first"


@mcp.tool()
def create_initiative(
    title: str,
    requirement: str,
    dri: str,
    engg: str,
    ctx: Context,
    slug: Optional[str] = None,
    work_item_url: Optional[str] = None,
    product: Optional[str] = None,
    design: Optional[str] = None,
    qa: Optional[str] = None,
    agent: Optional[str] = None,
) -> str:
    """Start a feature: pins the requirement (markdown) as the spec snapshot and assigns
    the people (dri and engg required). work_item_url: optional Azure DevOps link."""
    with _services() as records:
        state = InitiativeService(records).start(
            StartFeature(title=title, requirement=requirement, dri=dri, engg=engg, slug=slug, work_item_url=work_item_url, product=product, design=design, qa=qa),
            _actor(ctx, agent),
        )
        return fmt.state_text(state)


@mcp.tool()
def get_state(initiative: str) -> str:
    """Phase, each gate PASSED/BLOCKED with the failing rules, tasks with GATE_PR, counts by
    status, baseline and drift counts, stale narratives, unassessed catalog items."""
    with _services() as records:
        return fmt.state_text(InitiativeService(records).state(initiative))


@mcp.tool()
def next_work(ctx: Context, initiative: Optional[str] = None, kind: Optional[str] = None, person: Optional[str] = None, limit: int = 5) -> str:
    """Prioritised items you may take now (not leased by someone else), each with its
    context (the record, what it cites, open review items, the phase catalog, drift).
    kind ∈ review, gap, decision, approval, draft, plan, tests, task, promotion, manual_ac."""
    with _services() as records:
        out = WorklistService(records).next_work(initiative, kind, person, _actor(ctx, None).name, limit)
        return fmt.items_text(out["items"])


@mcp.tool()
def claim(item_key: str, ctx: Context, ttl_min: int = 15, agent: Optional[str] = None) -> str:
    """Lease a work item (key from next_work, e.g. task:order-events:T-1)."""
    with _services() as records:
        lease = WorklistService(records).claim(item_key, _actor(ctx, agent).name, ttl_min)
        return f"claimed {lease['item_key']} until {lease['expires_at']}"


@mcp.tool()
def heartbeat(item_key: str, ctx: Context, ttl_min: int = 15, agent: Optional[str] = None) -> str:
    """Extend your lease."""
    with _services() as records:
        lease = WorklistService(records).heartbeat(item_key, _actor(ctx, agent).name, ttl_min)
        return f"held {lease['item_key']} until {lease['expires_at']}"


@mcp.tool()
def release(item_key: str, ctx: Context, agent: Optional[str] = None) -> str:
    """Give a lease back."""
    with _services() as records:
        out = WorklistService(records).release(item_key, _actor(ctx, agent).name)
        return f"released {item_key}" if out["released"] else f"you held no lease on {item_key}"


@mcp.tool()
def read_record(initiative: str, refs: Union[List[str], str], history: bool = False, as_json: bool = False) -> str:
    """Full records: links in/out, open review items, fields; history adds revisions with
    who (human/agent) and because. as_json returns the REST JSON shape."""
    if isinstance(refs, str):
        refs = [r.strip() for r in refs.split(",") if r.strip()]
    with _services() as records:
        i = records.initiative(initiative)
        g = records.graph(i)
        out = []
        for ref in refs:
            r = records.get(i, ref)
            r = g.by_ref.get(ref, r)
            if as_json:
                out.append(json.dumps(record_json(r, g, detail=True), indent=1, default=str))
            else:
                out.append(fmt.record_full(records.bp, r, g, records.history(r) if history else None))
        return "\n\n".join(out)


@mcp.tool()
def search_records(initiative: str, type: Optional[str] = None, status: Optional[str] = None, query: Optional[str] = None, since: Optional[str] = None) -> str:
    """Records of an initiative, one per line. Filters: type, status, free text, since (ISO)."""
    with _services() as records:
        g = records.graph(records.initiative(initiative))
        return fmt.records_text(records.bp, records.find(g, type, status, query, since))


@mcp.tool()
def history(initiative: str, ref: str) -> str:
    """Every revision of a record: rev, when, who (human/agent), because, note."""
    with _services() as records:
        i = records.initiative(initiative)
        r = records.get(i, ref)
        return fmt.record_full(records.bp, r, records.graph(i), records.history(r))


@mcp.tool()
def write(initiative: str, ops: Union[List[Dict[str, Any]], str], ctx: Context, batch_id: Optional[str] = None, agent: Optional[str] = None) -> str:
    """Write a batch atomically. op = {ref?, type?, title?, fields, link?, unlink?, note?,
    base_rev?, because?, reviewed?}. Omit ref and give type to mint (D-n…); `#0` names the
    ref op 0 minted. Never send status. Reuse batch_id to retry safely (idempotent)."""
    with _services() as records:
        result = records.write(initiative, [parse_op(o) for o in _ops(ops)], _actor(ctx, agent), batch_id)
        return fmt.write_text(result)


@mcp.tool()
def resolve_review_item(initiative: str, id: int, resolution: str, note: str, ctx: Context, agent: Optional[str] = None) -> str:
    """Close a review item: upheld (still holds — say why) · revised · dismissed."""
    with _services() as records:
        i = records.initiative(initiative)
        item = ReviewService(records.db, records.bp).resolve(i, id, resolution, note, _actor(ctx, agent).name)
        records.db.commit()
        return f"review item {item.id} ({item.target_ref} ← {item.cause_ref}) {item.status}"


@mcp.tool()
def gate_status(initiative: str, gate: Optional[str] = None, task: Optional[str] = None) -> str:
    """Each gate's rules: ok / !! with the refs that fail it. GATE_PR needs `task`."""
    with _services() as records:
        g = records.graph(records.initiative(initiative))
        gates = records.bp.lifecycle.gates
        keys = [gate] if gate else list(gates)
        out = []
        for key in keys:
            if key not in gates:
                raise ValueError(f"No gate '{key}'. Gates: {', '.join(gates)}")
            if gates[key].scope == "task":
                tasks = [task] if task else [t.ref for t in g.of_type("task")]
                out += [fmt.gate_text(g.gate(key, task=t)) for t in tasks]
            else:
                out.append(fmt.gate_text(g.gate(key)))
        return "\n".join(out) or "no gates"


@mcp.tool()
def drift_report(initiative: str, task: Optional[str] = None, baseline: Optional[str] = None, format: str = "text") -> str:
    """What changed in the spec since the approved baseline and which human decision
    authorised each change. task scopes it to one task (what its PR review reads).
    format: text | markdown | json."""
    with _services() as records:
        g = records.graph(records.initiative(initiative))
        report = g.drift(task=task, baseline=baseline)
        if format == "markdown":
            return drift_render.markdown(report)
        if format == "json":
            return json.dumps(report.to_dict(), indent=1, default=str)
        return drift_render.text(report)


@mcp.tool()
def deploy_guard(initiative: str, task: str, sha: str, environment: str, ctx: Context, record: bool = False, agent: Optional[str] = None) -> str:
    """GO / NO-GO for deploying a task at a sha. record=true writes the ask as a deploy row."""
    with _services() as records:
        guard = DeployGuard(records)
        out = guard.record(initiative, task, sha, environment, _actor(ctx, agent)) if record else guard.check(initiative, task, sha, environment)
        lines = [f"{out['decision']} — {task} @ {sha} → {environment}"]
        lines += [f"  {'ok' if c['passed'] else '!!'} {c['name']}: {c['detail']}" for c in out["checks"]]
        return "\n".join(lines)


@mcp.tool()
def inbox(person: str) -> str:
    """One human's lane: gaps, decisions to rule, approvals owed, review items, manual ACs
    — overdue first. (Read-only here: humans answer in the web UI.)"""
    with _services() as records:
        return fmt.inbox_text(InboxService(records).inbox(person))


@mcp.tool()
def worklist(initiative: str) -> str:
    """Every open item of an initiative, both lanes, with leases."""
    with _services() as records:
        return fmt.items_text(WorklistService(records).worklist(initiative)["items"])


@mcp.tool()
def activity(initiative: str, since: Optional[str] = None, ref: Optional[str] = None, actor: Optional[str] = None, limit: int = 50) -> str:
    """Revisions and review-queue moves, newest first."""
    with _services() as records:
        return fmt.activity_text(ActivityService(records).feed(initiative, since, ref, actor, limit))
