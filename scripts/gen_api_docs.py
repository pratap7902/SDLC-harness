#!/usr/bin/env python3
"""Regenerate docs/api.md from REAL responses: seeds a scratch SQLite DB with the demo
scenario (scripts/seed_demo.py), then calls every endpoint the UI uses and writes the
request and (trimmed) response of each into the document.

    .venv/bin/python scripts/gen_api_docs.py        # → docs/api.md
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(tempfile.mkdtemp(prefix="srs-docs-"))
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{SCRATCH / 'docs.db'}"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import seed_demo  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

OUT: list = []


def trim(value, depth=0, keep=2):
    """Lists keep their first items; long text is cut — enough to show the shape."""
    if isinstance(value, list):
        items = [trim(v, depth + 1, keep) for v in value[:keep]]
        if len(value) > keep:
            items.append(f"… (+{len(value) - keep} more)")
        return items
    if isinstance(value, dict):
        return {k: trim(v, depth + 1, keep) for k, v in value.items()}
    if isinstance(value, str) and len(value) > 220:
        return value[:200] + "…"
    return value


def client(person="priya", kind="human") -> TestClient:
    return TestClient(app, headers={"X-Actor": person, "X-Actor-Kind": kind})


def h(text: str) -> None:
    OUT.append(text)


IDS: dict = {}


def iid(slug: str) -> int:
    """Initiatives are addressed by id; the script names them by slug for readability."""
    if slug not in IDS:
        for row in client().get("/api/initiatives").json():
            IDS[row["slug"]] = row["id"]
    return IDS[slug]


def by_id(text: str) -> str:
    """`/api/initiatives/order-events/…` → `/api/initiatives/<id>/…`; `task:order-events:T-2` → `task:<id>:T-2`."""
    text = re.sub(r"/api/initiatives/([a-z][a-z0-9-]+)", lambda m: f"/api/initiatives/{iid(m.group(1))}", text)
    return re.sub(r"\b(task|draft|gap|decision|approval|review_item|manual_ac|tests|plan):([a-z][a-z0-9-]+)", lambda m: f"{m.group(1)}:{iid(m.group(2))}", text)


def show(method: str, path: str, *, who=("priya", "human"), body=None, params=None, about: str = "", keep=2, expect=None, raw=False, title=None):
    path = by_id(path)
    title = by_id(title) if title else None
    if body is not None:
        body = json.loads(by_id(json.dumps(body)))
    r = client(*who).request(method, path, json=body, params=params)
    if expect is not None:
        assert r.status_code == expect, f"{method} {path}: {r.status_code} {r.text[:800]}"
    elif r.status_code >= 400:
        raise SystemExit(f"{method} {path}: {r.status_code} {r.text[:800]}")
    query = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
    h(f"### {title or method + ' ' + path + query}\n")
    if about:
        h(about.strip() + "\n")
    actor = f"X-Actor: {who[0]} · X-Actor-Kind: {who[1]}"
    h(f"`{method} {path}{query}` — {actor} → **{r.status_code}**\n")
    if body is not None:
        h("Request:\n\n```json\n" + json.dumps(body, indent=2, ensure_ascii=False) + "\n```\n")
    if raw:
        h("Response (`" + r.headers.get("content-type", "") + "`):\n\n````markdown\n" + r.text.strip() + "\n````\n")
    else:
        h("Response:\n\n```json\n" + json.dumps(trim(r.json(), keep=keep), indent=2, ensure_ascii=False) + "\n```\n")
    return r.json() if not raw else r.text


INTRO = """# SDLC Record Service — REST API for the web UI

Every endpoint the UI needs, with **real** request/response examples captured from the
running service against the demo data (`make seed`). Regenerate with
`.venv/bin/python scripts/gen_api_docs.py`. Long lists are trimmed to their first items
(`"… (+N more)"`) and long strings to 200 chars — the shapes are exact.

## Conventions

