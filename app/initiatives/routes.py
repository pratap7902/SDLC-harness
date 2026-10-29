"""REST under /api — mirrors the MCP tools for CI/CD and serves the web UI. Human-only
endpoints (answer, rule, approve, sign, retire, promote, re-pin) return 403 to agents."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.auth.dependencies import Caller, Human
from app.exceptions import NotFoundException, ValidationException
from app.initiatives.controllers.record_controller import RecordController
from app.initiatives.requests.requests import (
    AnswerGapRequest,
    ApprovalRequest,
    ClaimRequest,
    DeployGuardRequest,
    HeartbeatRequest,
    RepinRequest,
    ResolveReviewRequest,
    RetireRequest,
    RuleDecisionRequest,
    SignRequest,
    StartFeatureRequest,
    WriteRequest,
)
from app.initiatives.services import drift_render
from app.initiatives.services.activity_service import ActivityService
from app.initiatives.services.deploy_guard import DeployGuard
from app.initiatives.services.inbox_service import InboxService
from app.initiatives.services.initiative_service import InitiativeService, StartFeature
from app.initiatives.services.overview_service import OverviewService
from app.initiatives.services.record_service import GLOBAL_SLUG, RecordService, parse_op
from app.initiatives.services.review_service import ReviewService
from app.initiatives.services.views import record_json, review_item_json
from app.initiatives.services.worklist_service import WorklistService

router = APIRouter(tags=["initiatives"])

Records = Annotated[RecordService, Depends()]
RecordsCtl = Annotated[RecordController, Depends()]
Initiatives = Annotated[InitiativeService, Depends()]
Inbox = Annotated[InboxService, Depends()]
Worklist = Annotated[WorklistService, Depends()]
Activity = Annotated[ActivityService, Depends()]
Guard = Annotated[DeployGuard, Depends()]
Overview = Annotated[OverviewService, Depends()]


# ── initiatives ─────────────────────────────────────────────────────────────


@router.get("/initiatives")
def list_initiatives(service: Initiatives):
    return service.list()


@router.get("/overview")
def overview(service: Overview, actor: Caller):
    """The Features list in one read: per initiative its phase, people, next open human item,
    PR approvals, drift, GATE_DRAFT state, latest activity and agent lane; across initiatives
    the decisions waiting (the caller's first) and the caller's PR approvals. The caller is
    X-Actor (a bearer token later), never a path or query parameter."""
    return service.overview(actor.principal or None)


@router.post("/initiatives", status_code=201)
def start_initiative(body: StartFeatureRequest, service: Initiatives, actor: Caller):
    """The intake: start a feature from a requirement (UI form, MCP create_initiative, and
    later the Azure DevOps importer all call the same IntakeService.start)."""
    return service.start(StartFeature(**body.model_dump()), actor)


@router.get("/initiatives/{initiative_id}")
def get_state(initiative_id: int, service: Initiatives):
    return service.state(initiative_id)


@router.post("/initiatives/{initiative_id}/snapshot")
def repin_snapshot(initiative_id: int, body: RepinRequest, service: Initiatives, actor: Human):
    return service.repin(initiative_id, body.requirement, body.work_item_url, actor)


@router.get("/initiatives/{initiative_id}/draft")
def draft_page(initiative_id: int, service: Initiatives):
    return service.draft_page(initiative_id)


# ── records ─────────────────────────────────────────────────────────────────


@router.get("/initiatives/{initiative_id}/records")
def list_records(
    initiative_id: int,
    controller: RecordsCtl,
    type: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    since: Optional[str] = None,
):
    return controller.list_records(initiative_id, type, status, q, since)


@router.post("/initiatives/{initiative_id}/records")
def write_records(initiative_id: int, body: WriteRequest, controller: RecordsCtl, actor: Caller):
    return controller.write(initiative_id, body, actor.with_agent(body.agent))


@router.get("/initiatives/{initiative_id}/records/{ref}")
def get_record(initiative_id: int, ref: str, controller: RecordsCtl):
    return controller.get_record(initiative_id, ref)


@router.get("/initiatives/{initiative_id}/records/{ref}/history")
def record_history(initiative_id: int, ref: str, controller: RecordsCtl):
    return controller.history(initiative_id, ref)


@router.get("/initiatives/{initiative_id}/tasks/{ref}")
def task_page(initiative_id: int, ref: str, records: Records):
    """The task page (touchpoint 3): the task, its GATE_PR, its scoped drift report."""
    g = records.graph(records.initiative(initiative_id))
    task = g.get(ref)
    if task is None or task.type != "task":
        raise NotFoundException(message=f"No task '{ref}' in initiative {initiative_id}")
    report = g.drift(task=ref)
    return {
        "task": record_json(task, g, detail=True),
        "gate": g.gate("GATE_PR", task=ref).to_dict(),
        "drift": report.to_dict(),
        "approver": g.person_for("engg", ref),
        "test_runs": [record_json(r, g) for r in g.of_type("test_run") if ref in (g.f(r, "task") or []) or any(row.get("ac") in (g.f(task, "covers") or []) for row in g.f(r, "covers") or [])],
        "findings": [record_json(f, g) for f in g.of_type("finding") if ref in (g.f(f, "target") or [])],
        "deploys": [record_json(d, g) for d in g.of_type("deploy") if ref in (g.f(d, "task") or [])],
    }


# ── worklist, next work, leases ─────────────────────────────────────────────


@router.get("/initiatives/{initiative_id}/worklist")
def worklist(initiative_id: int, service: Worklist):
    return service.worklist(initiative_id)


@router.get("/initiatives/{initiative_id}/next-work")
def next_work(initiative_id: int, service: Worklist, actor: Caller, kind: Optional[str] = None, person: Optional[str] = None, limit: int = 10):
    return service.next_work(initiative_id, kind, person, actor.name, limit)


@router.get("/next-work")
def next_work_all(service: Worklist, actor: Caller, kind: Optional[str] = None, person: Optional[str] = None, limit: int = 10):
    return service.next_work(None, kind, person, actor.name, limit)


@router.post("/leases/claim")
def claim(body: ClaimRequest, service: Worklist, actor: Caller):
    return service.claim(body.item_key, actor.name, body.ttl_min)


@router.post("/leases/{key}/heartbeat")
def heartbeat(key: str, service: Worklist, actor: Caller, body: Optional[HeartbeatRequest] = None):
    return service.heartbeat(key, actor.name, body.ttl_min if body else None)


@router.delete("/leases/{key}")
def release(key: str, service: Worklist, actor: Caller):
    return service.release(key, actor.name)


# ── gates, drift ────────────────────────────────────────────────────────────


@router.get("/initiatives/{initiative_id}/gates")
def gates(initiative_id: int, records: Records):
    g = records.graph(records.initiative(initiative_id))
    out = []
    for key, gate in records.bp.lifecycle.gates.items():
        if gate.scope == "initiative":
            out.append(g.gate(key).to_dict())
        else:
            out += [g.gate(key, task=t.ref).to_dict() for t in g.of_type("task")]
    return out


@router.get("/initiatives/{initiative_id}/tasks/{ref}/gates")
def task_gates(initiative_id: int, ref: str, records: Records):
    g = records.graph(records.initiative(initiative_id))
    if g.get(ref) is None or g.get(ref).type != "task":
        raise NotFoundException(message=f"No task '{ref}' in initiative {initiative_id}")
    return [g.gate(key, task=ref).to_dict() for key, gate in records.bp.lifecycle.gates.items() if gate.scope == "task"]


@router.get("/initiatives/{initiative_id}/drift")
def drift(initiative_id: int, records: Records, request: Request, task: Optional[str] = None, baseline: Optional[str] = None, format: str = Query("json", pattern="^(json|md|text)$")):
    g = records.graph(records.initiative(initiative_id))
    if task and (g.get(task) is None or g.get(task).type != "task"):
        raise NotFoundException(message=f"No task '{task}' in initiative {initiative_id}")
    if baseline and (g.get(baseline) is None or g.get(baseline).type != "baseline"):
        raise NotFoundException(message=f"No baseline '{baseline}' in initiative {initiative_id}")
    report = g.drift(task=task, baseline=baseline)
    if format == "md":
        return PlainTextResponse(drift_render.markdown(report, str(request.base_url).rstrip("/")), media_type="text/markdown")
    if format == "text":
        return PlainTextResponse(drift_render.text(report))
    return report.to_dict()


# ── review queue ────────────────────────────────────────────────────────────


@router.get("/initiatives/{initiative_id}/reviews")
def reviews(initiative_id: int, records: Records, status: Optional[str] = "open"):
    i = records.initiative(initiative_id)
    items = records.reviews.all_for(i.id, None if status in (None, "", "all") else status)
    return [review_item_json(x) for x in items]


@router.post("/initiatives/{initiative_id}/reviews/{item_id}/resolve")
def resolve_review(initiative_id: int, item_id: int, body: ResolveReviewRequest, records: Records, actor: Caller):
    i = records.initiative(initiative_id)
    item = ReviewService(records.db, records.bp).resolve(i, item_id, body.resolution, body.note, actor)
    records.events.add("review_item_resolved", i.id, item.target_ref, actor.name, "", {"id": item.id, "resolution": item.status})
    records.db.commit()
    return review_item_json(item)


# ── the human lane ──────────────────────────────────────────────────────────


@router.get("/inbox")
def inbox(service: Inbox, actor: Caller):
    """The caller's inbox: what is routed to X-Actor, across initiatives."""
    return service.inbox(actor.principal)


@router.get("/people")
def people(service: Inbox):
    return service.people()


@router.post("/initiatives/{initiative_id}/gaps/{ref}/answer")
def answer_gap(initiative_id: int, ref: str, body: AnswerGapRequest, service: Inbox, actor: Human):
    return service.answer_gap(initiative_id, ref, body.answer or "", body.choice, actor).to_dict()


@router.post("/initiatives/{initiative_id}/decisions/{ref}/rule")
def rule_decision(initiative_id: int, ref: str, body: RuleDecisionRequest, service: Inbox, actor: Human):
    return service.rule_decision(initiative_id, ref, body.verdict, body.rationale, actor).to_dict()


@router.post("/initiatives/{initiative_id}/approvals", status_code=201)
def approve(initiative_id: int, body: ApprovalRequest, service: Inbox, actor: Human):
    return service.approve(initiative_id, body.target, body.role, body.at_sha, body.note, actor).to_dict()


@router.post("/initiatives/{initiative_id}/criteria/{ref}/sign")
def sign(initiative_id: int, ref: str, body: SignRequest, service: Inbox, actor: Human):
    return service.sign_ac(initiative_id, ref, body.at_sha, actor).to_dict()


@router.post("/initiatives/{initiative_id}/criteria/{ref}/retire")
def retire(initiative_id: int, ref: str, body: RetireRequest, service: Inbox, actor: Human):
    return service.retire_ac(initiative_id, ref, body.because, actor).to_dict()


# ── global scope ────────────────────────────────────────────────────────────


@router.get("/standards")
def standards(records: Records):
    g = records.graph(records.initiative(GLOBAL_SLUG))
    return [record_json(r, g) for r in g.of_type("standard")]


@router.get("/learnings")
def learnings(records: Records):
    g = records.graph(records.initiative(GLOBAL_SLUG))
    return [record_json(r, g) for r in g.of_type("learning")]


@router.post("/global/records")
def write_global(body: WriteRequest, controller: RecordsCtl, actor: Caller):
    return controller.write(GLOBAL_SLUG, body, actor.with_agent(body.agent))


@router.post("/learnings/{ref}/promote")
def promote(ref: str, service: Inbox, actor: Human):
    return service.promote_learning(ref, actor).to_dict()


# ── deploy guard ────────────────────────────────────────────────────────────


@router.get("/deploy-guard")
def deploy_guard(guard: Guard, initiative_id: int, task: str, sha: str, environment: str):
    return guard.check(initiative_id, task, sha, environment)


@router.post("/deploy-guard")
def deploy_guard_record(body: DeployGuardRequest, guard: Guard, actor: Caller):
    return guard.record(body.initiative_id, body.task, body.sha, body.environment, actor)


# ── activity ────────────────────────────────────────────────────────────────


@router.get("/initiatives/{initiative_id}/activity")
def activity(initiative_id: int, service: Activity, since: Optional[str] = None, ref: Optional[str] = None, actor: Optional[str] = None, limit: int = 200):
    return service.feed(initiative_id, since, ref, actor, limit)


@router.get("/initiatives/{initiative_id}/events")
def events(initiative_id: int, service: Activity, since: int = 0, limit: int = 200):
    return service.events(initiative_id, since, limit)


@router.get("/events")
def all_events(service: Activity, since: int = 0, limit: int = 200):
    return service.events(None, since, limit)


__all__ = ["router", "parse_op", "ValidationException"]