- **Base URL**: `http://localhost:8791` (`make dev`). All JSON routes are under `/api`.
  The Vite dev server (`http://localhost:5173`) is allowed by CORS.
- **Who is calling** comes only from authentication, never from a path, query or body.
  `AUTH_MODE=token` (every environment but local/testing): `Authorization: Bearer <token>`
  (`make token`); the token decides the person, the kind (`human` | `agent`) and service
  roles; no valid token → **401** (`AUTH_REQUIRED` / `BAD_TOKEN`) on every route.
  `AUTH_MODE=header` (local dev, tests — the examples below): `X-Actor: <person handle>` and
  `X-Actor-Kind: human | agent`; a missing kind is `agent`. `system` is never accepted from
  a caller (403 `KIND_NOT_ALLOWED`). Human-only endpoints (marked **human**) return
  **403** with `error_code: "HUMAN_ONLY"` to anyone else. `GET /api/inbox` and
  `GET /api/overview` are the caller's.
- **Integrations** (people directory admin, Microsoft Teams, Outline `kb`, Azure DevOps
  Boards, webhooks under `/api/hooks/…` and `/api/teams/messages`) are documented with
  their setup in `docs/integrations.md`; they talk to external systems, so they have no
  live examples here. `GET /api/people` (below) now carries the directory fields.
- **Ids in paths**: an initiative is addressed by its numeric `id`
  (`/api/initiatives/{id}/…`, `initiative_id` in the deploy guard and MCP tools); `slug` is
  a display label. Records are addressed by their ref within the initiative
  (`/api/initiatives/{id}/records/D-3`). Work-item and lease keys are
  `<kind>:<initiative id>[:<ref>]` (`task:3:T-1`).
- **Gaps: anyone answers, both people are kept.** Any human may answer any open gap. The
  answer stores `assigned_to` / `assigned_role` (who it was routed to at that moment,
  frozen), `answered_by` (the caller) and `answered_on`; `answered_for` is set when the
  answerer is not the assignee. The drift entry reads "G-2 answered by priya · assigned to
  arjun"; the activity feed carries `answered_by`, `assigned_to`, `answered_for` on the
  answering revision.
- **Keys are snake_case**; timestamps are ISO-8601 UTC with a trailing `Z`.
- **Statuses are derived**, never written. Each status has a pill colour in
  `GET /api/blueprint` → `pills` (green / amber / red / grey); every record JSON also
  carries its own `pill`.
- **Errors** are RFC 9457 problem JSON: `{status, title, detail, instance, error_code,
  error_data}`. A rejected write is **422** with the full write result (every op's
  `errors`) in `error_data`. 404 = unknown initiative/record; 409 = conflict (a lease held
  by someone else, a batch_id reused with different ops, a duplicate slug).
- **Refs**: `D-n` decision · `G-n` gap · `AC-n` acceptance criterion · `T-n` task ·
  `F-n` finding · `R-n` test run · `DEP-n` deploy · `APR-n` approval · `B-n` baseline ·
  `A-n` assignment · `draft` and `initiative` (one each per initiative) · `STD-n`, `L-n`
  (global). Refs appear bare in text fields (`"see D-3"`): link them to
  `/features/<id>/records/<ref>`.
- **Record JSON** (lists, detail, everywhere): `{ref, type, title, status, pill, line,
  rev, fields, created_by, created_at, updated_by, updated_at}`; the detail endpoint adds
  `links {out: [{kind, to}], in: [{kind, from}]}`, `stamps` (who set each field, and as
  what), `stale` (narratives to rewrite) and open `review_items`. `line` is the type's
  one-line summary field (a gap's question, a decision's verdict…). Field names, types,
  limits, vocabularies and which fields are human-only come from `GET /api/blueprint`.

## Page → endpoints

| Page | Reads | Writes |
|---|---|---|
| `/` Features | `GET /api/overview` (the caller's view: every initiative, decisions waiting, your PR approvals) | — |
| `/new` start a feature | — | `POST /api/initiatives` |
| `/inbox` (touchpoint 2) | `GET /api/inbox` (what is routed to the caller); `?view=all` — every open gap, from `GET /api/overview` → `waiting` | `POST …/gaps/{ref}/answer`, `POST …/decisions/{ref}/rule`, `POST …/approvals`, `POST …/criteria/{ref}/sign`, `POST …/reviews/{id}/resolve` |
| `/features/:id` feature | `GET /api/initiatives/{id}`, `GET …/worklist`, `GET …/draft` | `POST …/snapshot` (re-pin requirement) |
| `/features/:id/draft` (touchpoint 1) | `GET /api/initiatives/{id}/draft` | `POST …/approvals` `{target: "draft", role: "dri"}`, `POST …/gaps/{ref}/answer` |
| `/features/:id/drift` | `GET …/drift` (`?baseline=B-n` for older) | — |
| `/features/:id/tasks/:ref` (touchpoint 3) | `GET …/tasks/{ref}` (task + GATE_PR + scoped drift) | `POST …/approvals` `{target: "T-n", role: "engg", at_sha}` |
| `/features/:id/records/:ref` record | `GET …/records/{ref}`, `GET …/records/{ref}/history` | `POST …/criteria/{ref}/retire` (an AC) |
| `/features/:id/reviews` | `GET …/reviews?status=open|upheld|revised|dismissed|all` | `POST …/reviews/{id}/resolve` |
| `/features/:id/activity` | `GET …/activity`, `GET …/events?since=` | — |
| `/standards`, `/learnings` | `GET /api/standards`, `GET /api/learnings` | `POST /api/learnings/{ref}/promote` |
| `/blueprint` | `GET /api/blueprint`, `GET /api/blueprint/lifecycle` | — |

The three human touchpoints:

1. **Draft review** — `/features/:id/draft`. Show the draft sections (`problem`, `hld`, `lld`,
   `scope_in`, `scope_out`, `test_strategy` — markdown), each decision with its `options`
   and `verdict`, each AC, each gap, the draft-phase catalog and `gate` (GATE_DRAFT, rule by
   rule). The **Approve** button is enabled when `can_approve` is true; otherwise list
   `approval_blockers`. Only the `approver` (the DRI) may approve.
2. **Gap reviews** — `/inbox`. Each item has `kind` (`gap` · `decision` ·
   `approval` · `review_item` · `manual_ac`), its context, `options` + `recommendation`
   (gaps), `blocks`, `sla_hours`, `due_at`, `overdue`. Answer = pick an option (`choice`)
   or type (`answer`). Any human may answer any open gap (see Conventions).
3. **Final PR review** — `/features/:id/tasks/:ref`. Render `drift` (the task-scoped drift report:
   `entries` as a timeline between `approved_spec` and `current_spec`, `spec_diff`,
   `unexplained`), the `gate` (GATE_PR) and the PR. **Approve** posts the PR head sha
   (`task.fields.pr_sha`); the service pins the report's `digest`. A later push or new drift
   makes the approval `STALE` and the gate re-blocks on its own.

### The drift report (`GET /api/initiatives/{id}/drift`)

`status`: `NO_BASELINE` (draft not yet approved) · `CLEAN` (nothing changed) · `EXPLAINED`
(every change has a human-grounded reason) · `UNEXPLAINED`.

- `baseline` — `{ref, label, status, approval, approved_by, draft_rev, created_at, members}`.
- `entries[]` — chronological; each `{id, kind, ref, type, rev, at, actor, actor_kind,
  summary, what_moved[], because[], explained, explanation[{ref, ok, why}], related[],
  detail{}, in_scope}`. `kind` ∈ `gap_answered` · `decision_superseded` · `decision_added`
  · `decision_changed` · `decision_confirmed` · `ac_added` · `ac_changed` · `ac_retired` ·
  `draft_edited` · `requirement_repinned`. `detail` per kind: gap_answered → `{question,
  answer, choice, answered_by, blocks, resolution, kind, proposed_change}`;
  decision_superseded → `{superseded, old_verdict, new_verdict, question, level, rationale,
  related_gaps}`; ac_added → `{text, level, source}`; ac_changed → `{old, new}`;
  decision_changed → `{old_verdict, new_verdict}`; draft_edited → `{sections}`.
- `unexplained[]` — ids of entries with `explained: false` (each entry's `explanation`
  says why).
- `pending_gaps[]`, `pending_decisions[]` — raised after the baseline and still open (not
  drift yet).
- `spec_diff` — `draft{section: {added, removed, diff}}` (unified diff text),
  `decisions{added[], superseded[{old, new, old_verdict, new_verdict}], changed[],
  unchanged}`, `criteria{added[], retired[], changed[{ref, old, new}], unchanged}`.
- `approved_spec` / `current_spec` — `{draft{problem, hld, lld, scope_in, scope_out,
  test_strategy}, decisions[{ref, title, question, verdict, level, status}],
  criteria[{ref, text, level, manual, status}]}` — render side by side.
- `summary` — `{changes, explained, unexplained, pending_gaps, pending_decisions,
  other_changes}` (`other_changes` = initiative changes outside this task's scope).
- `digest` — what an engg approval pins. `approvals[]` (task scope) — `{ref, by, status,
  at_sha, drift_digest, matches_digest, note, at}`.
- `format=md` returns the PR sticky comment (markdown); `format=text` the compact text.

---
"""


def main() -> None:
    os.environ.pop("SEED_KEEP", None)
    seed_demo.main()
    from app.core.utils.time import set_clock

    set_clock(None)
    h(INTRO)

    h("## Health and blueprint\n")
    show("GET", "/health")
    show("GET", "/api/blueprint", keep=1, about="Record types (fields with limits, vocabularies, `actor: human`, typed-link `targets`), status vocabularies, `open` statuses, pill colours. Lists trimmed to 1 here; the real response has every type and field.")
    show("GET", "/api/blueprint/lifecycle", keep=3, about="Phases, the derived-status rules (plain English), per-phase catalogs, gates with their rules, routing and SLAs.")

    h("## Initiatives\n")
    show("GET", "/api/initiatives", about="Every initiative with phase, people, counts, baseline and drift summary.")
    show(
        "GET",
        "/api/overview",
        who=("arjun", "human"),
        keep=2,
        about="**The Features list in one read.** Per initiative: phase, `people` (role → person), `involved` (the `person` holds a role or has an item), `next` (the next open human item — yours first, then what blocks work — with `person` and a short `label`), `prs` (`approved`/`total`, `stale` task refs), `gate_draft.state` (`drafting` · `waiting` · `ready` · `approved` · `reopened`), `drift`, `updated_at` (latest revision or review move), `agents` (`queued`, `leased`, lease `holders`). Across initiatives: `waiting` (every routed human item, inbox-shaped, sorted for `person`), `decisions` (the same without task PR approvals) and `my_pr_approvals`.",
    )
    started = show(
        "POST",
        "/api/initiatives",
        expect=201,
        body={
            "title": "Payment webhooks",
            "requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles.",
            "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
            "dri": "priya",
            "engg": "arjun",
            "product": "meera",
            "qa": "sam",
        },
        about="**Start a feature** (the intake; `/new`). `requirement` (markdown), `title`, `dri`, `engg` are required; `slug` defaults from the title; `work_item_url` (Azure DevOps link), `product`, `design`, `qa`, `prd_refs` are optional. Pins `spec_snapshot` with its hash and writes the assignments. Returns the same body as `GET /api/initiatives/{id}` (`initiative.id` is the new id). 422 lists every missing field in `error_data.errors`; 409 if an explicit `slug` exists.",
    )
    assert started["initiative"]["slug"] == "payment-webhooks"
    show("GET", "/api/initiatives/order-events", keep=3, about="**Initiative state**: the initiative with its `spec_snapshot`, `phase`, assignments, initiative-scope gates (rule by rule), tasks with their GATE_PR status and drift summary, counts by type and status, open refs, the current baseline, drift summary, stale narratives, and every catalog (phase → items with `disposition`: `addressed` · `not_applicable` · `UNASSESSED`).")
    show("GET", "/api/initiatives/menu-sync-retries/draft", keep=2, about="**Draft review page** (touchpoint 1). `can_approve`, `approval_blockers[{rule, failing, detail}]` and `approver` drive the Approve button.")
    show("GET", "/api/initiatives/order-events/draft", keep=2, title="GET /api/initiatives/order-events/draft (approved)", about="The same page once approved: `gate.status` PASSED, `baselines[]`, `approvals[]`; D-1 shows `superseded_by: [\"D-4\"]`.")

    h("## Records\n")
    show("GET", "/api/initiatives/order-events/records", params={"type": "decision"}, about="Filters: `type`, `status`, `q` (free text over ref, title and fields), `since` (ISO).")
    show("GET", "/api/initiatives/order-events/records/G-2", about="Record detail: links both ways, per-field stamps (`by`, `kind`, `at`), stale narratives, open review items.")
    show("GET", "/api/initiatives/order-events/records/D-1/history", about="Every revision, newest first: `actor`, `actor_kind`, `because`, `note`, the full `fields` at that rev.")
    show(
        "POST",
        "/api/initiatives/payment-webhooks/records",
        who=("runner-sdk", "agent"),
        body={
            "agent": "draft-skill",
            "batch_id": "docs-example-1",
            "ops": [
                {"type": "decision", "title": "Sign webhooks with HMAC", "fields": {"question": "How do merchants verify a webhook?", "domain": "engg", "level": "SHOULD", "verdict": "HMAC-SHA256 over the raw body with a per-merchant secret", "rationale": "Industry default.", "decided_by": "runner-sdk/draft-skill", "decided_on": "2026-10-29"}},
                {"type": "acceptance_criterion", "fields": {"text": "Given a settled payment, when the webhook is sent, then its signature verifies with the merchant secret", "level": "integration", "source": ["#0"]}},
                {"type": "acceptance_criterion", "fields": {"text": "Given a merchant, when ops replays a webhook from the admin, then it is resent within 1 minute", "level": "manual", "manual": "yes", "source": ["#0"]}},
                {"ref": "draft", "fields": {"problem": "Merchants poll for settlement.", "hld": "Send a signed webhook on settlement (D-1).", "lld": "webhook_deliveries table; retry with backoff.", "test_strategy": "Integration tests; AC-2 is checked by hand in staging.", "decisions": ["#0"], "criteria": ["#1", "#2"]}},
                {"ref": "initiative", "fields": {"catalog": [{"item": i, "phase": "draft", "disposition": "addressed"} for i in ("security_review", "rollback_plan", "observability", "data_migration_assessed", "test_strategy")]}},
            ],
        },
        about="**Write a batch** (agents and the UI's generic editor). Atomic: every op or none. An op is `{ref?, type?, title?, fields, link?, unlink?, note?, base_rev?, because?, reviewed?}` — omit `ref` and give `type` to mint; `#n` = the ref op n minted; `null` deletes a field; never send `status`. Reusing a `batch_id` with the same ops returns the stored result (`replayed: true`).",
    )
    show(
        "POST",
        "/api/initiatives/order-events/records",
        who=("runner-sdk", "agent"),
        expect=422,
        title="POST /api/initiatives/order-events/records (rejected)",
        body={"ops": [{"ref": "draft", "fields": {"lld": "Relay polls every 5s."}}, {"type": "acceptance_criterion", "fields": {"text": "Relay lag under 5s", "level": "integration", "source": ["D-2"]}}]},
        about="A rejected batch: **422**, nothing saved, each op's errors in `error_data.results[].errors` (ops that were fine say `not saved`). Here: after baseline B-1 an agent may not move the spec without `because` (a human-answered gap, a grounded decision, or a finding).",
    )

    h("## The human lane (touchpoint 2)\n")
    show("GET", "/api/inbox", who=("arjun", "human"), about="The caller's inbox (X-Actor) across initiatives, overdue first. `kind`: `gap` (answer it), `decision` (rule it: MUST or escalated), `approval` (`target`: `draft` or a task; tasks carry `drift` and `digest`), `review_item` (`review_item_id`, `what_moved`), `manual_ac` (sign it). `route` says why it landed here (`role`, `domain`, `fallback` = routed to the DRI because nobody holds the role).")
    show("GET", "/api/people", about="Everyone with an assignment and their inbox size (the “Viewing as” switcher: who the UI sends as X-Actor).")
    show("POST", "/api/initiatives/menu-sync-retries/gaps/G-1/answer", who=("priya", "human"), body={"choice": "per-partner", "answer": "Per partner: one flaky partner must not starve the rest."}, about="**human** — answer a gap: `choice` (an option key) and/or `answer` (text; defaults to the option's label). **Any human may answer any open gap**: here priya answers G-1, which is routed to meera (product). The service stores `answered_by` (the caller), `assigned_to` / `assigned_role` (the routing at this moment, frozen) and `answered_for` (the assignee, because they differ) — see the record below. Returns the write result; `review_items` lists what the answer put up for review and who it went to.")
    show("GET", "/api/initiatives/menu-sync-retries/records/G-1", keep=3, title="GET /api/initiatives/menu-sync-retries/records/G-1 (answered on meera's behalf)", about="`fields.answered_by`, `assigned_to`, `assigned_role`, `answered_for`.")
    show("POST", "/api/initiatives/menu-sync-retries/decisions/D-2/rule", who=("meera", "human"), body={"verdict": "Per partner: 5 retries per hour each", "rationale": "G-1: partner timeouts are uneven."}, about="**human** — rule an OPEN or PROVISIONAL decision (MUST-level or escalated decisions can only be ruled here). A DECIDED decision returns 422: supersede it instead.")
    r = client("runner-sdk", "agent").post("/api/initiatives/payment-webhooks/approvals", json={"target": "draft", "role": "dri"})
    h("### 403 for agents on human endpoints\n")
    h("`POST /api/initiatives/payment-webhooks/approvals` — X-Actor: runner-sdk · X-Actor-Kind: agent → **" + str(r.status_code) + "**\n")
    h("```json\n" + json.dumps(r.json(), indent=2, ensure_ascii=False) + "\n```\n")
    show("POST", "/api/initiatives/payment-webhooks/approvals", who=("priya", "human"), expect=201, body={"target": "draft", "role": "dri", "note": "Scope is right."}, about="**human** — approve. `role` dri → `target: \"draft\"` (creates baseline B-n: see `baseline` in the result); engg → a task ref, with `at_sha` = the PR head (the service pins the drift `digest`); qa → a manual AC. The caller must hold the role on the initiative, and the gate's other rules must pass — else 422 naming them.")
    show("POST", "/api/initiatives/payment-webhooks/criteria/AC-2/sign", who=("sam", "human"), body={"at_sha": "77ab01c"}, about="**human** (qa) — sign a manual AC at a sha.")
    show("POST", "/api/initiatives/payment-webhooks/criteria/AC-1/retire", who=("priya", "human"), body={"because": "Signature checks move to the shared webhook library."}, about="**human** — retire an AC (shows as `ac_retired` drift).")
    out = show("POST", "/api/initiatives/payment-webhooks/snapshot", who=("priya", "human"), body={"requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles **or is refunded**.", "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410"}, keep=1, about="**human** — re-pin the requirement (a material change: the draft goes up for review, and the drift report shows `requirement_repinned`). Returns `{state, write}`.")
    assert out["write"]["review_items"]

    h("## Review queue\n")
    items = show("GET", "/api/initiatives/payment-webhooks/reviews", about="Open review items (`?status=open` default; `upheld`, `revised`, `dismissed`, `all`). Each: `cause` moved (`what_moved`), so `target` may no longer hold; `route_to` is who should look.")
    show("POST", f"/api/initiatives/payment-webhooks/reviews/{items[0]['id']}/resolve", who=("priya", "human"), body={"resolution": "upheld", "note": "Refunds are a separate initiative; the draft holds."}, about="Resolve: `upheld` (still holds — say why) · `revised` · `dismissed`. `note` required. `upheld` and `dismissed` are **human** (403 `HUMAN_ONLY` to agents); an agent's `reviewed: true` write leaves the item open with `judged_by: agent` and its note.")

    h("## Drift, gates, tasks (touchpoint 3)\n")
    show("GET", "/api/initiatives/order-events/tasks/T-3", keep=3, about="**Task page**: the task (detail), its GATE_PR (rule by rule), its task-scoped drift report (full shape below), the approver, test runs, findings, deploys.")
    show("GET", "/api/initiatives/inventory-sync-v3/drift", params={"task": "T-1"}, keep=3, about="The task-scoped drift report. Without `task`: the whole initiative. `baseline=B-n`: from an older baseline up to the next one.")
    show("GET", "/api/initiatives/inventory-sync-v3/drift", params={"task": "T-1", "format": "md"}, raw=True, about="The same report as the PR's sticky comment.")
    show("GET", "/api/initiatives/order-events/drift", params={"task": "T-2"}, keep=1, title="GET /api/initiatives/order-events/drift?task=T-2 (CLEAN)", about="A task with nothing changed in its scope: `status: CLEAN`, `other_changes` counts the initiative's changes outside it.")
    show("GET", "/api/initiatives/loyalty-expiry/drift", keep=2, title="GET /api/initiatives/loyalty-expiry/drift (UNEXPLAINED)", about="An agent changed AC-4 after approval citing finding F-1; a human then rejected F-1, so the change lost its reason: `status: UNEXPLAINED`, the entry's `explanation` says why, the draft is REOPENED and GATE_PR blocks.")
    show("GET", "/api/initiatives/payment-webhooks/drift", keep=2, title="GET /api/initiatives/payment-webhooks/drift (initiative scope)", about="Initiative scope after an AC retirement and a requirement re-pin by humans.")
    show("GET", "/api/initiatives/order-events/gates", keep=3, about="Every gate: initiative gates once, task gates per task. Each: `{gate, scope, target, status, human_role, text, rules[{name, passed, failing, detail, args}], note, failing_rules}`.")
    show("GET", "/api/initiatives/order-events/tasks/T-2/gates")
    show("GET", "/api/deploy-guard", params={"initiative_id": iid("order-events"), "task": "T-3", "sha": "a41c09e", "environment": "staging"}, about="CI/CD asks before a deploy: `decision` GO | NO-GO, `reasons`, each check.")
    show("POST", "/api/deploy-guard", who=("github-actions", "agent"), body={"initiative_id": iid("order-events"), "task": "T-3", "sha": "0000000", "environment": "production"}, about="Same check, recorded as a `deploy` row (`deploy` in the response).")

    h("## Worklist, next work, leases\n")
    show("GET", "/api/initiatives/menu-sync-retries/worklist", about="Every open item of an initiative, both lanes (`agent` / `human`), grouped by kind, with leases.")
    show("GET", "/api/initiatives/order-events/next-work", who=("runner-sdk", "agent"), keep=1, about="What the caller may take now (not leased by someone else), priority order, each with a `context` bundle. `?kind=` and `?person=` filter; `GET /api/next-work` spans all initiatives.")
    show("POST", "/api/leases/claim", who=("runner-sdk", "agent"), body={"item_key": "task:order-events:T-2", "ttl_min": 15}, about="Lease an item. 409 with `error_data {holder, expires_at}` when someone else holds it.")
    show("POST", "/api/leases/task:order-events:T-2/heartbeat", who=("runner-sdk", "agent"), body={"ttl_min": 30})
    show("DELETE", "/api/leases/task:order-events:T-2", who=("runner-sdk", "agent"))

    h("## Activity and events\n")
    show("GET", "/api/initiatives/order-events/activity", params={"limit": "4"}, keep=4, about="Revisions and review-queue moves, newest first. Filters: `since` (ISO), `ref`, `actor` (prefix), `limit`.")
    show("GET", "/api/initiatives/order-events/events", params={"since": "0", "limit": "3"}, keep=3, about="The event log (`record_written`, `baseline_created`, `review_item_queued`, `review_item_resolved`, `gate_changed`, `initiative_created`, `lease_claimed`, `lease_released`). Poll with `since=<last id>`; `GET /api/events` spans all initiatives.")

    h("## Global scope: standards and learnings\n")
    show("GET", "/api/standards")
    show("GET", "/api/learnings")
    show("POST", "/api/learnings/L-1/promote", who=("priya", "human"), about="**human** — promote a learning.")
    show("POST", "/api/global/records", who=("runner-sdk", "agent"), body={"agent": "retro-skill", "ops": [{"type": "learning", "fields": {"text": "Replay endpoints need idempotency keys.", "source": "payment-webhooks:AC-2", "provenance": "QA sign-off"}}]}, about="Write standards / learnings (global scope, refs `STD-n` / `L-n`). Same op shape as record writes.")

    h("## Repo registry, JUnit ingestion (the runner)\n")
    show("POST", "/api/global/records", who=("priya", "human"), title="POST /api/global/records (register a repository)", body={"ops": [{"type": "repository", "fields": {"name": "wb-be", "default_branch": "main", "local_path": "/srv/repos/wb-be", "test_command": "make test", "junit_path": "reports/junit.xml", "templates": ["python-service"], "owners": ["arjun"], "state": "active"}}]}, keep=1, about="**human** for `local_path` and `test_command` (the runner executes against them). A `repository` record (`REPO-n`, global scope).")
    show("GET", "/api/repos", keep=1, about="Registered repositories: `name`, `default_branch` (the base), `local_path` (local mode), `clone_url` (GitHub mode), `test_command`, `junit_path`, `templates`, `owners`. `?include_retired=true` adds retired ones.")
    show("GET", "/api/repos/wb-be", about="One repository by short name (`/api/repos/{owner}/{name}` for GitHub names). 404 `REPO_NOT_REGISTERED` otherwise.")
    junit = '<testsuite><testcase classname="t" name="test_AC_1_outbox_row"/><testcase classname="t" name="test_AC_3_key"><failure message="x">boom</failure></testcase></testsuite>'
    show("POST", "/api/initiatives/order-events/test-runs/junit", who=("ci-bot", "agent"), expect=201, body={"task": "T-3", "sha": "a41c09e", "level": "integration", "run_url": "https://ci.example.com/runs/88", "junit_xml": junit}, about="CI (or the local-mode runner) posts a JUnit report for a task at a sha: one `test_run` bound to `sha`, a `covers` row per AC named in test names (`AC-3`, `AC_3`, `test_AC_3_…`, `testAc3…`; worst outcome per AC). `unknown_acs`, `task_acs_without_tests`. Re-posting the same report is a replay.")

    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "api.md").write_text("\n".join(OUT))
    print(f"wrote docs/api.md ({len(OUT)} blocks)")


if __name__ == "__main__":
    main()
