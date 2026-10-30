# SDLC Record Service — REST API for the web UI

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

## Health and blueprint

### GET /health

`GET /health` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "healthy"
}
```

### GET /api/blueprint

Record types (fields with limits, vocabularies, `actor: human`, typed-link `targets`), status vocabularies, `open` statuses, pill colours. Lists trimmed to 1 here; the real response has every type and field.

`GET /api/blueprint` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "vocab": {
    "initiative_phase": [
      "UNASSIGNED",
      "… (+6 more)"
    ],
    "assignment_status": [
      "ACTIVE",
      "… (+1 more)"
    ],
    "draft_status": [
      "DRAFTING",
      "… (+3 more)"
    ],
    "decision_status": [
      "OPEN",
      "… (+3 more)"
    ],
    "gap_status": [
      "OPEN",
      "… (+2 more)"
    ],
    "ac_status": [
      "PROPOSED",
      "… (+3 more)"
    ],
    "task_status": [
      "READY",
      "… (+5 more)"
    ],
    "finding_status": [
      "OPEN",
      "… (+3 more)"
    ],
    "test_run_status": [
      "GREEN",
      "… (+2 more)"
    ],
    "deploy_status": [
      "PENDING",
      "… (+3 more)"
    ],
    "approval_status": [
      "CURRENT",
      "… (+1 more)"
    ],
    "baseline_status": [
      "CURRENT",
      "… (+1 more)"
    ],
    "standard_status_derived": [
      "DRAFT",
      "… (+3 more)"
    ],
    "learning_status": [
      "DRAFT",
      "… (+1 more)"
    ],
    "role": [
      "dri",
      "… (+4 more)"
    ],
    "domain": [
      "product",
      "… (+2 more)"
    ],
    "std_level": [
      "MUST",
      "… (+1 more)"
    ],
    "yes_no": [
      "yes",
      "… (+1 more)"
    ],
    "channel": [
      "web",
      "… (+1 more)"
    ],
    "gap_kind": [
      "unknown",
      "… (+4 more)"
    ],
    "test_level": [
      "unit",
      "… (+3 more)"
    ],
    "pr_state": [
      "none",
      "… (+5 more)"
    ],
    "severity": [
      "blocker",
      "… (+3 more)"
    ],
    "finding_resolution": [
      "fixed",
      "… (+2 more)"
    ],
    "run_result": [
      "GREEN",
      "… (+2 more)"
    ],
    "deploy_result": [
      "PENDING",
      "… (+3 more)"
    ],
    "environment": [
      "test",
      "… (+2 more)"
    ],
    "catalog_disposition": [
      "addressed",
      "… (+1 more)"
    ],
    "learning_stage": [
      "draft",
      "… (+1 more)"
    ],
    "standard_status": [
      "draft",
      "… (+3 more)"
    ]
  },
  "open": {
    "decision_status": [
      "OPEN",
      "… (+1 more)"
    ],
    "gap_status": [
      "OPEN"
    ],
    "draft_status": [
      "DRAFTING",
      "… (+2 more)"
    ],
    "ac_status": [
      "PROPOSED"
    ],
    "task_status": [
      "BLOCKED",
      "… (+4 more)"
    ],
    "finding_status": [
      "OPEN"
    ],
    "approval_status": [
      "STALE"
    ]
  },
  "answers": [
    "ANSWERED",
    "… (+2 more)"
  ],
  "pills": {
    "APPROVED": "green",
    "DECIDED": "green",
    "ANSWERED": "green",
    "DONE": "green",
    "GREEN": "green",
    "DEPLOYED": "green",
    "CURRENT": "green",
    "ACTIVE": "green",
    "FIXED": "green",
    "PROMOTED": "green",
    "ENFORCED": "green",
    "SHIP": "green",
    "IN_REVIEW": "amber",
    "PROVISIONAL": "amber",
    "IN_PROGRESS": "amber",
    "ADDED_AFTER_BASELINE": "amber",
    "PENDING": "amber",
    "STALE": "amber",
    "DRAFTING": "amber",
    "PROPOSED": "amber",
    "PLAN": "amber",
    "BUILD": "amber",
    "VALIDATE": "amber",
    "DRAFT": "amber",
    "OPEN": "red",
    "REOPENED": "red",
    "BLOCKED": "red",
    "STUCK": "red",
    "RED": "red",
    "ERROR": "red",
    "FAILED": "red",
    "ROLLED_BACK": "red",
    "UNASSIGNED": "red",
    "SUPERSEDED": "grey",
    "WITHDRAWN": "grey",
    "RETIRED": "grey",
    "REPLACED": "grey",
    "REJECTED": "grey",
    "ACKNOWLEDGED": "grey",
    "CLOSED": "grey",
    "READY": "grey"
  },
  "types": [
    {
      "key": "initiative",
      "title": "Initiative",
      "plural": "Initiatives",
      "ref": {
        "kind": "singleton",
        "value": "initiative"
      },
      "scope": "initiative",
      "status_vocab": "initiative_phase",
      "statuses": [
        "UNASSIGNED",
        "… (+6 more)"
      ],
      "status_rule": {
        "rule": "initiative_phase",
        "text": "UNASSIGNED until a dri and an engg are assigned · DRAFT until GATE_DRAFT passes · PLAN until every AC is covered by a task · BUILD until every task is DONE · VALIDATE until GATE_VALIDATED passes · SHI…"
      },
      "line": null,
      "narrated": true,
      "post_baseline_cause": false,
      "propagates_to": [
        "draft"
      ],
      "index": {
        "facets": [],
        "columns": [],
        "newest_first": false
      },
      "fields": [
        {
          "name": "summary",
          "type": "narrative",
          "max": 800,
          "required": false,
          "expect": true,
          "vocab": null,
          "values": null,
          "columns": [],
          "row_key": null,
          "column_vocab": {},
          "help": "",
          "material": false,
          "actor": null,
          "targets": [],
          "link_kind": null
        },
        "… (+5 more)"
      ],
      "rules": [],
      "actor_rules": []
    },
    "… (+13 more)"
  ]
}
```

### GET /api/blueprint/lifecycle

Phases, the derived-status rules (plain English), per-phase catalogs, gates with their rules, routing and SLAs.

`GET /api/blueprint/lifecycle` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "phases": [
    "intake",
    "draft",
    "plan",
    "… (+3 more)"
  ],
  "roles": [
    "dri",
    "product",
    "design",
    "… (+2 more)"
  ],
  "status_rules": {
    "initiative": {
      "rule": "initiative_phase",
      "text": "UNASSIGNED until a dri and an engg are assigned · DRAFT until GATE_DRAFT passes · PLAN until every AC is covered by a task · BUILD until every task is DONE · VALIDATE until GATE_VALIDATED passes · SHI…"
    },
    "assignment": {
      "rule": "assignment_status",
      "text": "ACTIVE; REPLACED when a newer assignment for the same role and scope exists"
    },
    "draft": {
      "rule": "draft_status",
      "text": "DRAFTING → IN_REVIEW (submitted_rev set) → APPROVED (a dri approval created a baseline) → REOPENED (the initiative has unexplained drift since the baseline)"
    },
    "decision": {
      "rule": "decision_status",
      "text": "SUPERSEDED if another decision supersedes it · OPEN if verdict empty · PROVISIONAL if provisional=yes · DECIDED"
    },
    "gap": {
      "rule": "gap_status",
      "text": "WITHDRAWN if withdrawn_because · ANSWERED if answer · OPEN"
    },
    "acceptance_criterion": {
      "rule": "ac_status",
      "text": "RETIRED if retired_because · APPROVED if in the current baseline · ADDED_AFTER_BASELINE if a baseline exists and this AC is not in it · PROPOSED"
    },
    "task": {
      "rule": "task_status",
      "text": "DONE if pr_state=merged and every covered AC has a green test run at pr_sha · STUCK if ci_attempts≥3 or review_rounds≥3 · BLOCKED if a depends_on task is not DONE, an implemented MUST decision is OPEN…"
    },
    "finding": {
      "rule": "finding_status",
      "text": "OPEN if resolution empty, else FIXED | REJECTED | ACKNOWLEDGED"
    },
    "test_run": {
      "rule": "test_run_status",
      "text": "= result (GREEN | RED | ERROR)"
    },
    "deploy": {
      "rule": "deploy_status",
      "text": "= result (PENDING | DEPLOYED | FAILED | ROLLED_BACK)"
    },
    "approval": {
      "rule": "approval_status",
      "text": "draft: CURRENT while its baseline is the newest and the draft is not REOPENED · task: CURRENT while at_sha = pr_sha and drift_digest = drift_report(task).digest · AC: CURRENT while the AC is at approved_rev · else STALE"
    },
    "baseline": {
      "rule": "baseline_status",
      "text": "CURRENT for the newest baseline of an initiative, SUPERSEDED for older"
    },
    "standard": {
      "rule": "field_status",
      "text": "= state, upper-cased",
      "field": "state"
    },
    "learning": {
      "rule": "field_status",
      "text": "= stage, upper-cased (DRAFT when empty)",
      "field": "stage"
    }
  },
  "catalogs": {
    "intake": [
      {
        "item": "dri_assigned",
        "phase": "intake",
        "text": "an ACTIVE dri assignment",
        "derived": true
      },
      {
        "item": "engg_assigned",
        "phase": "intake",
        "text": "an ACTIVE engg assignment",
        "derived": true
      },
      {
        "item": "requirement_snapshotted",
        "phase": "intake",
        "text": "spec_snapshot pinned with its hash",
        "derived": true
      }
    ],
    "draft": [
      {
        "item": "security_review",
        "phase": "draft",
        "text": "threats, data classification, authn/z touched",
        "derived": false
      },
      {
        "item": "rollback_plan",
        "phase": "draft",
        "text": "how a bad deploy is undone",
        "derived": false
      },
      {
        "item": "observability",
        "phase": "draft",
        "text": "metrics, logs, alerts that show it works",
        "derived": false
      },
      "… (+2 more)"
    ],
    "plan": [
      {
        "item": "every_ac_covered_by_a_task",
        "phase": "plan",
        "text": "each live AC is in some task's covers",
        "derived": true
      },
      {
        "item": "every_task_has_template",
        "phase": "plan",
        "text": "each task names its paved-road template",
        "derived": true
      }
    ],
    "build": []
  },
  "gates": {
    "GATE_DRAFT": {
      "scope": "initiative",
      "human": "dri",
      "text": "Touchpoint 1 — the DRI approves the draft; approval creates baseline B-n",
      "on_pass": "create_baseline",
      "rules": [
        {
          "name": "no_open_decision_in_draft_scope",
          "args": {}
        },
        {
          "name": "no_open_gap_blocking_draft",
          "args": {}
        },
        {
          "name": "no_open_review_items_on_spec",
          "args": {}
        },
        "… (+4 more)"
      ]
    },
    "GATE_PR": {
      "scope": "task",
      "human": "engg",
      "text": "Touchpoint 3 — the engineer approves the task's drift report at the PR head",
      "on_pass": null,
      "rules": [
        {
          "name": "pr_state_in",
          "args": {
            "states": [
              "open",
              "approved"
            ]
          }
        },
        {
          "name": "no_blocker_finding_open_at_sha",
          "args": {}
        },
        {
          "name": "every_covered_ac_has_a_test",
          "args": {}
        },
        "… (+3 more)"
      ]
    },
    "GATE_VALIDATED": {
      "scope": "initiative",
      "human": null,
      "text": "Derived — every live AC green (scoped to the task's ACs when deploy_guard asks), manual ACs signed by QA, no open blocker",
      "on_pass": null,
      "rules": [
        {
          "name": "every_ac_green",
          "args": {}
        },
        {
          "name": "manual_acs_signed_by",
          "args": {
            "role": "qa"
          }
        },
        {
          "name": "no_blocker_finding_open",
          "args": {}
        }
      ]
    }
  },
  "deploy_guard": {
    "text": "GATE_PR passed for the task at this sha AND GATE_VALIDATED for the task's ACs AND no OPEN or PROVISIONAL decision among the task's implements",
    "args": [
      "initiative",
      "task",
      "sha",
      "… (+1 more)"
    ]
  },
  "routing": {
    "by_domain": {
      "product": "product",
      "design": "design",
      "engg": "engg"
    },
    "gates": {
      "GATE_DRAFT": "dri",
      "GATE_PR": "engg",
      "manual_ac": "qa"
    },
    "fallback": "dri",
    "sla_hours": {
      "gap": 24,
      "decision": 24,
      "approval": 48,
      "review_item": 48,
      "manual_ac": 48
    },
    "escalate_to": "dri"
  },
  "handoff": {
    "ci_attempts": 3,
    "review_rounds": 3
  }
}
```

## Initiatives

### GET /api/initiatives

Every initiative with phase, people, counts, baseline and drift summary.

`GET /api/initiatives` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "id": 7,
    "slug": "webhook-signing",
    "title": "Partner webhook signing",
    "work_item_url": null,
    "created_by": "rahul",
    "created_at": "2026-10-30T07:35:00Z",
    "closed_at": null,
    "snapshot_hash": "6034c8c1e9f65dda7cea51ae62a60898fa72719cae36c16dd429f978eaadf443",
    "phase": "DRAFT",
    "pill": "amber",
    "summary": "",
    "dri": "rahul",
    "engg": "nikhil",
    "counts": {
      "open_gaps": 0,
      "open_decisions": 0,
      "tasks": 0,
      "tasks_done": 0,
      "open_review_items": 0
    },
    "baseline": null,
    "drift": null
  },
  {
    "id": 6,
    "slug": "menu-sync-retries",
    "title": "Menu sync retries",
    "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4833",
    "created_by": "priya",
    "created_at": "2026-10-29T05:41:00Z",
    "closed_at": null,
    "snapshot_hash": "3097d30d3c0ef5cc69b40b07b6ffb41959ba287e244ebe43959366e39c6a7030",
    "phase": "DRAFT",
    "pill": "amber",
    "summary": "",
    "dri": "priya",
    "engg": "arjun",
    "counts": {
      "open_gaps": 1,
      "open_decisions": 1,
      "tasks": 0,
      "tasks_done": 0,
      "open_review_items": 0
    },
    "baseline": null,
    "drift": null
  },
  "… (+5 more)"
]
```

### GET /api/overview

**The Features list in one read.** Per initiative: phase, `people` (role → person), `involved` (the `person` holds a role or has an item), `next` (the next open human item — yours first, then what blocks work — with `person` and a short `label`), `prs` (`approved`/`total`, `stale` task refs), `gate_draft.state` (`drafting` · `waiting` · `ready` · `approved` · `reopened`), `drift`, `updated_at` (latest revision or review move), `agents` (`queued`, `leased`, lease `holders`). Across initiatives: `waiting` (every routed human item, inbox-shaped, sorted for `person`), `decisions` (the same without task PR approvals) and `my_pr_approvals`.

`GET /api/overview` — X-Actor: arjun · X-Actor-Kind: human → **200**

Response:

```json
{
  "person": "arjun",
  "summary": {
    "features": 7,
    "decisions_waiting": 7,
    "agents_working": 5,
    "agents_leased": 3
  },
  "initiatives": [
    {
      "id": 7,
      "slug": "webhook-signing",
      "title": "Partner webhook signing",
      "work_item_url": null,
      "created_by": "rahul",
      "created_at": "2026-10-30T07:35:00Z",
      "closed_at": null,
      "snapshot_hash": "6034c8c1e9f65dda7cea51ae62a60898fa72719cae36c16dd429f978eaadf443",
      "phase": "DRAFT",
      "pill": "amber",
      "summary": "",
      "dri": "rahul",
      "engg": "nikhil",
      "people": {
        "dri": "rahul",
        "engg": "nikhil"
      },
      "involved": false,
      "counts": {
        "open_gaps": 0,
        "open_decisions": 0,
        "tasks": 0,
        "tasks_done": 0,
        "open_review_items": 0,
        "waiting": 0
      },
      "next": null,
      "prs": {
        "total": 0,
        "approved": 0,
        "approved_refs": [],
        "stale": [],
        "with_pr": 0,
        "done": 0
      },
      "gate_draft": {
        "status": "BLOCKED",
        "state": "drafting",
        "failing_rules": [
          "catalog_addressed"
        ],
        "draft_rev": null,
        "draft_status": null
      },
      "baseline": null,
      "drift": null,
      "updated_at": "2026-10-30T07:35:00Z",
      "agents": {
        "queued": 0,
        "leased": 1,
        "holders": [
          "runner-sdk/draft-from-ticket"
        ],
        "working": [
          {
            "kind": "draft",
            "ref": null,
            "holder": "runner-sdk/draft-from-ticket"
          }
        ]
      }
    },
    {
      "id": 6,
      "slug": "menu-sync-retries",
      "title": "Menu sync retries",
      "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4833",
      "created_by": "priya",
      "created_at": "2026-10-29T05:41:00Z",
      "closed_at": null,
      "snapshot_hash": "3097d30d3c0ef5cc69b40b07b6ffb41959ba287e244ebe43959366e39c6a7030",
      "phase": "DRAFT",
      "pill": "amber",
      "summary": "",
      "dri": "priya",
      "engg": "arjun",
      "people": {
        "dri": "priya",
        "engg": "arjun",
        "product": "meera"
      },
      "involved": true,
      "counts": {
        "open_gaps": 1,
        "open_decisions": 1,
        "tasks": 0,
        "tasks_done": 0,
        "open_review_items": 0,
        "waiting": 1
      },
      "next": {
        "key": "gap:6:G-1",
        "kind": "gap",
        "ref": "G-1",
        "person": "meera",
        "label": "G-1 · gap",
        "title": "Is the retry budget per partner or global?",
        "overdue": false,
        "due_at": "2026-10-31T03:41:00Z"
      },
      "prs": {
        "total": 0,
        "approved": 0,
        "approved_refs": [],
        "stale": [],
        "with_pr": 0,
        "done": 0
      },
      "gate_draft": {
        "status": "BLOCKED",
        "state": "waiting",
        "failing_rules": [
          "no_open_decision_in_draft_scope",
          "no_open_gap_blocking_draft"
        ],
        "draft_rev": 2,
        "draft_status": "DRAFTING"
      },
      "baseline": null,
      "drift": null,
      "updated_at": "2026-10-30T03:41:00Z",
      "agents": {
        "queued": 1,
        "leased": 0,
        "holders": [],
        "working": [
          {
            "kind": "draft",
            "ref": null,
            "holder": null
          }
        ]
      }
    },
    "… (+5 more)"
  ],
  "waiting": [
    {
      "key": "gap:5:G-2",
      "kind": "gap",
      "initiative_id": 5,
      "initiative": "order-events",
      "initiative_title": "Order events for downstream consumers",
      "ref": "G-2",
      "route": {
        "person": "arjun",
        "role": "engg",
        "domain": "engg",
        "fallback": false
      },
      "person": "arjun",
      "since": "2026-10-30T05:41:00Z",
      "age_hours": 2.0,
      "sla_hours": 24,
      "due_at": "2026-10-31T05:41:00Z",
      "overdue": false,
      "priority": 10,
      "title": "The outbox table can't be added to the orders schema in time",
      "record": {
        "ref": "G-2",
        "type": "gap",
        "title": "The outbox table can't be added to the orders schema in time",
        "status": "OPEN",
        "pill": "red",
        "line": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
        "rev": 1,
        "fields": {
          "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
          "kind": "deviation",
          "domain": "engg",
          "level": "MUST",
          "asked_by": "runner-sdk/implement-task",
          "why_now": "Implementing T-1 hit the orders schema ownership rule: T-1 cannot finish as D-1 is written.",
          "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
          "options": [
            {
              "key": "separate-schema",
              "label": "Outbox in a separate schema",
              "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
            },
            {
              "key": "cdc",
              "label": "CDC via Debezium on the orders table",
              "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."
            },
            "… (+1 more)"
          ],
          "recommendation": "cdc",
          "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
          "blocks": [
            "D-1",
            "T-1"
          ],
          "proposed_change": "D-1 verdict: outbox → CDC via Debezium on the orders table. Add AC: CDC lag over 5 s for 2 min fires the alert. LLD event delivery section rewritten."
        },
        "created_by": "runner-sdk/implement-task",
        "created_at": "2026-10-30T05:41:00Z",
        "updated_by": "runner-sdk/implement-task",
        "updated_at": "2026-10-30T05:41:00Z"
      },
      "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
      "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
      "options": [
        {
          "key": "separate-schema",
          "label": "Outbox in a separate schema",
          "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
        },
        {
          "key": "cdc",
          "label": "CDC via Debezium on the orders table",
          "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."
        },
        "… (+1 more)"
      ],
      "recommendation": "cdc",
      "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
      "blocks": [
        "D-1",
        "T-1"
      ],
      "level": "MUST"
    },
    {
      "key": "approval:2:T-3",
      "kind": "approval",
      "initiative_id": 2,
      "initiative": "payouts-v2",
      "initiative_title": "Payouts v2: refunds ledger",
      "ref": "T-3",
      "route": {
        "person": "arjun",
        "role": "engg",
        "domain": null,
        "fallback": false
      },
      "person": "arjun",
      "since": "2026-10-29T04:41:00Z",
      "age_hours": 27.0,
      "sla_hours": 48,
      "due_at": "2026-10-31T04:41:00Z",
      "overdue": false,
      "priority": 20,
      "title": "Review the drift of T-3: Refunds ledger API",
      "gate": "GATE_PR",
      "role": "engg",
      "target": "T-3",
      "pr_url": "https://github.com/navanta/payouts-svc/pull/77",
      "pr_sha": "e19b0c4",
      "drift": {
        "changes": 1,
        "explained": 1,
        "unexplained": 0,
        "pending_gaps": 0,
        "pending_decisions": 0,
        "other_changes": 0
      },
      "digest": "aa08550c5085fccfd40c398a894c019678e5627b4bcfce8694fa0e4decf65bfa",
      "stale_approvals": []
    },
    "… (+6 more)"
  ],
  "decisions": [
    {
      "key": "gap:5:G-2",
      "kind": "gap",
      "initiative_id": 5,
      "initiative": "order-events",
      "initiative_title": "Order events for downstream consumers",
      "ref": "G-2",
      "route": {
        "person": "arjun",
        "role": "engg",
        "domain": "engg",
        "fallback": false
      },
      "person": "arjun",
      "since": "2026-10-30T05:41:00Z",
      "age_hours": 2.0,
      "sla_hours": 24,
      "due_at": "2026-10-31T05:41:00Z",
      "overdue": false,
      "priority": 10,
      "title": "The outbox table can't be added to the orders schema in time",
      "record": {
        "ref": "G-2",
        "type": "gap",
        "title": "The outbox table can't be added to the orders schema in time",
        "status": "OPEN",
        "pill": "red",
        "line": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
        "rev": 1,
        "fields": {
          "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
          "kind": "deviation",
          "domain": "engg",
          "level": "MUST",
          "asked_by": "runner-sdk/implement-task",
          "why_now": "Implementing T-1 hit the orders schema ownership rule: T-1 cannot finish as D-1 is written.",
          "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
          "options": [
            {
              "key": "separate-schema",
              "label": "Outbox in a separate schema",
              "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
            },
            {
              "key": "cdc",
              "label": "CDC via Debezium on the orders table",
              "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."
            },
            "… (+1 more)"
          ],
          "recommendation": "cdc",
          "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
          "blocks": [
            "D-1",
            "T-1"
          ],
          "proposed_change": "D-1 verdict: outbox → CDC via Debezium on the orders table. Add AC: CDC lag over 5 s for 2 min fires the alert. LLD event delivery section rewritten."
        },
        "created_by": "runner-sdk/implement-task",
        "created_at": "2026-10-30T05:41:00Z",
        "updated_by": "runner-sdk/implement-task",
        "updated_at": "2026-10-30T05:41:00Z"
      },
      "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
      "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
      "options": [
        {
          "key": "separate-schema",
          "label": "Outbox in a separate schema",
          "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
        },
        {
          "key": "cdc",
          "label": "CDC via Debezium on the orders table",
          "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."
        },
        "… (+1 more)"
      ],
      "recommendation": "cdc",
      "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
      "blocks": [
        "D-1",
        "T-1"
      ],
      "level": "MUST"
    },
    {
      "key": "review_item:2:22",
      "kind": "review_item",
      "initiative_id": 2,
      "initiative": "payouts-v2",
      "initiative_title": "Payouts v2: refunds ledger",
      "ref": "22",
      "route": {
        "person": "arjun",
        "role": "engg",
        "domain": "engg",
        "fallback": false
      },
      "person": "arjun",
      "since": "2026-10-29T11:41:00Z",
      "age_hours": 20.0,
      "sla_hours": 48,
      "due_at": "2026-10-31T11:41:00Z",
      "overdue": false,
      "priority": 30,
      "title": "D-2 ← G-1: does it still hold?",
      "review_item_id": 22,
      "target": "D-2",
      "cause": "G-1",
      "what_moved": "status OPEN → ANSWERED"
    },
    "… (+5 more)"
  ],
  "my_pr_approvals": [
    {
      "key": "approval:2:T-3",
      "kind": "approval",
      "initiative_id": 2,
      "initiative": "payouts-v2",
      "initiative_title": "Payouts v2: refunds ledger",
      "ref": "T-3",
      "route": {
        "person": "arjun",
        "role": "engg",
        "domain": null,
        "fallback": false
      },
      "person": "arjun",
      "since": "2026-10-29T04:41:00Z",
      "age_hours": 27.0,
      "sla_hours": 48,
      "due_at": "2026-10-31T04:41:00Z",
      "overdue": false,
      "priority": 20,
      "title": "Review the drift of T-3: Refunds ledger API",
      "gate": "GATE_PR",
      "role": "engg",
      "target": "T-3",
      "pr_url": "https://github.com/navanta/payouts-svc/pull/77",
      "pr_sha": "e19b0c4",
      "drift": {
        "changes": 1,
        "explained": 1,
        "unexplained": 0,
        "pending_gaps": 0,
        "pending_decisions": 0,
        "other_changes": 0
      },
      "digest": "aa08550c5085fccfd40c398a894c019678e5627b4bcfce8694fa0e4decf65bfa",
      "stale_approvals": []
    }
  ]
}
```

### POST /api/initiatives

**Start a feature** (the intake; `/new`). `requirement` (markdown), `title`, `dri`, `engg` are required; `slug` defaults from the title; `work_item_url` (Azure DevOps link), `product`, `design`, `qa`, `prd_refs` are optional. Pins `spec_snapshot` with its hash and writes the assignments. Returns the same body as `GET /api/initiatives/{id}` (`initiative.id` is the new id). 422 lists every missing field in `error_data.errors`; 409 if an explicit `slug` exists.

`POST /api/initiatives` — X-Actor: priya · X-Actor-Kind: human → **201**

Request:

```json
{
  "title": "Payment webhooks",
  "requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles.",
  "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
  "dri": "priya",
  "engg": "arjun",
  "product": "meera",
  "qa": "sam"
}
```

Response:

```json
{
  "initiative": {
    "id": 8,
    "slug": "payment-webhooks",
    "title": "Payment webhooks",
    "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
    "created_by": "priya",
    "created_at": "2026-10-30T07:41:34Z",
    "closed_at": null,
    "snapshot_hash": "a98a462dac3c82099ff1a3e5fd850ac1dcc41a30612f84ef9abb4c4661ff2d0d",
    "phase": "DRAFT",
    "pill": "amber",
    "summary": "",
    "spec_snapshot": {
      "requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles.",
      "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
      "created_by": "priya",
      "at": "2026-10-30T07:41:34Z"
    }
  },
  "phase": "DRAFT",
  "assignments": [
    {
      "ref": "A-1",
      "person": "priya",
      "role": "dri",
      "scope": [
        "initiative"
      ],
      "status": "ACTIVE"
    },
    {
      "ref": "A-2",
      "person": "arjun",
      "role": "engg",
      "scope": [
        "initiative"
      ],
      "status": "ACTIVE"
    },
    "… (+2 more)"
  ],
  "gates": [
    {
      "gate": "GATE_DRAFT",
      "scope": "initiative",
      "target": null,
      "status": "BLOCKED",
      "human_role": "dri",
      "text": "Touchpoint 1 — the DRI approves the draft; approval creates baseline B-n",
      "rules": [
        {
          "name": "no_open_decision_in_draft_scope",
          "passed": true,
          "failing": [],
          "detail": "",
          "args": {}
        },
        {
          "name": "no_open_gap_blocking_draft",
          "passed": true,
          "failing": [],
          "detail": "",
          "args": {}
        },
        "… (+5 more)"
      ],
      "note": "",
      "failing_rules": [
        "catalog_addressed",
        "approval_by_role"
      ]
    },
    {
      "gate": "GATE_VALIDATED",
      "scope": "initiative",
      "target": null,
      "status": "BLOCKED",
      "human_role": null,
      "text": "Derived — every live AC green (scoped to the task's ACs when deploy_guard asks), manual ACs signed by QA, no open blocker",
      "rules": [
        {
          "name": "every_ac_green",
          "passed": false,
          "failing": [],
          "detail": "no live acceptance criteria yet",
          "args": {}
        },
        {
          "name": "manual_acs_signed_by",
          "passed": true,
          "failing": [],
          "detail": "",
          "args": {
            "role": "qa"
          }
        },
        "… (+1 more)"
      ],
      "note": "",
      "failing_rules": [
        "every_ac_green"
      ]
    }
  ],
  "tasks": [],
  "counts": {
    "initiative": {
      "DRAFT": 1
    },
    "assignment": {
      "ACTIVE": 4
    }
  },
  "open": {
    "decisions": [],
    "gaps": [],
    "review_items": 0
  },
  "stuck": [],
  "baseline": null,
  "drift": null,
  "stale": [],
  "catalog": {
    "intake": [
      {
        "item": "dri_assigned",
        "phase": "intake",
        "text": "an ACTIVE dri assignment",
        "derived": true,
        "disposition": "addressed",
        "note": "",
        "refs": ""
      },
      {
        "item": "engg_assigned",
        "phase": "intake",
        "text": "an ACTIVE engg assignment",
        "derived": true,
        "disposition": "addressed",
        "note": "",
        "refs": ""
      },
      "… (+1 more)"
    ],
    "draft": [
      {
        "item": "security_review",
        "phase": "draft",
        "text": "threats, data classification, authn/z touched",
        "derived": false,
        "disposition": "UNASSESSED",
        "note": "",
        "refs": ""
      },
      {
        "item": "rollback_plan",
        "phase": "draft",
        "text": "how a bad deploy is undone",
        "derived": false,
        "disposition": "UNASSESSED",
        "note": "",
        "refs": ""
      },
      "… (+3 more)"
    ],
    "plan": [
      {
        "item": "every_ac_covered_by_a_task",
        "phase": "plan",
        "text": "each live AC is in some task's covers",
        "derived": true,
        "disposition": "UNASSESSED",
        "note": "",
        "refs": ""
      },
      {
        "item": "every_task_has_template",
        "phase": "plan",
        "text": "each task names its paved-road template",
        "derived": true,
        "disposition": "UNASSESSED",
        "note": "",
        "refs": ""
      }
    ],
    "build": []
  }
}
```

### GET /api/initiatives/5

**Initiative state**: the initiative with its `spec_snapshot`, `phase`, assignments, initiative-scope gates (rule by rule), tasks with their GATE_PR status and drift summary, counts by type and status, open refs, the current baseline, drift summary, stale narratives, and every catalog (phase → items with `disposition`: `addressed` · `not_applicable` · `UNASSESSED`).

`GET /api/initiatives/5` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "initiative": {
    "id": 5,
    "slug": "order-events",
    "title": "Order events for downstream consumers",
    "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4821",
    "created_by": "priya",
    "created_at": "2026-10-24T07:41:00Z",
    "closed_at": null,
    "snapshot_hash": "0cd67b2220cbd2fc69ae3c5323d37a804d69bae80dfb18441708da9c20291b94",
    "phase": "BUILD",
    "pill": "amber",
    "summary": "",
    "spec_snapshot": {
      "requirement": "# Order events for downstream consumers\n\nNotifications-svc polls the orders database every minute to find new and cancelled orders.\nEmails go out late, and the polling query is the orders DB's top loa…",
      "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4821",
      "created_by": "priya",
      "at": "2026-10-24T07:41:00Z"
    }
  },
  "phase": "BUILD",
  "assignments": [
    {
      "ref": "A-1",
      "person": "priya",
      "role": "dri",
      "scope": [
        "initiative"
      ],
      "status": "ACTIVE"
    },
    {
      "ref": "A-2",
      "person": "arjun",
      "role": "engg",
      "scope": [
        "initiative"
      ],
      "status": "ACTIVE"
    },
    {
      "ref": "A-3",
      "person": "meera",
      "role": "product",
      "scope": [
        "initiative"
      ],
      "status": "ACTIVE"
    },
    "… (+1 more)"
  ],
  "gates": [
    {
      "gate": "GATE_DRAFT",
      "scope": "initiative",
      "target": null,
      "status": "PASSED",
      "human_role": "dri",
      "text": "Touchpoint 1 — the DRI approves the draft; approval creates baseline B-n",
      "rules": [
        {
          "name": "no_open_decision_in_draft_scope",
          "passed": true,
          "failing": [],
          "detail": "",
          "args": {}
        },
        {
          "name": "no_open_gap_blocking_draft",
          "passed": false,
          "failing": [
            "G-2"
          ],
          "detail": "OPEN gaps block the spec",
          "args": {}
        },
        {
          "name": "no_open_review_items_on_spec",
          "passed": true,
          "failing": [],
          "detail": "",
          "args": {}
        },
        "… (+4 more)"
      ],
      "note": "approved; preconditions that fail now are mid-build work, not a reopened draft",
      "failing_rules": [
        "no_open_gap_blocking_draft"
      ]
    },
    {
      "gate": "GATE_VALIDATED",
      "scope": "initiative",
      "target": null,
      "status": "BLOCKED",
      "human_role": null,
      "text": "Derived — every live AC green (scoped to the task's ACs when deploy_guard asks), manual ACs signed by QA, no open blocker",
      "rules": [
        {
          "name": "every_ac_green",
          "passed": false,
          "failing": [
            "AC-1",
            "AC-2",
            "AC-3",
            "… (+2 more)"
          ],
          "detail": "ACs whose latest run at the PR head / deploying sha is not GREEN",
          "args": {}
        },
        {
          "name": "manual_acs_signed_by",
          "passed": false,
          "failing": [
            "AC-6"
          ],
          "detail": "manual ACs not signed by qa",
          "args": {
            "role": "qa"
          }
        },
        {
          "name": "no_blocker_finding_open",
          "passed": true,
          "failing": [],
          "detail": "",
          "args": {}
        }
      ],
      "note": "",
      "failing_rules": [
        "every_ac_green",
        "manual_acs_signed_by"
      ]
    }
  ],
  "tasks": [
    {
      "ref": "T-1",
      "type": "task",
      "title": "Outbox table and relay",
      "status": "BLOCKED",
      "pill": "red",
      "line": "Write the event row in the order transaction and relay it to orders.events",
      "rev": 1,
      "fields": {
        "goal": "Write the event row in the order transaction and relay it to orders.events",
        "repo": "orders-service",
        "template": "python-service-v3",
        "implements": [
          "D-1"
        ],
        "covers": [
          "AC-2",
          "AC-3"
        ],
        "rollback": "Revert the PR; the change is behind a flag."
      },
      "created_by": "runner-sdk/plan-to-tasks",
      "created_at": "2026-10-25T11:41:00Z",
      "updated_by": "runner-sdk/plan-to-tasks",
      "updated_at": "2026-10-25T11:41:00Z",
      "gate_pr": {
        "status": "BLOCKED",
        "failing_rules": [
          "pr_state_in",
          "every_covered_ac_has_a_test",
          "approval_by_role"
        ]
      },
      "drift": {
        "changes": 0,
        "explained": 0,
        "unexplained": 0,
        "pending_gaps": 1,
        "pending_decisions": 0,
        "other_changes": 0
      }
    },
    {
      "ref": "T-2",
      "type": "task",
      "title": "Emit created and cancelled",
      "status": "BLOCKED",
      "pill": "red",
      "line": "Publish order.created and order.cancelled envelopes",
      "rev": 1,
      "fields": {
        "goal": "Publish order.created and order.cancelled envelopes",
        "repo": "orders-service",
        "template": "python-service-v3",
        "implements": [
          "D-1",
          "D-2"
        ],
        "covers": [
          "AC-1",
          "AC-7"
        ],
        "depends_on": [
          "T-1"
        ],
        "rollback": "Revert the PR; the change is behind a flag."
      },
      "created_by": "runner-sdk/plan-to-tasks",
      "created_at": "2026-10-25T11:41:00Z",
      "updated_by": "runner-sdk/plan-to-tasks",
      "updated_at": "2026-10-25T11:41:00Z",
      "gate_pr": {
        "status": "BLOCKED",
        "failing_rules": [
          "pr_state_in",
          "every_covered_ac_has_a_test",
          "approval_by_role"
        ]
      },
      "drift": {
        "changes": 0,
        "explained": 0,
        "unexplained": 0,
        "pending_gaps": 1,
        "pending_decisions": 0,
        "other_changes": 0
      }
    },
    {
      "ref": "T-3",
      "type": "task",
      "title": "Topic, IAM and lag dashboard",
      "status": "IN_REVIEW",
      "pill": "amber",
      "line": "Create orders.events, the notifications-svc read role and the lag dashboard",
      "rev": 2,
      "fields": {
        "goal": "Create orders.events, the notifications-svc read role and the lag dashboard",
        "repo": "infra-terraform",
        "template": "terraform-module",
        "implements": [
          "D-1"
        ],
        "covers": [
          "AC-4",
          "AC-6"
        ],
        "rollback": "terraform destroy of the new module; nothing else depends on it yet.",
        "pr_url": "https://github.com/navanta/infra-terraform/pull/212",
        "pr_state": "open",
        "pr_sha": "a41c09e",
        "ci_attempts": "1",
        "review_rounds": "1"
      },
      "created_by": "runner-sdk/plan-to-tasks",
      "created_at": "2026-10-25T11:41:00Z",
      "updated_by": "runner-sdk/implement-task",
      "updated_at": "2026-10-28T07:41:00Z",
      "gate_pr": {
        "status": "PASSED",
        "failing_rules": []
      },
      "drift": {
        "changes": 0,
        "explained": 0,
        "unexplained": 0,
        "pending_gaps": 1,
        "pending_decisions": 0,
        "other_changes": 0
      }
    },
    "… (+1 more)"
  ],
  "counts": {
    "initiative": {
      "BUILD": 1
    },
    "assignment": {
      "ACTIVE": 4
    },
    "draft": {
      "APPROVED": 1
    },
    "decision": {
      "DECIDED": 1,
      "PROVISIONAL": 1
    },
    "gap": {
      "ANSWERED": 1,
      "OPEN": 1
    },
    "acceptance_criterion": {
      "APPROVED": 7
    },
    "task": {
      "BLOCKED": 3,
      "IN_REVIEW": 1
    },
    "finding": {
      "FIXED": 1
    },
    "test_run": {
      "GREEN": 1
    },
    "approval": {
      "CURRENT": 2
    },
    "baseline": {
      "CURRENT": 1
    }
  },
  "open": {
    "decisions": [],
    "gaps": [
      "G-2"
    ],
    "review_items": 0
  },
  "stuck": [],
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 3 approved by priya",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "priya",
    "draft_rev": "3",
    "members": [
      "draft",
      "D-1",
      "D-2",
      "… (+8 more)"
    ],
    "created_at": "2026-10-25T09:41:00Z"
  },
  "drift": {
    "changes": 0,
    "explained": 0,
    "unexplained": 0,
    "pending_gaps": 1,
    "pending_decisions": 0,
    "other_changes": 0
  },
  "stale": [
    "draft.summary"
  ],
  "catalog": {
    "intake": [
      {
        "item": "dri_assigned",
        "phase": "intake",
        "text": "an ACTIVE dri assignment",
        "derived": true,
        "disposition": "addressed",
        "note": "",
        "refs": ""
      },
      {
        "item": "engg_assigned",
        "phase": "intake",
        "text": "an ACTIVE engg assignment",
        "derived": true,
        "disposition": "addressed",
        "note": "",
        "refs": ""
      },
      {
        "item": "requirement_snapshotted",
        "phase": "intake",
        "text": "spec_snapshot pinned with its hash",
        "derived": true,
        "disposition": "addressed",
        "note": "",
        "refs": ""
      }
    ],
    "draft": [
      {
        "item": "security_review",
        "phase": "draft",
        "text": "threats, data classification, authn/z touched",
        "derived": false,
        "disposition": "addressed",
        "note": "AC-4: only notifications-svc reads the topic; payloads carry ids and states only.",
        "refs": ""
      },
      {
        "item": "rollback_plan",
        "phase": "draft",
        "text": "how a bad deploy is undone",
        "derived": false,
        "disposition": "addressed",
        "note": "HLD: stop the relay; the event table is additive.",
        "refs": ""
      },
      {
        "item": "observability",
        "phase": "draft",
        "text": "metrics, logs, alerts that show it works",
        "derived": false,
        "disposition": "addressed",
        "note": "AC-6: publish lag per topic on the ops dashboard.",
        "refs": ""
      },
      "… (+2 more)"
    ],
    "plan": [
      {
        "item": "every_ac_covered_by_a_task",
        "phase": "plan",
        "text": "each live AC is in some task's covers",
        "derived": true,
        "disposition": "addressed",
        "note": "",
        "refs": ""
      },
      {
        "item": "every_task_has_template",
        "phase": "plan",
        "text": "each task names its paved-road template",
        "derived": true,
        "disposition": "addressed",
        "note": "",
        "refs": ""
      }
    ],
    "build": []
  }
}
```

### GET /api/initiatives/6/draft

**Draft review page** (touchpoint 1). `can_approve`, `approval_blockers[{rule, failing, detail}]` and `approver` drive the Approve button.

`GET /api/initiatives/6/draft` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "initiative": {
    "id": 6,
    "slug": "menu-sync-retries",
    "title": "Menu sync retries",
    "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4833",
    "created_by": "priya",
    "created_at": "2026-10-29T05:41:00Z",
    "closed_at": null,
    "snapshot_hash": "3097d30d3c0ef5cc69b40b07b6ffb41959ba287e244ebe43959366e39c6a7030",
    "phase": "DRAFT",
    "pill": "amber",
    "summary": "",
    "spec_snapshot": {
      "requirement": "# Menu sync retries\nMenu pushes to partners fail on timeouts and are never retried, so stores show stale menus until someone pushes again by hand.\n\n**Done:** failed pushes retry on their own and no st…",
      "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4833",
      "created_by": "priya",
      "at": "2026-10-29T05:41:00Z"
    }
  },
  "draft": {
    "ref": "draft",
    "type": "draft",
    "title": "Draft",
    "status": "DRAFTING",
    "pill": "amber",
    "line": null,
    "rev": 2,
    "fields": {
      "problem": "Menu pushes to partners fail on timeouts and are never retried, so stores show stale menus until someone pushes again by hand. Done means failed pushes retry on their own and no store shows a menu mor…",
      "hld": "Failed pushes go to a delayed queue in the menu-sync worker (D-1) with exponential backoff and jitter, as STD-2 requires. A retry budget (D-2, scope pending G-1) stops one partner from flooding the qu…",
      "lld": "- `retry_queue(partner_id, menu_version, attempt, next_at)`\n- Backoff 30 s, 2 min, 8 min with ±20% jitter.\n- Each push carries menu_version; the partner adapter drops any version older than the last o…",
      "scope_in": [
        "retries for menu pushes",
        "the budget",
        "… (+2 more)"
      ],
      "scope_out": [
        "retries for order or inventory pushes",
        "partner-side changes"
      ],
      "test_strategy": "Integration: a fake partner that times out N times, checking retries, ordering and the alert. Unit: backoff schedule and version ordering. Manual: QA checks the queue-depth panel.",
      "decisions": [
        "D-1",
        "D-2"
      ],
      "criteria": [
        "AC-1",
        "AC-2",
        "… (+2 more)"
      ]
    },
    "created_by": "runner-sdk/draft-from-ticket",
    "created_at": "2026-10-29T07:41:00Z",
    "updated_by": "runner-sdk/draft-from-ticket",
    "updated_at": "2026-10-30T03:41:00Z",
    "links": {
      "out": [
        {
          "kind": "contains",
          "to": "D-1"
        },
        {
          "kind": "contains",
          "to": "D-2"
        },
        "… (+8 more)"
      ],
      "in": [
        {
          "kind": "blocks",
          "from": "G-1"
        }
      ]
    },
    "stamps": {
      "problem": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-29T07:41:00"
      },
      "hld": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-30T03:41:00"
      },
      "lld": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-29T07:41:00"
      },
      "scope_in": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-29T07:41:00"
      },
      "scope_out": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-29T07:41:00"
      },
      "test_strategy": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-29T07:41:00"
      },
      "decisions": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-29T07:41:00"
      },
      "criteria": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-29T07:41:00"
      }
    },
    "stale": [],
    "review_items": []
  },
  "decisions": [
    {
      "ref": "D-1",
      "type": "decision",
      "title": "Delayed queue in the menu-sync worker",
      "status": "DECIDED",
      "pill": "green",
      "line": "Delayed queue in the menu-sync worker",
      "rev": 1,
      "fields": {
        "question": "Where do retries run?",
        "domain": "engg",
        "level": "SHOULD",
        "options": [
          {
            "name": "delayed queue",
            "consequences": "Reuses the worker; backoff is a queue delay",
            "cost_risk": "low"
          },
          {
            "name": "cron re-push",
            "consequences": "Simple; menus can be up to 15 minutes stale",
            "cost_risk": "staleness"
          },
          "… (+1 more)"
        ],
        "verdict": "Delayed queue in the menu-sync worker",
        "rationale": "Cites STD-2 retries with backoff and jitter; reuses the worker.",
        "decided_by": "runner-sdk/draft-skill",
        "decided_on": "2026-10-29"
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-29T07:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-29T07:41:00Z",
      "links": {
        "out": [
          {
            "kind": "mentions",
            "to": "STD-2"
          }
        ],
        "in": [
          {
            "kind": "contains",
            "from": "draft"
          },
          {
            "kind": "mentions",
            "from": "draft"
          },
          "… (+2 more)"
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "domain": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "options": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "verdict": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "rationale": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "decided_by": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "decided_on": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        }
      },
      "stale": [],
      "review_items": [],
      "superseded_by": [],
      "sourced_acs": [
        "AC-1",
        "AC-3"
      ]
    },
    {
      "ref": "D-2",
      "type": "decision",
      "title": "Retry budget scope",
      "status": "OPEN",
      "pill": "red",
      "line": null,
      "rev": 1,
      "fields": {
        "question": "What does the retry budget cover?",
        "domain": "product",
        "level": "SHOULD",
        "options": [
          {
            "name": "per partner",
            "consequences": "One flaky partner can't use up retries for everyone",
            "cost_risk": "config per partner"
          },
          {
            "name": "global",
            "consequences": "Simpler to run",
            "cost_risk": "one partner can starve the others"
          }
        ]
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-29T07:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-29T07:41:00Z",
      "links": {
        "out": [],
        "in": [
          {
            "kind": "blocks",
            "from": "G-1"
          },
          {
            "kind": "contains",
            "from": "draft"
          },
          "… (+3 more)"
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "domain": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "options": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        }
      },
      "stale": [],
      "review_items": [],
      "superseded_by": [],
      "sourced_acs": [
        "AC-2"
      ]
    }
  ],
  "criteria": [
    {
      "ref": "AC-1",
      "type": "acceptance_criterion",
      "title": "Given a push times out, then it is retried with backoff at most 3 times within 15 minutes",
      "status": "PROPOSED",
      "pill": "amber",
      "line": "Given a push times out, then it is retried with backoff at most 3 times within 15 minutes",
      "rev": 2,
      "fields": {
        "text": "Given a push times out, then it is retried with backoff at most 3 times within 15 minutes",
        "level": "integration",
        "source": [
          "D-1"
        ]
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-29T07:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-30T03:41:00Z",
      "links": {
        "out": [
          {
            "kind": "source",
            "to": "D-1"
          }
        ],
        "in": [
          {
            "kind": "contains_ac",
            "from": "draft"
          }
        ]
      },
      "stamps": {
        "text": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "source": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        }
      },
      "stale": [],
      "review_items": []
    },
    {
      "ref": "AC-2",
      "type": "acceptance_criterion",
      "title": "Given the retry budget runs out, then the partner is flagged and on-call is alerted",
      "status": "PROPOSED",
      "pill": "amber",
      "line": "Given the retry budget runs out, then the partner is flagged and on-call is alerted",
      "rev": 2,
      "fields": {
        "text": "Given the retry budget runs out, then the partner is flagged and on-call is alerted",
        "level": "integration",
        "source": [
          "D-2"
        ]
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-29T07:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-30T03:41:00Z",
      "links": {
        "out": [
          {
            "kind": "source",
            "to": "D-2"
          }
        ],
        "in": [
          {
            "kind": "contains_ac",
            "from": "draft"
          },
          {
            "kind": "mentions",
            "from": "initiative"
          }
        ]
      },
      "stamps": {
        "text": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        },
        "source": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-29T07:41:00"
        }
      },
      "stale": [],
      "review_items": []
    },
    "… (+2 more)"
  ],
  "gaps": [
    {
      "ref": "G-1",
      "type": "gap",
      "title": "Is the retry budget per partner or global?",
      "status": "OPEN",
      "pill": "red",
      "line": "Is the retry budget per partner or global?",
      "rev": 1,
      "fields": {
        "question": "Is the retry budget per partner or global?",
        "kind": "unknown",
        "domain": "product",
        "level": "MUST",
        "asked_by": "runner-sdk/draft-from-ticket",
        "why_now": "D-2 cannot be decided without it, and the draft cannot be approved with D-2 open.",
        "context": "STD-2 requires a retry budget but doesn't say what it covers. Partners differ a lot in how often their APIs time out.",
        "options": [
          {
            "key": "per-partner",
            "label": "Per partner",
            "consequence": "One flaky partner can't use up retries for everyone. Needs a budget per partner in config."
          },
          {
            "key": "global",
            "label": "Global",
            "consequence": "Simpler to run. One flaky partner can starve the others."
          }
        ],
        "recommendation": "per-partner",
        "recommendation_why": "Partner timeouts are very uneven; a global budget lets one partner starve the rest.",
        "blocks": [
          "D-2",
          "draft"
        ]
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-30T03:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-30T03:41:00Z",
      "links": {
        "out": [
          {
            "kind": "blocks",
            "to": "D-2"
          },
          {
            "kind": "blocks",
            "to": "draft"
          },
          "… (+2 more)"
        ],
        "in": [
          {
            "kind": "mentions",
            "from": "draft"
          }
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "kind": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "domain": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "asked_by": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "why_now": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "context": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "options": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "recommendation": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "recommendation_why": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        },
        "blocks": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-30T03:41:00"
        }
      },
      "stale": [],
      "review_items": []
    }
  ],
  "catalog": [
    {
      "item": "security_review",
      "phase": "draft",
      "text": "threats, data classification, authn/z touched",
      "derived": false,
      "disposition": "not_applicable",
      "note": "No new access.",
      "refs": ""
    },
    {
      "item": "rollback_plan",
      "phase": "draft",
      "text": "how a bad deploy is undone",
      "derived": false,
      "disposition": "addressed",
      "note": "Flag menu_retries.",
      "refs": ""
    },
    "… (+3 more)"
  ],
  "gate": {
    "gate": "GATE_DRAFT",
    "scope": "initiative",
    "target": null,
    "status": "BLOCKED",
    "human_role": "dri",
    "text": "Touchpoint 1 — the DRI approves the draft; approval creates baseline B-n",
    "rules": [
      {
        "name": "no_open_decision_in_draft_scope",
        "passed": false,
        "failing": [
          "D-2"
        ],
        "detail": "decisions still OPEN (a PROVISIONAL SHOULD passes)",
        "args": {}
      },
      {
        "name": "no_open_gap_blocking_draft",
        "passed": false,
        "failing": [
          "G-1"
        ],
        "detail": "OPEN gaps block the spec",
        "args": {}
      },
      "… (+5 more)"
    ],
    "note": "",
    "failing_rules": [
      "no_open_decision_in_draft_scope",
      "no_open_gap_blocking_draft",
      "… (+1 more)"
    ]
  },
  "can_approve": false,
  "approver": "priya",
  "approval_blockers": [
    {
      "rule": "no_open_decision_in_draft_scope",
      "failing": [
        "D-2"
      ],
      "detail": "decisions still OPEN (a PROVISIONAL SHOULD passes)"
    },
    {
      "rule": "no_open_gap_blocking_draft",
      "failing": [
        "G-1"
      ],
      "detail": "OPEN gaps block the spec"
    }
  ],
  "approvals": [],
  "baselines": [],
  "review_items": []
}
```

### GET /api/initiatives/5/draft (approved)

The same page once approved: `gate.status` PASSED, `baselines[]`, `approvals[]`; D-1 shows `superseded_by: ["D-4"]`.

`GET /api/initiatives/5/draft` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "initiative": {
    "id": 5,
    "slug": "order-events",
    "title": "Order events for downstream consumers",
    "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4821",
    "created_by": "priya",
    "created_at": "2026-10-24T07:41:00Z",
    "closed_at": null,
    "snapshot_hash": "0cd67b2220cbd2fc69ae3c5323d37a804d69bae80dfb18441708da9c20291b94",
    "phase": "BUILD",
    "pill": "amber",
    "summary": "",
    "spec_snapshot": {
      "requirement": "# Order events for downstream consumers\n\nNotifications-svc polls the orders database every minute to find new and cancelled orders.\nEmails go out late, and the polling query is the orders DB's top loa…",
      "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4821",
      "created_by": "priya",
      "at": "2026-10-24T07:41:00Z"
    }
  },
  "draft": {
    "ref": "draft",
    "type": "draft",
    "title": "Draft",
    "status": "APPROVED",
    "pill": "green",
    "line": null,
    "rev": 3,
    "fields": {
      "summary": "Order changes and an event row commit together (D-1); a relay publishes versioned envelopes (D-2) to orders.events.",
      "problem": "Notifications-svc polls the orders database every minute to find new and cancelled orders. Emails go out late, and the polling query is the orders DB's top load. Done means consumers receive order.cre…",
      "hld": "orders-service writes each order change and an event row in one transaction (D-1). A relay publishes event rows to the `orders.events` topic and marks them sent. Events use a versioned envelope (D-2).…",
      "lld": "- `order_events(id, order_id, type, payload, created_at, sent_at)`\n- Event delivery: a relay polls unsent rows every 200 ms in batches of 500, publishes with key = order_id, and sets `sent_at` after t…",
      "scope_in": [
        "order.created and order.cancelled",
        "the orders.events topic",
        "… (+2 more)"
      ],
      "scope_out": [
        "refund events",
        "backfilling historical orders",
        "… (+1 more)"
      ],
      "test_strategy": "Unit: envelope and dedupe logic. Integration: relay against a real broker, including a 10-minute outage (AC-3). Manual: QA checks the lag dashboard in the test environment. Every criterion maps to at …",
      "decisions": [
        "D-1",
        "D-2"
      ],
      "criteria": [
        "AC-1",
        "AC-2",
        "… (+5 more)"
      ],
      "submitted_rev": "3"
    },
    "created_by": "runner-sdk/draft-from-ticket",
    "created_at": "2026-10-24T09:41:00Z",
    "updated_by": "runner-sdk/draft-from-ticket",
    "updated_at": "2026-10-25T02:41:00Z",
    "links": {
      "out": [
        {
          "kind": "contains",
          "to": "D-1"
        },
        {
          "kind": "contains",
          "to": "D-2"
        },
        "… (+10 more)"
      ],
      "in": [
        {
          "kind": "approves",
          "from": "APR-1"
        },
        {
          "kind": "blocks",
          "from": "G-1"
        }
      ]
    },
    "stamps": {
      "summary": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-24T09:41:00"
      },
      "problem": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-24T09:41:00"
      },
      "hld": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-24T09:41:00"
      },
      "lld": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-24T09:41:00"
      },
      "scope_in": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-24T09:41:00"
      },
      "scope_out": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-24T09:41:00"
      },
      "test_strategy": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-24T12:41:00"
      },
      "decisions": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-24T09:41:00"
      },
      "criteria": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-25T02:41:00"
      },
      "submitted_rev": {
        "by": "runner-sdk/draft-from-ticket",
        "kind": "agent",
        "at": "2026-10-25T02:41:00"
      }
    },
    "stale": [
      "summary"
    ],
    "review_items": []
  },
  "decisions": [
    {
      "ref": "D-1",
      "type": "decision",
      "title": "Transactional outbox",
      "status": "DECIDED",
      "pill": "green",
      "line": "Transactional outbox",
      "rev": 2,
      "fields": {
        "question": "How do order events reach consumers?",
        "domain": "engg",
        "level": "MUST",
        "options": [
          {
            "name": "outbox",
            "consequences": "Extra table and relay; exactly-once to the broker",
            "cost_risk": "one table, one relay process"
          },
          {
            "name": "dual-write",
            "consequences": "Simple; loses events on partial failure (breaks STD-1)",
            "cost_risk": "lost events"
          },
          "… (+1 more)"
        ],
        "verdict": "Transactional outbox",
        "rationale": "STD-1 needs exactly-once to the broker; dual-write breaks it and CDC is not set up on orders. Menu sync (D-55) chose the same.",
        "provisional": "no",
        "decided_by": "priya",
        "decided_on": "2026-10-24"
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-24T09:41:00Z",
      "updated_by": "priya",
      "updated_at": "2026-10-24T16:41:00Z",
      "links": {
        "out": [
          {
            "kind": "mentions",
            "to": "STD-1"
          }
        ],
        "in": [
          {
            "kind": "blocks",
            "from": "G-2"
          },
          {
            "kind": "contains",
            "from": "draft"
          },
          "… (+10 more)"
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "domain": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "options": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "verdict": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-24T16:41:00"
        },
        "rationale": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-24T16:41:00"
        },
        "provisional": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-24T16:41:00"
        },
        "decided_by": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-24T16:41:00"
        },
        "decided_on": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-24T16:41:00"
        }
      },
      "stale": [],
      "review_items": [],
      "superseded_by": [],
      "sourced_acs": [
        "AC-1",
        "AC-2",
        "… (+3 more)"
      ]
    },
    {
      "ref": "D-2",
      "type": "decision",
      "title": "Event envelope with schema_version",
      "status": "PROVISIONAL",
      "pill": "amber",
      "line": "Envelope with schema_version, additive changes only",
      "rev": 1,
      "fields": {
        "question": "How are event schemas versioned?",
        "domain": "engg",
        "level": "SHOULD",
        "verdict": "Envelope with schema_version, additive changes only",
        "rationale": "Follows the default menu-sync chose (D-55 there). A human answer later would supersede it.",
        "provisional": "yes",
        "decided_by": "runner-sdk/draft-skill",
        "decided_on": "2026-10-24"
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-24T09:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-24T09:41:00Z",
      "links": {
        "out": [],
        "in": [
          {
            "kind": "contains",
            "from": "draft"
          },
          {
            "kind": "implements",
            "from": "T-2"
          },
          "… (+3 more)"
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "domain": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "verdict": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "rationale": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "provisional": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "decided_by": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "decided_on": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        }
      },
      "stale": [],
      "review_items": [],
      "superseded_by": [],
      "sourced_acs": [
        "AC-5"
      ]
    }
  ],
  "criteria": [
    {
      "ref": "AC-1",
      "type": "acceptance_criterion",
      "title": "Given an order commits, when the relay runs, then order.created is published once",
      "status": "APPROVED",
      "pill": "green",
      "line": "Given an order commits, when the relay runs, then order.created is published once",
      "rev": 1,
      "fields": {
        "text": "Given an order commits, when the relay runs, then order.created is published once",
        "level": "integration",
        "source": [
          "D-1"
        ]
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-24T09:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-24T09:41:00Z",
      "links": {
        "out": [
          {
            "kind": "source",
            "to": "D-1"
          }
        ],
        "in": [
          {
            "kind": "contains_ac",
            "from": "draft"
          },
          {
            "kind": "covers",
            "from": "T-2"
          }
        ]
      },
      "stamps": {
        "text": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "source": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        }
      },
      "stale": [],
      "review_items": []
    },
    {
      "ref": "AC-2",
      "type": "acceptance_criterion",
      "title": "Given an order write, then its event row is written in the same transaction",
      "status": "APPROVED",
      "pill": "green",
      "line": "Given an order write, then its event row is written in the same transaction",
      "rev": 1,
      "fields": {
        "text": "Given an order write, then its event row is written in the same transaction",
        "level": "unit",
        "source": [
          "D-1"
        ]
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-24T09:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-24T09:41:00Z",
      "links": {
        "out": [
          {
            "kind": "source",
            "to": "D-1"
          }
        ],
        "in": [
          {
            "kind": "contains_ac",
            "from": "draft"
          },
          {
            "kind": "covers",
            "from": "T-1"
          }
        ]
      },
      "stamps": {
        "text": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "source": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        }
      },
      "stale": [],
      "review_items": []
    },
    "… (+5 more)"
  ],
  "gaps": [
    {
      "ref": "G-1",
      "type": "gap",
      "title": "Do cancelled orders emit events?",
      "status": "ANSWERED",
      "pill": "green",
      "line": "Do cancelled orders emit events?",
      "rev": 3,
      "fields": {
        "question": "Do cancelled orders emit events?",
        "kind": "unknown",
        "domain": "product",
        "level": "MUST",
        "asked_by": "runner-sdk/draft-skill",
        "why_now": "The event list in the HLD depends on it.",
        "context": "The requirement names `order.created` and `order.cancelled`, but refunds after cancellation are a separate flow.",
        "options": [
          {
            "key": "yes",
            "label": "Yes, refunds out of scope",
            "consequence": "order.cancelled published; refunds stay out"
          },
          {
            "key": "no",
            "label": "No, created only",
            "consequence": "notifications keeps polling for cancellations"
          }
        ],
        "recommendation": "yes",
        "recommendation_why": "The requirement names order.cancelled.",
        "blocks": [
          "draft"
        ],
        "answer": "Yes — cancellations matter for notifications; refunds are out of scope.",
        "choice": "yes",
        "answered_by": "meera",
        "answered_on": "2026-10-25T01:41:00Z",
        "assigned_to": "meera",
        "assigned_role": "product",
        "answered_via": "web",
        "resolution": "AC-7 added; order.cancelled is in scope."
      },
      "created_by": "runner-sdk/draft-from-ticket",
      "created_at": "2026-10-24T09:41:00Z",
      "updated_by": "runner-sdk/draft-from-ticket",
      "updated_at": "2026-10-25T02:41:00Z",
      "links": {
        "out": [
          {
            "kind": "blocks",
            "to": "draft"
          },
          {
            "kind": "mentions",
            "to": "AC-7"
          }
        ],
        "in": [
          {
            "kind": "because",
            "from": "AC-7"
          }
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "kind": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "domain": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "level": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "asked_by": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "why_now": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "context": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "options": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "recommendation": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "recommendation_why": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "blocks": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-24T09:41:00"
        },
        "answer": {
          "by": "meera",
          "kind": "human",
          "at": "2026-10-25T01:41:00"
        },
        "choice": {
          "by": "meera",
          "kind": "human",
          "at": "2026-10-25T01:41:00"
        },
        "answered_by": {
          "by": "meera",
          "kind": "human",
          "at": "2026-10-25T01:41:00"
        },
        "answered_on": {
          "by": "meera",
          "kind": "human",
          "at": "2026-10-25T01:41:00"
        },
        "assigned_to": {
          "by": "meera",
          "kind": "human",
          "at": "2026-10-25T01:41:00"
        },
        "assigned_role": {
          "by": "meera",
          "kind": "human",
          "at": "2026-10-25T01:41:00"
        },
        "answered_via": {
          "by": "meera",
          "kind": "human",
          "at": "2026-10-25T01:41:00"
        },
        "resolution": {
          "by": "runner-sdk/draft-from-ticket",
          "kind": "agent",
          "at": "2026-10-25T02:41:00"
        }
      },
      "stale": [],
      "review_items": []
    },
    {
      "ref": "G-2",
      "type": "gap",
      "title": "The outbox table can't be added to the orders schema in time",
      "status": "OPEN",
      "pill": "red",
      "line": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
      "rev": 1,
      "fields": {
        "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
        "kind": "deviation",
        "domain": "engg",
        "level": "MUST",
        "asked_by": "runner-sdk/implement-task",
        "why_now": "Implementing T-1 hit the orders schema ownership rule: T-1 cannot finish as D-1 is written.",
        "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
        "options": [
          {
            "key": "separate-schema",
            "label": "Outbox in a separate schema",
            "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
          },
          {
            "key": "cdc",
            "label": "CDC via Debezium on the orders table",
            "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."
          },
          "… (+1 more)"
        ],
        "recommendation": "cdc",
        "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
        "blocks": [
          "D-1",
          "T-1"
        ],
        "proposed_change": "D-1 verdict: outbox → CDC via Debezium on the orders table. Add AC: CDC lag over 5 s for 2 min fires the alert. LLD event delivery section rewritten."
      },
      "created_by": "runner-sdk/implement-task",
      "created_at": "2026-10-30T05:41:00Z",
      "updated_by": "runner-sdk/implement-task",
      "updated_at": "2026-10-30T05:41:00Z",
      "links": {
        "out": [
          {
            "kind": "blocks",
            "to": "D-1"
          },
          {
            "kind": "blocks",
            "to": "T-1"
          },
          "… (+3 more)"
        ],
        "in": []
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "kind": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "domain": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "level": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "asked_by": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "why_now": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "context": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "options": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "recommendation": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "recommendation_why": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "blocks": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        },
        "proposed_change": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-30T05:41:00"
        }
      },
      "stale": [],
      "review_items": []
    }
  ],
  "catalog": [
    {
      "item": "security_review",
      "phase": "draft",
      "text": "threats, data classification, authn/z touched",
      "derived": false,
      "disposition": "addressed",
      "note": "AC-4: only notifications-svc reads the topic; payloads carry ids and states only.",
      "refs": ""
    },
    {
      "item": "rollback_plan",
      "phase": "draft",
      "text": "how a bad deploy is undone",
      "derived": false,
      "disposition": "addressed",
      "note": "HLD: stop the relay; the event table is additive.",
      "refs": ""
    },
    "… (+3 more)"
  ],
  "gate": {
    "gate": "GATE_DRAFT",
    "scope": "initiative",
    "target": null,
    "status": "PASSED",
    "human_role": "dri",
    "text": "Touchpoint 1 — the DRI approves the draft; approval creates baseline B-n",
    "rules": [
      {
        "name": "no_open_decision_in_draft_scope",
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      {
        "name": "no_open_gap_blocking_draft",
        "passed": false,
        "failing": [
          "G-2"
        ],
        "detail": "OPEN gaps block the spec",
        "args": {}
      },
      "… (+5 more)"
    ],
    "note": "approved; preconditions that fail now are mid-build work, not a reopened draft",
    "failing_rules": [
      "no_open_gap_blocking_draft"
    ]
  },
  "can_approve": false,
  "approver": "priya",
  "approval_blockers": [
    {
      "rule": "no_open_gap_blocking_draft",
      "failing": [
        "G-2"
      ],
      "detail": "OPEN gaps block the spec"
    }
  ],
  "approvals": [
    {
      "ref": "APR-1",
      "type": "approval",
      "title": "dri approves draft",
      "status": "CURRENT",
      "pill": "green",
      "line": "dri",
      "rev": 1,
      "fields": {
        "target": [
          "draft"
        ],
        "role": "dri",
        "approved_rev": "3",
        "note": "Scope is right. Ship behind the flag."
      },
      "created_by": "priya",
      "created_at": "2026-10-25T09:41:00Z",
      "updated_by": "priya",
      "updated_at": "2026-10-25T09:41:00Z"
    }
  ],
  "baselines": [
    {
      "ref": "B-1",
      "label": "B-1 — draft rev 3 approved by priya",
      "status": "CURRENT",
      "approval": "APR-1",
      "approved_by": "priya",
      "draft_rev": "3",
      "members": [
        "draft",
        "D-1",
        "… (+9 more)"
      ],
      "created_at": "2026-10-25T09:41:00Z"
    }
  ],
  "review_items": []
}
```

## Records

### GET /api/initiatives/5/records?type=decision

Filters: `type`, `status`, `q` (free text over ref, title and fields), `since` (ISO).

`GET /api/initiatives/5/records?type=decision` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "ref": "D-1",
    "type": "decision",
    "title": "Transactional outbox",
    "status": "DECIDED",
    "pill": "green",
    "line": "Transactional outbox",
    "rev": 2,
    "fields": {
      "question": "How do order events reach consumers?",
      "domain": "engg",
      "level": "MUST",
      "options": [
        {
          "name": "outbox",
          "consequences": "Extra table and relay; exactly-once to the broker",
          "cost_risk": "one table, one relay process"
        },
        {
          "name": "dual-write",
          "consequences": "Simple; loses events on partial failure (breaks STD-1)",
          "cost_risk": "lost events"
        },
        "… (+1 more)"
      ],
      "verdict": "Transactional outbox",
      "rationale": "STD-1 needs exactly-once to the broker; dual-write breaks it and CDC is not set up on orders. Menu sync (D-55) chose the same.",
      "provisional": "no",
      "decided_by": "priya",
      "decided_on": "2026-10-24"
    },
    "created_by": "runner-sdk/draft-from-ticket",
    "created_at": "2026-10-24T09:41:00Z",
    "updated_by": "priya",
    "updated_at": "2026-10-24T16:41:00Z"
  },
  {
    "ref": "D-2",
    "type": "decision",
    "title": "Event envelope with schema_version",
    "status": "PROVISIONAL",
    "pill": "amber",
    "line": "Envelope with schema_version, additive changes only",
    "rev": 1,
    "fields": {
      "question": "How are event schemas versioned?",
      "domain": "engg",
      "level": "SHOULD",
      "verdict": "Envelope with schema_version, additive changes only",
      "rationale": "Follows the default menu-sync chose (D-55 there). A human answer later would supersede it.",
      "provisional": "yes",
      "decided_by": "runner-sdk/draft-skill",
      "decided_on": "2026-10-24"
    },
    "created_by": "runner-sdk/draft-from-ticket",
    "created_at": "2026-10-24T09:41:00Z",
    "updated_by": "runner-sdk/draft-from-ticket",
    "updated_at": "2026-10-24T09:41:00Z"
  }
]
```

### GET /api/initiatives/5/records/G-2

Record detail: links both ways, per-field stamps (`by`, `kind`, `at`), stale narratives, open review items.

`GET /api/initiatives/5/records/G-2` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "ref": "G-2",
  "type": "gap",
  "title": "The outbox table can't be added to the orders schema in time",
  "status": "OPEN",
  "pill": "red",
  "line": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
  "rev": 1,
  "fields": {
    "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
    "kind": "deviation",
    "domain": "engg",
    "level": "MUST",
    "asked_by": "runner-sdk/implement-task",
    "why_now": "Implementing T-1 hit the orders schema ownership rule: T-1 cannot finish as D-1 is written.",
    "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
    "options": [
      {
        "key": "separate-schema",
        "label": "Outbox in a separate schema",
        "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
      },
      {
        "key": "cdc",
        "label": "CDC via Debezium on the orders table",
        "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."
      },
      "… (+1 more)"
    ],
    "recommendation": "cdc",
    "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
    "blocks": [
      "D-1",
      "T-1"
    ],
    "proposed_change": "D-1 verdict: outbox → CDC via Debezium on the orders table. Add AC: CDC lag over 5 s for 2 min fires the alert. LLD event delivery section rewritten."
  },
  "created_by": "runner-sdk/implement-task",
  "created_at": "2026-10-30T05:41:00Z",
  "updated_by": "runner-sdk/implement-task",
  "updated_at": "2026-10-30T05:41:00Z",
  "links": {
    "out": [
      {
        "kind": "blocks",
        "to": "D-1"
      },
      {
        "kind": "blocks",
        "to": "T-1"
      },
      "… (+3 more)"
    ],
    "in": []
  },
  "stamps": {
    "question": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "kind": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "domain": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "level": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "asked_by": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "why_now": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "context": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "options": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "recommendation": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "recommendation_why": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "blocks": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    },
    "proposed_change": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-30T05:41:00"
    }
  },
  "stale": [],
  "review_items": []
}
```

### GET /api/initiatives/5/records/D-1/history

Every revision, newest first: `actor`, `actor_kind`, `because`, `note`, the full `fields` at that rev.

`GET /api/initiatives/5/records/D-1/history` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "rev": 2,
    "ref": "D-1",
    "title": "Transactional outbox",
    "status": "DECIDED",
    "fields": {
      "question": "How do order events reach consumers?",
      "domain": "engg",
      "level": "MUST",
      "options": [
        {
          "name": "outbox",
          "consequences": "Extra table and relay; exactly-once to the broker",
          "cost_risk": "one table, one relay process"
        },
        {
          "name": "dual-write",
          "consequences": "Simple; loses events on partial failure (breaks STD-1)",
          "cost_risk": "lost events"
        },
        "… (+1 more)"
      ],
      "verdict": "Transactional outbox",
      "rationale": "STD-1 needs exactly-once to the broker; dual-write breaks it and CDC is not set up on orders. Menu sync (D-55) chose the same.",
      "provisional": "no",
      "decided_by": "priya",
      "decided_on": "2026-10-24"
    },
    "links": [
      "mentions:STD-1"
    ],
    "actor": "priya",
    "actor_kind": "human",
    "batch_id": "ac780616-1e74-4446-b101-837e4bc0863d",
    "note": "ruled in the inbox",
    "because": [],
    "at": "2026-10-24T16:41:00Z"
  },
  {
    "rev": 1,
    "ref": "D-1",
    "title": "Transactional outbox",
    "status": "OPEN",
    "fields": {
      "question": "How do order events reach consumers?",
      "domain": "engg",
      "level": "MUST",
      "options": [
        {
          "name": "outbox",
          "consequences": "Extra table and relay; exactly-once to the broker",
          "cost_risk": "one table, one relay process"
        },
        {
          "name": "dual-write",
          "consequences": "Simple; loses events on partial failure (breaks STD-1)",
          "cost_risk": "lost events"
        },
        "… (+1 more)"
      ]
    },
    "links": [
      "mentions:STD-1"
    ],
    "actor": "runner-sdk/draft-from-ticket",
    "actor_kind": "agent",
    "batch_id": "57c19647-761c-4e81-8c2d-55c9df7f5fa7",
    "note": "",
    "because": [],
    "at": "2026-10-24T09:41:00Z"
  }
]
```

### POST /api/initiatives/8/records

**Write a batch** (agents and the UI's generic editor). Atomic: every op or none. An op is `{ref?, type?, title?, fields, link?, unlink?, note?, base_rev?, because?, reviewed?}` — omit `ref` and give `type` to mint; `#n` = the ref op n minted; `null` deletes a field; never send `status`. Reusing a `batch_id` with the same ops returns the stored result (`replayed: true`).

`POST /api/initiatives/8/records` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Request:

```json
{
  "agent": "draft-skill",
  "batch_id": "docs-example-1",
  "ops": [
    {
      "type": "decision",
      "title": "Sign webhooks with HMAC",
      "fields": {
        "question": "How do merchants verify a webhook?",
        "domain": "engg",
        "level": "SHOULD",
        "verdict": "HMAC-SHA256 over the raw body with a per-merchant secret",
        "rationale": "Industry default.",
        "decided_by": "runner-sdk/draft-skill",
        "decided_on": "2026-10-29"
      }
    },
    {
      "type": "acceptance_criterion",
      "fields": {
        "text": "Given a settled payment, when the webhook is sent, then its signature verifies with the merchant secret",
        "level": "integration",
        "source": [
          "#0"
        ]
      }
    },
    {
      "type": "acceptance_criterion",
      "fields": {
        "text": "Given a merchant, when ops replays a webhook from the admin, then it is resent within 1 minute",
        "level": "manual",
        "manual": "yes",
        "source": [
          "#0"
        ]
      }
    },
    {
      "ref": "draft",
      "fields": {
        "problem": "Merchants poll for settlement.",
        "hld": "Send a signed webhook on settlement (D-1).",
        "lld": "webhook_deliveries table; retry with backoff.",
        "test_strategy": "Integration tests; AC-2 is checked by hand in staging.",
        "decisions": [
          "#0"
        ],
        "criteria": [
          "#1",
          "#2"
        ]
      }
    },
    {
      "ref": "initiative",
      "fields": {
        "catalog": [
          {
            "item": "security_review",
            "phase": "draft",
            "disposition": "addressed"
          },
          {
            "item": "rollback_plan",
            "phase": "draft",
            "disposition": "addressed"
          },
          {
            "item": "observability",
            "phase": "draft",
            "disposition": "addressed"
          },
          {
            "item": "data_migration_assessed",
            "phase": "draft",
            "disposition": "addressed"
          },
          {
            "item": "test_strategy",
            "phase": "draft",
            "disposition": "addressed"
          }
        ]
      }
    }
  ]
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "docs-example-1",
  "results": [
    {
      "index": 0,
      "ref": "D-1",
      "type": "decision",
      "action": "created",
      "rev": 1,
      "status": "DECIDED",
      "errors": [],
      "warnings": []
    },
    {
      "index": 1,
      "ref": "AC-1",
      "type": "acceptance_criterion",
      "action": "created",
      "rev": 1,
      "status": "PROPOSED",
      "errors": [],
      "warnings": []
    },
    "… (+3 more)"
  ],
  "minted": {
    "#0": "D-1",
    "#1": "AC-1",
    "#2": "AC-2"
  },
  "review_items": [],
  "stale": [],
  "gates_changed": [],
  "baseline": null,
  "replayed": false
}
```

### POST /api/initiatives/5/records (rejected)

A rejected batch: **422**, nothing saved, each op's errors in `error_data.results[].errors` (ops that were fine say `not saved`). Here: after baseline B-1 an agent may not move the spec without `because` (a human-answered gap, a grounded decision, or a finding).

`POST /api/initiatives/5/records` — X-Actor: runner-sdk · X-Actor-Kind: agent → **422**

Request:

```json
{
  "ops": [
    {
      "ref": "draft",
      "fields": {
        "lld": "Relay polls every 5s."
      }
    },
    {
      "type": "acceptance_criterion",
      "fields": {
        "text": "Relay lag under 5s",
        "level": "integration",
        "source": [
          "D-2"
        ]
      }
    }
  ]
}
```

Response:

```json
{
  "status": 422,
  "title": "Write rejected — nothing was saved",
  "detail": "Write rejected — nothing was saved",
  "instance": "http://testserver/api/initiatives/5/records",
  "error_code": "VALIDATION_ERROR",
  "error_data": {
    "ok": false,
    "batch_id": "b5b9acef-8645-4240-b40a-9e159e71d807",
    "results": [
      {
        "index": 0,
        "ref": "draft",
        "type": "draft",
        "action": "error",
        "rev": null,
        "status": null,
        "errors": [
          "because: spec change after baseline B-1 needs `because` (a gap answer, a decision, a finding) — draft is a member of the baseline; moved: lld: “- `order_events(id, order_id, type, payload, created_at,…"
        ],
        "warnings": []
      },
      {
        "index": 1,
        "ref": "AC-8",
        "type": "acceptance_criterion",
        "action": "error",
        "rev": null,
        "status": null,
        "errors": [
          "because: spec change after baseline B-1 needs `because` (a gap answer, a decision, a finding) — AC-8 is added after the baseline; moved: new acceptance_criterion"
        ],
        "warnings": []
      }
    ],
    "minted": {},
    "review_items": [],
    "stale": [],
    "gates_changed": [],
    "baseline": null,
    "replayed": false
  }
}
```

## The human lane (touchpoint 2)

### GET /api/inbox

The caller's inbox (X-Actor) across initiatives, overdue first. `kind`: `gap` (answer it), `decision` (rule it: MUST or escalated), `approval` (`target`: `draft` or a task; tasks carry `drift` and `digest`), `review_item` (`review_item_id`, `what_moved`), `manual_ac` (sign it). `route` says why it landed here (`role`, `domain`, `fallback` = routed to the DRI because nobody holds the role).

`GET /api/inbox` — X-Actor: arjun · X-Actor-Kind: human → **200**

Response:

```json
{
  "person": "arjun",
  "count": 3,
  "overdue": 0,
  "counts": {
    "gap": 1,
    "approval": 1,
    "review_item": 1
  },
  "items": [
    {
      "key": "gap:5:G-2",
      "kind": "gap",
      "initiative_id": 5,
      "initiative": "order-events",
      "initiative_title": "Order events for downstream consumers",
      "ref": "G-2",
      "route": {
        "person": "arjun",
        "role": "engg",
        "domain": "engg",
        "fallback": false
      },
      "person": "arjun",
      "since": "2026-10-30T05:41:00Z",
      "age_hours": 2.0,
      "sla_hours": 24,
      "due_at": "2026-10-31T05:41:00Z",
      "overdue": false,
      "priority": 10,
      "title": "The outbox table can't be added to the orders schema in time",
      "record": {
        "ref": "G-2",
        "type": "gap",
        "title": "The outbox table can't be added to the orders schema in time",
        "status": "OPEN",
        "pill": "red",
        "line": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
        "rev": 1,
        "fields": {
          "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
          "kind": "deviation",
          "domain": "engg",
          "level": "MUST",
          "asked_by": "runner-sdk/implement-task",
          "why_now": "Implementing T-1 hit the orders schema ownership rule: T-1 cannot finish as D-1 is written.",
          "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
          "options": [
            {
              "key": "separate-schema",
              "label": "Outbox in a separate schema",
              "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
            },
            {
              "key": "cdc",
              "label": "CDC via Debezium on the orders table",
              "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."
            },
            "… (+1 more)"
          ],
          "recommendation": "cdc",
          "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
          "blocks": [
            "D-1",
            "T-1"
          ],
          "proposed_change": "D-1 verdict: outbox → CDC via Debezium on the orders table. Add AC: CDC lag over 5 s for 2 min fires the alert. LLD event delivery section rewritten."
        },
        "created_by": "runner-sdk/implement-task",
        "created_at": "2026-10-30T05:41:00Z",
        "updated_by": "runner-sdk/implement-task",
        "updated_at": "2026-10-30T05:41:00Z"
      },
      "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
      "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
      "options": [
        {
          "key": "separate-schema",
          "label": "Outbox in a separate schema",
          "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
        },
        {
          "key": "cdc",
          "label": "CDC via Debezium on the orders table",
          "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."
        },
        "… (+1 more)"
      ],
      "recommendation": "cdc",
      "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
      "blocks": [
        "D-1",
        "T-1"
      ],
      "level": "MUST"
    },
    {
      "key": "approval:2:T-3",
      "kind": "approval",
      "initiative_id": 2,
      "initiative": "payouts-v2",
      "initiative_title": "Payouts v2: refunds ledger",
      "ref": "T-3",
      "route": {
        "person": "arjun",
        "role": "engg",
        "domain": null,
        "fallback": false
      },
      "person": "arjun",
      "since": "2026-10-29T04:41:00Z",
      "age_hours": 27.0,
      "sla_hours": 48,
      "due_at": "2026-10-31T04:41:00Z",
      "overdue": false,
      "priority": 20,
      "title": "Review the drift of T-3: Refunds ledger API",
      "gate": "GATE_PR",
      "role": "engg",
      "target": "T-3",
      "pr_url": "https://github.com/navanta/payouts-svc/pull/77",
      "pr_sha": "e19b0c4",
      "drift": {
        "changes": 1,
        "explained": 1,
        "unexplained": 0,
        "pending_gaps": 0,
        "pending_decisions": 0,
        "other_changes": 0
      },
      "digest": "aa08550c5085fccfd40c398a894c019678e5627b4bcfce8694fa0e4decf65bfa",
      "stale_approvals": []
    },
    "… (+1 more)"
  ]
}
```

### GET /api/people

Everyone with an assignment and their inbox size (the “Viewing as” switcher: who the UI sends as X-Actor).

`GET /api/people` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "person": "arjun",
    "roles": [
      {
        "initiative": "payment-webhooks",
        "role": "engg"
      },
      {
        "initiative": "menu-sync-retries",
        "role": "engg"
      },
      "… (+2 more)"
    ],
    "inbox": 3,
    "name": null,
    "email": null,
    "in_directory": false,
    "teams_user_id": null,
    "identities": []
  },
  {
    "person": "meera",
    "roles": [
      {
        "initiative": "payment-webhooks",
        "role": "product"
      },
      {
        "initiative": "menu-sync-retries",
        "role": "product"
      },
      "… (+4 more)"
    ],
    "inbox": 1,
    "name": null,
    "email": null,
    "in_directory": false,
    "teams_user_id": null,
    "identities": []
  },
  "… (+4 more)"
]
```

### POST /api/initiatives/6/gaps/G-1/answer

**human** — answer a gap: `choice` (an option key) and/or `answer` (text; defaults to the option's label). **Any human may answer any open gap**: here priya answers G-1, which is routed to meera (product). The service stores `answered_by` (the caller), `assigned_to` / `assigned_role` (the routing at this moment, frozen) and `answered_for` (the assignee, because they differ) — see the record below. Returns the write result; `review_items` lists what the answer put up for review and who it went to.

`POST /api/initiatives/6/gaps/G-1/answer` — X-Actor: priya · X-Actor-Kind: human → **200**

Request:

```json
{
  "choice": "per-partner",
  "answer": "Per partner: one flaky partner must not starve the rest."
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "719934f8-3f61-4690-96d9-b3443c34c567",
  "results": [
    {
      "index": 0,
      "ref": "G-1",
      "type": "gap",
      "action": "updated",
      "rev": 2,
      "status": "ANSWERED",
      "errors": [],
      "warnings": []
    }
  ],
  "minted": {},
  "review_items": [
    "D-2 ← G-1: status OPEN → ANSWERED (→ meera)",
    "draft ← G-1: status OPEN → ANSWERED (→ meera)"
  ],
  "stale": [],
  "gates_changed": [],
  "baseline": null,
  "replayed": false
}
```

### GET /api/initiatives/6/records/G-1 (answered on meera's behalf)

`fields.answered_by`, `assigned_to`, `assigned_role`, `answered_for`.

`GET /api/initiatives/6/records/G-1` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "ref": "G-1",
  "type": "gap",
  "title": "Is the retry budget per partner or global?",
  "status": "ANSWERED",
  "pill": "green",
  "line": "Is the retry budget per partner or global?",
  "rev": 2,
  "fields": {
    "question": "Is the retry budget per partner or global?",
    "kind": "unknown",
    "domain": "product",
    "level": "MUST",
    "asked_by": "runner-sdk/draft-from-ticket",
    "why_now": "D-2 cannot be decided without it, and the draft cannot be approved with D-2 open.",
    "context": "STD-2 requires a retry budget but doesn't say what it covers. Partners differ a lot in how often their APIs time out.",
    "options": [
      {
        "key": "per-partner",
        "label": "Per partner",
        "consequence": "One flaky partner can't use up retries for everyone. Needs a budget per partner in config."
      },
      {
        "key": "global",
        "label": "Global",
        "consequence": "Simpler to run. One flaky partner can starve the others."
      }
    ],
    "recommendation": "per-partner",
    "recommendation_why": "Partner timeouts are very uneven; a global budget lets one partner starve the rest.",
    "blocks": [
      "D-2",
      "draft"
    ],
    "answer": "Per partner: one flaky partner must not starve the rest.",
    "choice": "per-partner",
    "answered_by": "priya",
    "answered_on": "2026-10-30T07:41:34Z",
    "assigned_to": "meera",
    "assigned_role": "product",
    "answered_for": "meera",
    "answered_via": "web"
  },
  "created_by": "runner-sdk/draft-from-ticket",
  "created_at": "2026-10-30T03:41:00Z",
  "updated_by": "priya",
  "updated_at": "2026-10-30T07:41:34Z",
  "links": {
    "out": [
      {
        "kind": "blocks",
        "to": "D-2"
      },
      {
        "kind": "blocks",
        "to": "draft"
      },
      {
        "kind": "mentions",
        "to": "D-2"
      },
      "… (+1 more)"
    ],
    "in": [
      {
        "kind": "mentions",
        "from": "draft"
      }
    ]
  },
  "stamps": {
    "question": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "kind": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "domain": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "level": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "asked_by": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "why_now": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "context": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "options": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "recommendation": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "recommendation_why": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "blocks": {
      "by": "runner-sdk/draft-from-ticket",
      "kind": "agent",
      "at": "2026-10-30T03:41:00"
    },
    "answer": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-30T07:41:34"
    },
    "choice": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-30T07:41:34"
    },
    "answered_by": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-30T07:41:34"
    },
    "answered_on": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-30T07:41:34"
    },
    "assigned_to": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-30T07:41:34"
    },
    "assigned_role": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-30T07:41:34"
    },
    "answered_for": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-30T07:41:34"
    },
    "answered_via": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-30T07:41:34"
    }
  },
  "stale": [],
  "review_items": []
}
```

### POST /api/initiatives/6/decisions/D-2/rule

**human** — rule an OPEN or PROVISIONAL decision (MUST-level or escalated decisions can only be ruled here). A DECIDED decision returns 422: supersede it instead.

`POST /api/initiatives/6/decisions/D-2/rule` — X-Actor: meera · X-Actor-Kind: human → **200**

Request:

```json
{
  "verdict": "Per partner: 5 retries per hour each",
  "rationale": "G-1: partner timeouts are uneven."
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "05ab8ba0-5920-43e5-a4c5-45534ac6343a",
  "results": [
    {
      "index": 0,
      "ref": "D-2",
      "type": "decision",
      "action": "updated",
      "rev": 2,
      "status": "DECIDED",
      "errors": [],
      "warnings": []
    }
  ],
  "minted": {},
  "review_items": [],
  "stale": [],
  "gates_changed": [],
  "baseline": null,
  "replayed": false
}
```

### 403 for agents on human endpoints

`POST /api/initiatives/payment-webhooks/approvals` — X-Actor: runner-sdk · X-Actor-Kind: agent → **403**

```json
{
  "status": 403,
  "title": "Human-only operation: runner-sdk is a agent. Agents ask (raise a gap); humans answer in the web UI.",
  "detail": "Human-only operation: runner-sdk is a agent. Agents ask (raise a gap); humans answer in the web UI.",
  "instance": "http://testserver/api/initiatives/payment-webhooks/approvals",
  "error_code": "HUMAN_ONLY",
  "error_data": {}
}
```

### POST /api/initiatives/8/approvals

**human** — approve. `role` dri → `target: "draft"` (creates baseline B-n: see `baseline` in the result); engg → a task ref, with `at_sha` = the PR head (the service pins the drift `digest`); qa → a manual AC. The caller must hold the role on the initiative, and the gate's other rules must pass — else 422 naming them.

`POST /api/initiatives/8/approvals` — X-Actor: priya · X-Actor-Kind: human → **201**

Request:

```json
{
  "target": "draft",
  "role": "dri",
  "note": "Scope is right."
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "3c87ca38-0308-4e08-aa6f-b55a43d14d8f",
  "results": [
    {
      "index": 0,
      "ref": "APR-1",
      "type": "approval",
      "action": "created",
      "rev": 1,
      "status": "CURRENT",
      "errors": [],
      "warnings": []
    }
  ],
  "minted": {
    "#0": "APR-1"
  },
  "review_items": [],
  "stale": [],
  "gates_changed": [
    {
      "gate": "GATE_DRAFT",
      "task": null,
      "before": "BLOCKED",
      "after": "PASSED"
    }
  ],
  "baseline": "B-1",
  "replayed": false
}
```

### POST /api/initiatives/8/criteria/AC-2/sign

**human** (qa) — sign a manual AC at a sha.

`POST /api/initiatives/8/criteria/AC-2/sign` — X-Actor: sam · X-Actor-Kind: human → **200**

Request:

```json
{
  "at_sha": "77ab01c"
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "111f14f6-c949-46bb-bfe8-35e6efee91bb",
  "results": [
    {
      "index": 0,
      "ref": "AC-2",
      "type": "acceptance_criterion",
      "action": "updated",
      "rev": 2,
      "status": "APPROVED",
      "errors": [],
      "warnings": []
    }
  ],
  "minted": {},
  "review_items": [],
  "stale": [],
  "gates_changed": [],
  "baseline": null,
  "replayed": false
}
```

### POST /api/initiatives/8/criteria/AC-1/retire

**human** — retire an AC (shows as `ac_retired` drift).

`POST /api/initiatives/8/criteria/AC-1/retire` — X-Actor: priya · X-Actor-Kind: human → **200**

Request:

```json
{
  "because": "Signature checks move to the shared webhook library."
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "e08e3cb9-d05d-4707-9c15-100877176277",
  "results": [
    {
      "index": 0,
      "ref": "AC-1",
      "type": "acceptance_criterion",
      "action": "updated",
      "rev": 2,
      "status": "RETIRED",
      "errors": [],
      "warnings": []
    }
  ],
  "minted": {},
  "review_items": [],
  "stale": [],
  "gates_changed": [
    {
      "gate": "GATE_VALIDATED",
      "task": null,
      "before": "BLOCKED",
      "after": "PASSED"
    }
  ],
  "baseline": null,
  "replayed": false
}
```

### POST /api/initiatives/8/snapshot

**human** — re-pin the requirement (a material change: the draft goes up for review, and the drift report shows `requirement_repinned`). Returns `{state, write}`.

`POST /api/initiatives/8/snapshot` — X-Actor: priya · X-Actor-Kind: human → **200**

Request:

```json
{
  "requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles **or is refunded**.",
  "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410"
}
```

Response:

```json
{
  "state": {
    "initiative": {
      "id": 8,
      "slug": "payment-webhooks",
      "title": "Payment webhooks",
      "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
      "created_by": "priya",
      "created_at": "2026-10-30T07:41:34Z",
      "closed_at": null,
      "snapshot_hash": "3e1d0980654a7e1f11252a40a60e77f88085137c7dd361b379fa08ec41566e8c",
      "phase": "PLAN",
      "pill": "amber",
      "summary": "",
      "spec_snapshot": {
        "requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles **or is refunded**.",
        "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
        "created_by": "priya",
        "at": "2026-10-30T07:41:34Z",
        "previous_hash": "a98a462dac3c82099ff1a3e5fd850ac1dcc41a30612f84ef9abb4c4661ff2d0d",
        "previous_at": "2026-10-30T07:41:34Z"
      }
    },
    "phase": "PLAN",
    "assignments": [
      {
        "ref": "A-1",
        "person": "priya",
        "role": "dri",
        "scope": [
          "initiative"
        ],
        "status": "ACTIVE"
      },
      "… (+3 more)"
    ],
    "gates": [
      {
        "gate": "GATE_DRAFT",
        "scope": "initiative",
        "target": null,
        "status": "PASSED",
        "human_role": "dri",
        "text": "Touchpoint 1 — the DRI approves the draft; approval creates baseline B-n",
        "rules": [
          {
            "name": "no_open_decision_in_draft_scope",
            "passed": true,
            "failing": [],
            "detail": "",
            "args": {}
          },
          "… (+6 more)"
        ],
        "note": "approved; preconditions that fail now are mid-build work, not a reopened draft",
        "failing_rules": [
          "no_open_review_items_on_spec"
        ]
      },
      "… (+1 more)"
    ],
    "tasks": [],
    "counts": {
      "initiative": {
        "PLAN": 1
      },
      "assignment": {
        "ACTIVE": 4
      },
      "draft": {
        "APPROVED": 1
      },
      "decision": {
        "DECIDED": 1
      },
      "acceptance_criterion": {
        "RETIRED": 1,
        "APPROVED": 1
      },
      "approval": {
        "CURRENT": 1
      },
      "baseline": {
        "CURRENT": 1
      }
    },
    "open": {
      "decisions": [],
      "gaps": [],
      "review_items": 1
    },
    "stuck": [],
    "baseline": {
      "ref": "B-1",
      "label": "B-1 — draft rev 1 approved by priya",
      "status": "CURRENT",
      "approval": "APR-1",
      "approved_by": "priya",
      "draft_rev": "1",
      "members": [
        "draft",
        "… (+3 more)"
      ],
      "created_at": "2026-10-30T07:41:34Z"
    },
    "drift": {
      "changes": 2,
      "explained": 2,
      "unexplained": 0,
      "pending_gaps": 0,
      "pending_decisions": 0,
      "other_changes": 0
    },
    "stale": [],
    "catalog": {
      "intake": [
        {
          "item": "dri_assigned",
          "phase": "intake",
          "text": "an ACTIVE dri assignment",
          "derived": true,
          "disposition": "addressed",
          "note": "",
          "refs": ""
        },
        "… (+2 more)"
      ],
      "draft": [
        {
          "item": "security_review",
          "phase": "draft",
          "text": "threats, data classification, authn/z touched",
          "derived": false,
          "disposition": "addressed",
          "note": "",
          "refs": ""
        },
        "… (+4 more)"
      ],
      "plan": [
        {
          "item": "every_ac_covered_by_a_task",
          "phase": "plan",
          "text": "each live AC is in some task's covers",
          "derived": true,
          "disposition": "UNASSESSED",
          "note": "",
          "refs": ""
        },
        "… (+1 more)"
      ],
      "build": []
    }
  },
  "write": {
    "ok": true,
    "batch_id": "2c92461c-2657-4cb6-b4cb-d4fe0de51ea3",
    "results": [
      {
        "index": 0,
        "ref": "initiative",
        "type": "initiative",
        "action": "updated",
        "rev": 3,
        "status": "PLAN",
        "errors": [],
        "warnings": []
      }
    ],
    "minted": {},
    "review_items": [
      "draft ← initiative: snapshot_hash: “a98a462dac3c82099ff1a3e5fd850ac1dcc41a30612f84ef9abb4c4661f…” → “3e1d0980654a7e1f11252a40a60e77f88085137c7dd361b379fa08ec415…” (→ priya)"
    ],
    "stale": [],
    "gates_changed": [],
    "baseline": null,
    "replayed": false
  }
}
```

## Review queue

### GET /api/initiatives/8/reviews

Open review items (`?status=open` default; `upheld`, `revised`, `dismissed`, `all`). Each: `cause` moved (`what_moved`), so `target` may no longer hold; `route_to` is who should look.

`GET /api/initiatives/8/reviews` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "id": 25,
    "target": "draft",
    "cause": "initiative",
    "cause_rev": 3,
    "what_moved": "snapshot_hash: “a98a462dac3c82099ff1a3e5fd850ac1dcc41a30612f84ef9abb4c4661f…” → “3e1d0980654a7e1f11252a40a60e77f88085137c7dd361b379fa08ec415…”",
    "path": "scope",
    "status": "open",
    "route_to": "priya",
    "domain": null,
    "judged_by": "rules",
    "note": null,
    "created_by": "priya",
    "created_at": "2026-10-30T07:41:34Z",
    "resolved_by": null,
    "resolved_at": null
  }
]
```

### POST /api/initiatives/8/reviews/25/resolve

Resolve: `upheld` (still holds — say why) · `revised` · `dismissed`. `note` required. `upheld` and `dismissed` are **human** (403 `HUMAN_ONLY` to agents); an agent's `reviewed: true` write leaves the item open with `judged_by: agent` and its note.

`POST /api/initiatives/8/reviews/25/resolve` — X-Actor: priya · X-Actor-Kind: human → **200**

Request:

```json
{
  "resolution": "upheld",
  "note": "Refunds are a separate initiative; the draft holds."
}
```

Response:

```json
{
  "id": 25,
  "target": "draft",
  "cause": "initiative",
  "cause_rev": 3,
  "what_moved": "snapshot_hash: “a98a462dac3c82099ff1a3e5fd850ac1dcc41a30612f84ef9abb4c4661f…” → “3e1d0980654a7e1f11252a40a60e77f88085137c7dd361b379fa08ec415…”",
  "path": "scope",
  "status": "upheld",
  "route_to": "priya",
  "domain": null,
  "judged_by": "rules",
  "note": "Refunds are a separate initiative; the draft holds.",
  "created_by": "priya",
  "created_at": "2026-10-30T07:41:34Z",
  "resolved_by": "priya",
  "resolved_at": "2026-10-30T07:41:34Z"
}
```

## Drift, gates, tasks (touchpoint 3)

### GET /api/initiatives/5/tasks/T-3

**Task page**: the task (detail), its GATE_PR (rule by rule), its task-scoped drift report (full shape below), the approver, test runs, findings, deploys.

`GET /api/initiatives/5/tasks/T-3` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "task": {
    "ref": "T-3",
    "type": "task",
    "title": "Topic, IAM and lag dashboard",
    "status": "IN_REVIEW",
    "pill": "amber",
    "line": "Create orders.events, the notifications-svc read role and the lag dashboard",
    "rev": 2,
    "fields": {
      "goal": "Create orders.events, the notifications-svc read role and the lag dashboard",
      "repo": "infra-terraform",
      "template": "terraform-module",
      "implements": [
        "D-1"
      ],
      "covers": [
        "AC-4",
        "AC-6"
      ],
      "rollback": "terraform destroy of the new module; nothing else depends on it yet.",
      "pr_url": "https://github.com/navanta/infra-terraform/pull/212",
      "pr_state": "open",
      "pr_sha": "a41c09e",
      "ci_attempts": "1",
      "review_rounds": "1"
    },
    "created_by": "runner-sdk/plan-to-tasks",
    "created_at": "2026-10-25T11:41:00Z",
    "updated_by": "runner-sdk/implement-task",
    "updated_at": "2026-10-28T07:41:00Z",
    "links": {
      "out": [
        {
          "kind": "covers",
          "to": "AC-4"
        },
        {
          "kind": "covers",
          "to": "AC-6"
        },
        {
          "kind": "implements",
          "to": "D-1"
        }
      ],
      "in": [
        {
          "kind": "approves",
          "from": "APR-2"
        },
        {
          "kind": "depends_on",
          "from": "T-4"
        },
        {
          "kind": "runs_for",
          "from": "R-1"
        }
      ]
    },
    "stamps": {
      "goal": {
        "by": "runner-sdk/plan-to-tasks",
        "kind": "agent",
        "at": "2026-10-25T11:41:00"
      },
      "repo": {
        "by": "runner-sdk/plan-to-tasks",
        "kind": "agent",
        "at": "2026-10-25T11:41:00"
      },
      "template": {
        "by": "runner-sdk/plan-to-tasks",
        "kind": "agent",
        "at": "2026-10-25T11:41:00"
      },
      "implements": {
        "by": "runner-sdk/plan-to-tasks",
        "kind": "agent",
        "at": "2026-10-25T11:41:00"
      },
      "covers": {
        "by": "runner-sdk/plan-to-tasks",
        "kind": "agent",
        "at": "2026-10-25T11:41:00"
      },
      "rollback": {
        "by": "runner-sdk/plan-to-tasks",
        "kind": "agent",
        "at": "2026-10-25T11:41:00"
      },
      "pr_url": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-28T07:41:00"
      },
      "pr_state": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-28T07:41:00"
      },
      "pr_sha": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-28T07:41:00"
      },
      "ci_attempts": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-28T07:41:00"
      },
      "review_rounds": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-28T07:41:00"
      }
    },
    "stale": [],
    "review_items": []
  },
  "gate": {
    "gate": "GATE_PR",
    "scope": "task",
    "target": "T-3",
    "status": "PASSED",
    "human_role": "engg",
    "text": "Touchpoint 3 — the engineer approves the task's drift report at the PR head",
    "rules": [
      {
        "name": "pr_state_in",
        "passed": true,
        "failing": [],
        "detail": "pr_state is open; needs open | approved",
        "args": {
          "states": [
            "open",
            "approved"
          ]
        }
      },
      {
        "name": "no_blocker_finding_open_at_sha",
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      {
        "name": "every_covered_ac_has_a_test",
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      "… (+3 more)"
    ],
    "note": "",
    "failing_rules": []
  },
  "drift": {
    "status": "CLEAN",
    "initiative": "order-events",
    "task": "T-3",
    "baseline": {
      "ref": "B-1",
      "label": "B-1 — draft rev 3 approved by priya",
      "status": "CURRENT",
      "approval": "APR-1",
      "approved_by": "priya",
      "draft_rev": "3",
      "created_at": "2026-10-25T09:41:00Z",
      "members": 11
    },
    "until": null,
    "scope_refs": [
      "AC-1",
      "AC-2",
      "AC-3",
      "… (+6 more)"
    ],
    "summary": {
      "changes": 0,
      "explained": 0,
      "unexplained": 0,
      "pending_gaps": 1,
      "pending_decisions": 0,
      "other_changes": 0
    },
    "digest": "2e955487883a09bdcd5582737e965530635e0a3b5ce49a656c761298c4ec4f93",
    "entries": [],
    "unexplained": [],
    "pending_gaps": [
      {
        "ref": "G-2",
        "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
        "kind": "deviation",
        "domain": "engg",
        "blocks": [
          "D-1",
          "T-1"
        ],
        "asked_by": "runner-sdk/implement-task",
        "at": "2026-10-30T05:41:00Z"
      }
    ],
    "pending_decisions": [],
    "spec_diff": {
      "draft": {},
      "decisions": {
        "added": [],
        "superseded": [],
        "changed": [],
        "unchanged": 1
      },
      "criteria": {
        "added": [],
        "retired": [],
        "changed": [],
        "unchanged": 6
      }
    },
    "approved_spec": {
      "draft": {
        "problem": "Notifications-svc polls the orders database every minute to find new and cancelled orders. Emails go out late, and the polling query is the orders DB's top load. Done means consumers receive order.cre…",
        "hld": "orders-service writes each order change and an event row in one transaction (D-1). A relay publishes event rows to the `orders.events` topic and marks them sent. Events use a versioned envelope (D-2).…",
        "lld": "- `order_events(id, order_id, type, payload, created_at, sent_at)`\n- Event delivery: a relay polls unsent rows every 200 ms in batches of 500, publishes with key = order_id, and sets `sent_at` after t…",
        "scope_in": [
          "order.created and order.cancelled",
          "the orders.events topic",
          "consumer dedupe",
          "… (+1 more)"
        ],
        "scope_out": [
          "refund events",
          "backfilling historical orders",
          "other consumers"
        ],
        "test_strategy": "Unit: envelope and dedupe logic. Integration: relay against a real broker, including a 10-minute outage (AC-3). Manual: QA checks the lag dashboard in the test environment. Every criterion maps to at …"
      },
      "decisions": [
        {
          "ref": "D-1",
          "title": "Transactional outbox",
          "question": "How do order events reach consumers?",
          "verdict": "Transactional outbox",
          "level": "MUST",
          "status": "DECIDED"
        }
      ],
      "criteria": [
        {
          "ref": "AC-1",
          "text": "Given an order commits, when the relay runs, then order.created is published once",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        {
          "ref": "AC-2",
          "text": "Given an order write, then its event row is written in the same transaction",
          "level": "unit",
          "manual": "",
          "status": "APPROVED"
        },
        {
          "ref": "AC-3",
          "text": "Given the broker is down for 10 min, when it recovers, then every event arrives with none duplicated",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        "… (+3 more)"
      ]
    },
    "current_spec": {
      "draft": {
        "problem": "Notifications-svc polls the orders database every minute to find new and cancelled orders. Emails go out late, and the polling query is the orders DB's top load. Done means consumers receive order.cre…",
        "hld": "orders-service writes each order change and an event row in one transaction (D-1). A relay publishes event rows to the `orders.events` topic and marks them sent. Events use a versioned envelope (D-2).…",
        "lld": "- `order_events(id, order_id, type, payload, created_at, sent_at)`\n- Event delivery: a relay polls unsent rows every 200 ms in batches of 500, publishes with key = order_id, and sets `sent_at` after t…",
        "scope_in": [
          "order.created and order.cancelled",
          "the orders.events topic",
          "consumer dedupe",
          "… (+1 more)"
        ],
        "scope_out": [
          "refund events",
          "backfilling historical orders",
          "other consumers"
        ],
        "test_strategy": "Unit: envelope and dedupe logic. Integration: relay against a real broker, including a 10-minute outage (AC-3). Manual: QA checks the lag dashboard in the test environment. Every criterion maps to at …"
      },
      "decisions": [
        {
          "ref": "D-1",
          "title": "Transactional outbox",
          "question": "How do order events reach consumers?",
          "verdict": "Transactional outbox",
          "level": "MUST",
          "status": "DECIDED"
        }
      ],
      "criteria": [
        {
          "ref": "AC-1",
          "text": "Given an order commits, when the relay runs, then order.created is published once",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        {
          "ref": "AC-2",
          "text": "Given an order write, then its event row is written in the same transaction",
          "level": "unit",
          "manual": "",
          "status": "APPROVED"
        },
        {
          "ref": "AC-3",
          "text": "Given the broker is down for 10 min, when it recovers, then every event arrives with none duplicated",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        "… (+3 more)"
      ]
    },
    "approvals": [
      {
        "ref": "APR-2",
        "by": "arjun",
        "status": "CURRENT",
        "at_sha": "a41c09e",
        "drift_digest": "2e955487883a09bdcd5582737e965530635e0a3b5ce49a656c761298c4ec4f93",
        "matches_digest": true,
        "note": "Topic, role and dashboard as in the HLD.",
        "at": "2026-10-28T11:41:00Z"
      }
    ]
  },
  "approver": "arjun",
  "test_runs": [
    {
      "ref": "R-1",
      "type": "test_run",
      "title": "infra-terraform plan + policy tests @ a41c09e",
      "status": "GREEN",
      "pill": "green",
      "line": "infra-terraform plan + policy tests",
      "rev": 1,
      "fields": {
        "summary": "infra-terraform plan + policy tests",
        "level": "integration",
        "result": "GREEN",
        "at_sha": "a41c09e",
        "run_url": "https://ci.navanta.dev/runs/12005",
        "environment": "ci",
        "task": [
          "T-3"
        ],
        "covers": [
          {
            "ac": "AC-4",
            "result": "GREEN",
            "test_id": "test_AC_4_topic_acl"
          }
        ],
        "run_on": "2026-10-30T06:41"
      },
      "created_by": "runner-sdk/write-tests",
      "created_at": "2026-10-28T07:41:00Z",
      "updated_by": "runner-sdk/write-tests",
      "updated_at": "2026-10-28T07:41:00Z"
    }
  ],
  "findings": [],
  "deploys": []
}
```

### GET /api/initiatives/1/drift?task=T-1

The task-scoped drift report. Without `task`: the whole initiative. `baseline=B-n`: from an older baseline up to the next one.

`GET /api/initiatives/1/drift?task=T-1` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "EXPLAINED",
  "initiative": "inventory-sync-v3",
  "task": "T-1",
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 1 approved by priya",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "priya",
    "draft_rev": "1",
    "created_at": "2026-10-11T07:41:00Z",
    "members": 7
  },
  "until": null,
  "scope_refs": [
    "AC-1",
    "AC-3",
    "D-1",
    "… (+3 more)"
  ],
  "summary": {
    "changes": 2,
    "explained": 2,
    "unexplained": 0,
    "pending_gaps": 0,
    "pending_decisions": 0,
    "other_changes": 0
  },
  "digest": "f4e2b3666dfbfc5cddc33fa34d72e3f09b2346e2db33663a485ceb3ab75540a3",
  "entries": [
    {
      "id": "gap_answered:G-1@2",
      "kind": "gap_answered",
      "ref": "G-1",
      "type": "gap",
      "rev": 2,
      "at": "2026-10-14T11:41:00Z",
      "actor": "meera",
      "actor_kind": "human",
      "summary": "G-1 answered by meera: “Delta sync — a minute is what partners were promised.”",
      "what_moved": [],
      "because": [],
      "explained": true,
      "explanation": [
        {
          "ref": null,
          "ok": true,
          "why": "a human answer (meera)"
        }
      ],
      "related": [
        "D-1"
      ],
      "detail": {
        "question": "A full sync takes 4 minutes for large partners. Switch to delta sync every 30 seconds?",
        "answer": "Delta sync — a minute is what partners were promised.",
        "choice": "delta",
        "answered_by": "meera",
        "assigned_to": "meera",
        "assigned_role": "product",
        "answered_for": "",
        "blocks": [
          "D-1"
        ],
        "resolution": "D-3 supersedes D-1.",
        "kind": "deviation",
        "proposed_change": ""
      },
      "in_scope": true
    },
    {
      "id": "decision_superseded:D-3@1",
      "kind": "decision_superseded",
      "ref": "D-3",
      "type": "decision",
      "rev": 1,
      "at": "2026-10-14T13:41:00Z",
      "actor": "runner-sdk/implement-task",
      "actor_kind": "agent",
      "summary": "D-3 supersedes D-1: verdict “Full sync every 5 minutes” → “Delta sync every 30 seconds”",
      "what_moved": [
        "verdict: “Full sync every 5 minutes” → “Delta sync every 30 seconds”"
      ],
      "because": [
        "G-1"
      ],
      "explained": true,
      "explanation": [
        {
          "ref": "G-1",
          "ok": true,
          "why": "answered by meera: “Delta sync — a minute is what partners were promised.”"
        }
      ],
      "related": [
        "D-1",
        "G-1"
      ],
      "detail": {
        "superseded": "D-1",
        "old_verdict": "Full sync every 5 minutes",
        "new_verdict": "Delta sync every 30 seconds",
        "question": "How often is inventory synced?",
        "level": "SHOULD",
        "rationale": "G-1: full sync is too slow for large partners.",
        "related_gaps": [
          "G-1"
        ]
      },
      "in_scope": true
    }
  ],
  "unexplained": [],
  "pending_gaps": [],
  "pending_decisions": [],
  "spec_diff": {
    "draft": {},
    "decisions": {
      "added": [],
      "superseded": [
        {
          "old": "D-1",
          "new": "D-3",
          "old_verdict": "Full sync every 5 minutes",
          "new_verdict": "Delta sync every 30 seconds"
        }
      ],
      "changed": [],
      "unchanged": 0
    },
    "criteria": {
      "added": [],
      "retired": [],
      "changed": [],
      "unchanged": 2
    }
  },
  "approved_spec": {
    "draft": {
      "problem": "Partner inventory is up to an hour stale.",
      "hld": "Sync (D-1) and push (D-2).",
      "lld": "- sync cursor per partner",
      "scope_in": null,
      "scope_out": null,
      "test_strategy": "Integration and a manual lag check."
    },
    "decisions": [
      {
        "ref": "D-1",
        "title": "Full sync every 5 minutes",
        "question": "How often is inventory synced?",
        "verdict": "Full sync every 5 minutes",
        "level": "SHOULD",
        "status": "DECIDED"
      }
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given a stock change, then the partner sees it within a minute",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-3",
        "text": "Given a full resync, then no partner receives a duplicate",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      }
    ]
  },
  "current_spec": {
    "draft": {
      "problem": "Partner inventory is up to an hour stale.",
      "hld": "Sync (D-1) and push (D-2).",
      "lld": "- sync cursor per partner",
      "scope_in": null,
      "scope_out": null,
      "test_strategy": "Integration and a manual lag check."
    },
    "decisions": [
      {
        "ref": "D-3",
        "title": "Delta sync every 30 seconds",
        "question": "How often is inventory synced?",
        "verdict": "Delta sync every 30 seconds",
        "level": "SHOULD",
        "status": "DECIDED"
      }
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given a stock change, then the partner sees it within a minute",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-3",
        "text": "Given a full resync, then no partner receives a duplicate",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      }
    ]
  },
  "approvals": [
    {
      "ref": "APR-2",
      "by": "nikhil",
      "status": "CURRENT",
      "at_sha": "8b9c0d1e",
      "drift_digest": "f4e2b3666dfbfc5cddc33fa34d72e3f09b2346e2db33663a485ceb3ab75540a3",
      "matches_digest": true,
      "note": "",
      "at": "2026-10-26T07:41:00Z"
    }
  ]
}
```

### GET /api/initiatives/1/drift?task=T-1&format=md

The same report as the PR's sticky comment.

`GET /api/initiatives/1/drift?task=T-1&format=md` — X-Actor: priya · X-Actor-Kind: human → **200**

Response (`text/markdown; charset=utf-8`):

````markdown
## Drift since baseline B-1 (approved by priya, 2026-10-11, draft rev 1) — scope: T-1
**2 changes · 2 explained · 0 unexplained** · digest `f4e2b366…`

| when | who | change | because | |
|---|---|---|---|---|
| 10-14 11:41 | meera (human) | G-1 answered by meera: “Delta sync — a minute is what partners were promised.” | — | ✓ |
| 10-14 13:41 | runner-sdk/implement-task | D-3 supersedes D-1: verdict “Full sync every 5 minutes” → “Delta sync every 30 seconds” | G-1 | ✓ |

### Spec diff · decisions: 1 superseded
- D-1 → D-3: “Full sync every 5 minutes” → “Delta sync every 30 seconds”
````

### GET /api/initiatives/5/drift?task=T-2 (CLEAN)

A task with nothing changed in its scope: `status: CLEAN`, `other_changes` counts the initiative's changes outside it.

`GET /api/initiatives/5/drift?task=T-2` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "CLEAN",
  "initiative": "order-events",
  "task": "T-2",
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 3 approved by priya",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "priya",
    "draft_rev": "3",
    "created_at": "2026-10-25T09:41:00Z",
    "members": 11
  },
  "until": null,
  "scope_refs": [
    "AC-1",
    "… (+9 more)"
  ],
  "summary": {
    "changes": 0,
    "explained": 0,
    "unexplained": 0,
    "pending_gaps": 1,
    "pending_decisions": 0,
    "other_changes": 0
  },
  "digest": "42c0cb7b907516b13fce222a1079e3cd8873baa7dd0f3a6ebaf16a88c6f29dd3",
  "entries": [],
  "unexplained": [],
  "pending_gaps": [
    {
      "ref": "G-2",
      "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
      "kind": "deviation",
      "domain": "engg",
      "blocks": [
        "D-1",
        "… (+1 more)"
      ],
      "asked_by": "runner-sdk/implement-task",
      "at": "2026-10-30T05:41:00Z"
    }
  ],
  "pending_decisions": [],
  "spec_diff": {
    "draft": {},
    "decisions": {
      "added": [],
      "superseded": [],
      "changed": [],
      "unchanged": 2
    },
    "criteria": {
      "added": [],
      "retired": [],
      "changed": [],
      "unchanged": 6
    }
  },
  "approved_spec": {
    "draft": {
      "problem": "Notifications-svc polls the orders database every minute to find new and cancelled orders. Emails go out late, and the polling query is the orders DB's top load. Done means consumers receive order.cre…",
      "hld": "orders-service writes each order change and an event row in one transaction (D-1). A relay publishes event rows to the `orders.events` topic and marks them sent. Events use a versioned envelope (D-2).…",
      "lld": "- `order_events(id, order_id, type, payload, created_at, sent_at)`\n- Event delivery: a relay polls unsent rows every 200 ms in batches of 500, publishes with key = order_id, and sets `sent_at` after t…",
      "scope_in": [
        "order.created and order.cancelled",
        "… (+3 more)"
      ],
      "scope_out": [
        "refund events",
        "… (+2 more)"
      ],
      "test_strategy": "Unit: envelope and dedupe logic. Integration: relay against a real broker, including a 10-minute outage (AC-3). Manual: QA checks the lag dashboard in the test environment. Every criterion maps to at …"
    },
    "decisions": [
      {
        "ref": "D-1",
        "title": "Transactional outbox",
        "question": "How do order events reach consumers?",
        "verdict": "Transactional outbox",
        "level": "MUST",
        "status": "DECIDED"
      },
      "… (+1 more)"
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given an order commits, when the relay runs, then order.created is published once",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      "… (+5 more)"
    ]
  },
  "current_spec": {
    "draft": {
      "problem": "Notifications-svc polls the orders database every minute to find new and cancelled orders. Emails go out late, and the polling query is the orders DB's top load. Done means consumers receive order.cre…",
      "hld": "orders-service writes each order change and an event row in one transaction (D-1). A relay publishes event rows to the `orders.events` topic and marks them sent. Events use a versioned envelope (D-2).…",
      "lld": "- `order_events(id, order_id, type, payload, created_at, sent_at)`\n- Event delivery: a relay polls unsent rows every 200 ms in batches of 500, publishes with key = order_id, and sets `sent_at` after t…",
      "scope_in": [
        "order.created and order.cancelled",
        "… (+3 more)"
      ],
      "scope_out": [
        "refund events",
        "… (+2 more)"
      ],
      "test_strategy": "Unit: envelope and dedupe logic. Integration: relay against a real broker, including a 10-minute outage (AC-3). Manual: QA checks the lag dashboard in the test environment. Every criterion maps to at …"
    },
    "decisions": [
      {
        "ref": "D-1",
        "title": "Transactional outbox",
        "question": "How do order events reach consumers?",
        "verdict": "Transactional outbox",
        "level": "MUST",
        "status": "DECIDED"
      },
      "… (+1 more)"
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given an order commits, when the relay runs, then order.created is published once",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      "… (+5 more)"
    ]
  },
  "approvals": []
}
```

### GET /api/initiatives/3/drift (UNEXPLAINED)

An agent changed AC-4 after approval citing finding F-1; a human then rejected F-1, so the change lost its reason: `status: UNEXPLAINED`, the entry's `explanation` says why, the draft is REOPENED and GATE_PR blocks.

`GET /api/initiatives/3/drift` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "UNEXPLAINED",
  "initiative": "loyalty-expiry",
  "task": null,
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 1 approved by priya",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "priya",
    "draft_rev": "1",
    "created_at": "2026-10-22T07:41:00Z",
    "members": 8
  },
  "until": null,
  "scope_refs": [],
  "summary": {
    "changes": 1,
    "explained": 0,
    "unexplained": 1,
    "pending_gaps": 0,
    "pending_decisions": 0,
    "other_changes": 0
  },
  "digest": "6cb8ffda70a91ea5e03cc6fc4fe40fe7b2a7af3164f4c3da287000fe53fd17d0",
  "entries": [
    {
      "id": "ac_changed:AC-4@2",
      "kind": "ac_changed",
      "ref": "AC-4",
      "type": "acceptance_criterion",
      "rev": 2,
      "at": "2026-10-30T03:41:00Z",
      "actor": "runner-sdk/implement-task",
      "actor_kind": "agent",
      "summary": "AC-4 changed: text: “Points expire 365 days after earning” → “Points expire 365 days after the last purchase”",
      "what_moved": [
        "text: “Points expire 365 days after earning” → “Points expire 365 days after the last purchase”"
      ],
      "because": [
        "F-1"
      ],
      "explained": false,
      "explanation": [
        {
          "ref": "F-1",
          "ok": false,
          "why": "F-1 was rejected"
        }
      ],
      "related": [],
      "detail": {
        "old": "Points expire 365 days after earning",
        "new": "Points expire 365 days after the last purchase"
      },
      "in_scope": true
    }
  ],
  "unexplained": [
    "ac_changed:AC-4@2"
  ],
  "pending_gaps": [],
  "pending_decisions": [],
  "spec_diff": {
    "draft": {},
    "decisions": {
      "added": [],
      "superseded": [],
      "changed": [],
      "unchanged": 1
    },
    "criteria": {
      "added": [],
      "retired": [],
      "changed": [
        {
          "ref": "AC-4",
          "old": "Points expire 365 days after earning",
          "new": "Points expire 365 days after the last purchase"
        }
      ],
      "unchanged": 5
    }
  },
  "approved_spec": {
    "draft": {
      "problem": "Points never expire, which the partner contract requires.",
      "hld": "A nightly job (D-1) writes expiry ledger entries; a notice email goes out 30 days before.",
      "lld": "- `expiry_runs(day, status)` for idempotency\n- ledger entry type EXPIRY",
      "scope_in": null,
      "scope_out": null,
      "test_strategy": "Unit for the date rule; integration for the job and emails; manual check of the support view."
    },
    "decisions": [
      {
        "ref": "D-1",
        "title": "Nightly expiry job, not on read",
        "question": "When are points expired?",
        "verdict": "Nightly expiry job, not on read",
        "level": "SHOULD",
        "status": "DECIDED"
      }
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given points older than 365 days, when the nightly job runs, then an expiry ledger entry is written",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-2",
        "text": "Given the job reruns, then no point expires twice",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      "… (+4 more)"
    ]
  },
  "current_spec": {
    "draft": {
      "problem": "Points never expire, which the partner contract requires.",
      "hld": "A nightly job (D-1) writes expiry ledger entries; a notice email goes out 30 days before.",
      "lld": "- `expiry_runs(day, status)` for idempotency\n- ledger entry type EXPIRY",
      "scope_in": null,
      "scope_out": null,
      "test_strategy": "Unit for the date rule; integration for the job and emails; manual check of the support view."
    },
    "decisions": [
      {
        "ref": "D-1",
        "title": "Nightly expiry job, not on read",
        "question": "When are points expired?",
        "verdict": "Nightly expiry job, not on read",
        "level": "SHOULD",
        "status": "DECIDED"
      }
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given points older than 365 days, when the nightly job runs, then an expiry ledger entry is written",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-2",
        "text": "Given the job reruns, then no point expires twice",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      "… (+4 more)"
    ]
  },
  "approvals": []
}
```

### GET /api/initiatives/8/drift (initiative scope)

Initiative scope after an AC retirement and a requirement re-pin by humans.

`GET /api/initiatives/8/drift` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "EXPLAINED",
  "initiative": "payment-webhooks",
  "task": null,
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 1 approved by priya",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "priya",
    "draft_rev": "1",
    "created_at": "2026-10-30T07:41:34Z",
    "members": 4
  },
  "until": null,
  "scope_refs": [],
  "summary": {
    "changes": 2,
    "explained": 2,
    "unexplained": 0,
    "pending_gaps": 0,
    "pending_decisions": 0,
    "other_changes": 0
  },
  "digest": "5d3db0d113cb3fbd51d7d4587d0a42d5177b8297ac9fda17037e23256fe1265e",
  "entries": [
    {
      "id": "requirement_repinned:initiative@3",
      "kind": "requirement_repinned",
      "ref": "initiative",
      "type": "initiative",
      "rev": 3,
      "at": "2026-10-30T07:41:34Z",
      "actor": "priya",
      "actor_kind": "human",
      "summary": "requirement re-pinned by priya (hash 3e1d0980)",
      "what_moved": [
        "snapshot_hash"
      ],
      "because": [],
      "explained": true,
      "explanation": [
        {
          "ref": null,
          "ok": true,
          "why": "made by a human (priya)"
        }
      ],
      "related": [],
      "detail": {},
      "in_scope": true
    },
    {
      "id": "ac_retired:AC-1@2",
      "kind": "ac_retired",
      "ref": "AC-1",
      "type": "acceptance_criterion",
      "rev": 2,
      "at": "2026-10-30T07:41:34Z",
      "actor": "priya",
      "actor_kind": "human",
      "summary": "AC-1 retired: Signature checks move to the shared webhook library.",
      "what_moved": [],
      "because": [],
      "explained": true,
      "explanation": [
        {
          "ref": null,
          "ok": true,
          "why": "made by a human (priya)"
        }
      ],
      "related": [],
      "detail": {
        "text": "Given a settled payment, when the webhook is sent, then its signature verifies with the merchant secret",
        "retired_because": "Signature checks move to the shared webhook library."
      },
      "in_scope": true
    }
  ],
  "unexplained": [],
  "pending_gaps": [],
  "pending_decisions": [],
  "spec_diff": {
    "draft": {},
    "decisions": {
      "added": [],
      "superseded": [],
      "changed": [],
      "unchanged": 1
    },
    "criteria": {
      "added": [],
      "retired": [
        {
          "ref": "AC-1",
          "text": "Given a settled payment, when the webhook is sent, then its signature verifies with the merchant secret",
          "retired_because": "Signature checks move to the shared webhook library."
        }
      ],
      "changed": [],
      "unchanged": 1
    }
  },
  "approved_spec": {
    "draft": {
      "problem": "Merchants poll for settlement.",
      "hld": "Send a signed webhook on settlement (D-1).",
      "lld": "webhook_deliveries table; retry with backoff.",
      "scope_in": null,
      "scope_out": null,
      "test_strategy": "Integration tests; AC-2 is checked by hand in staging."
    },
    "decisions": [
      {
        "ref": "D-1",
        "title": "Sign webhooks with HMAC",
        "question": "How do merchants verify a webhook?",
        "verdict": "HMAC-SHA256 over the raw body with a per-merchant secret",
        "level": "SHOULD",
        "status": "DECIDED"
      }
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given a settled payment, when the webhook is sent, then its signature verifies with the merchant secret",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-2",
        "text": "Given a merchant, when ops replays a webhook from the admin, then it is resent within 1 minute",
        "level": "manual",
        "manual": "yes",
        "status": "APPROVED"
      }
    ]
  },
  "current_spec": {
    "draft": {
      "problem": "Merchants poll for settlement.",
      "hld": "Send a signed webhook on settlement (D-1).",
      "lld": "webhook_deliveries table; retry with backoff.",
      "scope_in": null,
      "scope_out": null,
      "test_strategy": "Integration tests; AC-2 is checked by hand in staging."
    },
    "decisions": [
      {
        "ref": "D-1",
        "title": "Sign webhooks with HMAC",
        "question": "How do merchants verify a webhook?",
        "verdict": "HMAC-SHA256 over the raw body with a per-merchant secret",
        "level": "SHOULD",
        "status": "DECIDED"
      }
    ],
    "criteria": [
      {
        "ref": "AC-2",
        "text": "Given a merchant, when ops replays a webhook from the admin, then it is resent within 1 minute",
        "level": "manual",
        "manual": "yes",
        "status": "APPROVED"
      }
    ]
  },
  "approvals": []
}
```

### GET /api/initiatives/5/gates

Every gate: initiative gates once, task gates per task. Each: `{gate, scope, target, status, human_role, text, rules[{name, passed, failing, detail, args}], note, failing_rules}`.

`GET /api/initiatives/5/gates` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "gate": "GATE_DRAFT",
    "scope": "initiative",
    "target": null,
    "status": "PASSED",
    "human_role": "dri",
    "text": "Touchpoint 1 — the DRI approves the draft; approval creates baseline B-n",
    "rules": [
      {
        "name": "no_open_decision_in_draft_scope",
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      {
        "name": "no_open_gap_blocking_draft",
        "passed": false,
        "failing": [
          "G-2"
        ],
        "detail": "OPEN gaps block the spec",
        "args": {}
      },
      {
        "name": "no_open_review_items_on_spec",
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      "… (+4 more)"
    ],
    "note": "approved; preconditions that fail now are mid-build work, not a reopened draft",
    "failing_rules": [
      "no_open_gap_blocking_draft"
    ]
  },
  {
    "gate": "GATE_PR",
    "scope": "task",
    "target": "T-1",
    "status": "BLOCKED",
    "human_role": "engg",
    "text": "Touchpoint 3 — the engineer approves the task's drift report at the PR head",
    "rules": [
      {
        "name": "pr_state_in",
        "passed": false,
        "failing": [
          "T-1"
        ],
        "detail": "pr_state is none; needs open | approved",
        "args": {
          "states": [
            "open",
            "approved"
          ]
        }
      },
      {
        "name": "no_blocker_finding_open_at_sha",
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      {
        "name": "every_covered_ac_has_a_test",
        "passed": false,
        "failing": [
          "AC-2",
          "AC-3"
        ],
        "detail": "covered ACs with no test run row",
        "args": {}
      },
      "… (+3 more)"
    ],
    "note": "",
    "failing_rules": [
      "pr_state_in",
      "every_covered_ac_has_a_test",
      "approval_by_role"
    ]
  },
  {
    "gate": "GATE_PR",
    "scope": "task",
    "target": "T-2",
    "status": "BLOCKED",
    "human_role": "engg",
    "text": "Touchpoint 3 — the engineer approves the task's drift report at the PR head",
    "rules": [
      {
        "name": "pr_state_in",
        "passed": false,
        "failing": [
          "T-2"
        ],
        "detail": "pr_state is none; needs open | approved",
        "args": {
          "states": [
            "open",
            "approved"
          ]
        }
      },
      {
        "name": "no_blocker_finding_open_at_sha",
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      {
        "name": "every_covered_ac_has_a_test",
        "passed": false,
        "failing": [
          "AC-1",
          "AC-7"
        ],
        "detail": "covered ACs with no test run row",
        "args": {}
      },
      "… (+3 more)"
    ],
    "note": "",
    "failing_rules": [
      "pr_state_in",
      "every_covered_ac_has_a_test",
      "approval_by_role"
    ]
  },
  "… (+3 more)"
]
```

### GET /api/initiatives/5/tasks/T-2/gates

`GET /api/initiatives/5/tasks/T-2/gates` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "gate": "GATE_PR",
    "scope": "task",
    "target": "T-2",
    "status": "BLOCKED",
    "human_role": "engg",
    "text": "Touchpoint 3 — the engineer approves the task's drift report at the PR head",
    "rules": [
      {
        "name": "pr_state_in",
        "passed": false,
        "failing": [
          "T-2"
        ],
        "detail": "pr_state is none; needs open | approved",
        "args": {
          "states": [
            "open",
            "approved"
          ]
        }
      },
      {
        "name": "no_blocker_finding_open_at_sha",
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      "… (+4 more)"
    ],
    "note": "",
    "failing_rules": [
      "pr_state_in",
      "every_covered_ac_has_a_test",
      "… (+1 more)"
    ]
  }
]
```

### GET /api/deploy-guard?initiative_id=5&task=T-3&sha=a41c09e&environment=staging

CI/CD asks before a deploy: `decision` GO | NO-GO, `reasons`, each check.

`GET /api/deploy-guard?initiative_id=5&task=T-3&sha=a41c09e&environment=staging` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "decision": "NO-GO",
  "initiative_id": 5,
  "initiative": "order-events",
  "task": "T-3",
  "sha": "a41c09e",
  "environment": "staging",
  "reasons": [
    "GATE_VALIDATED: manual_acs_signed_by (AC-6)"
  ],
  "checks": [
    {
      "name": "GATE_PR",
      "passed": true,
      "detail": "passed"
    },
    {
      "name": "sha_matches_pr",
      "passed": true,
      "detail": "PR head a41c09e, deploying a41c09e"
    },
    "… (+3 more)"
  ],
  "drift": {
    "changes": 0,
    "explained": 0,
    "unexplained": 0,
    "pending_gaps": 1,
    "pending_decisions": 0,
    "other_changes": 0,
    "digest": "2e955487883a09bdcd5582737e965530635e0a3b5ce49a656c761298c4ec4f93",
    "status": "CLEAN"
  }
}
```

### POST /api/deploy-guard

Same check, recorded as a `deploy` row (`deploy` in the response).

`POST /api/deploy-guard` — X-Actor: github-actions · X-Actor-Kind: agent → **200**

Request:

```json
{
  "initiative_id": 5,
  "task": "T-3",
  "sha": "0000000",
  "environment": "production"
}
```

Response:

```json
{
  "decision": "NO-GO",
  "initiative_id": 5,
  "initiative": "order-events",
  "task": "T-3",
  "sha": "0000000",
  "environment": "production",
  "reasons": [
    "sha_matches_pr: PR head a41c09e, deploying 0000000",
    "approved_at_sha: engg approved at a41c09e",
    "… (+1 more)"
  ],
  "checks": [
    {
      "name": "GATE_PR",
      "passed": true,
      "detail": "passed"
    },
    {
      "name": "sha_matches_pr",
      "passed": false,
      "detail": "PR head a41c09e, deploying 0000000"
    },
    "… (+3 more)"
  ],
  "drift": {
    "changes": 0,
    "explained": 0,
    "unexplained": 0,
    "pending_gaps": 1,
    "pending_decisions": 0,
    "other_changes": 0,
    "digest": "2e955487883a09bdcd5582737e965530635e0a3b5ce49a656c761298c4ec4f93",
    "status": "CLEAN"
  },
  "deploy": "DEP-1"
}
```

## Worklist, next work, leases

### GET /api/initiatives/6/worklist

Every open item of an initiative, both lanes (`agent` / `human`), grouped by kind, with leases.

`GET /api/initiatives/6/worklist` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "initiative_id": 6,
  "initiative": "menu-sync-retries",
  "count": 2,
  "groups": {
    "review": [
      {
        "key": "review:6:24",
        "kind": "review",
        "lane": "agent",
        "initiative_id": 6,
        "initiative": "menu-sync-retries",
        "ref": "24",
        "title": "draft ← G-1",
        "why": "G-1 moved (status OPEN → ANSWERED) — revise draft, or say why it still holds",
        "person": "meera",
        "priority": 10,
        "target": "draft",
        "cause": "G-1",
        "review_item_id": 24,
        "lease": null
      }
    ],
    "draft": [
      {
        "key": "draft:6",
        "kind": "draft",
        "lane": "agent",
        "initiative_id": 6,
        "initiative": "menu-sync-retries",
        "ref": null,
        "title": "Draft is DRAFTING",
        "why": "no_open_review_items_on_spec (draft)",
        "person": null,
        "priority": 30,
        "lease": null
      }
    ]
  },
  "items": [
    {
      "key": "review:6:24",
      "kind": "review",
      "lane": "agent",
      "initiative_id": 6,
      "initiative": "menu-sync-retries",
      "ref": "24",
      "title": "draft ← G-1",
      "why": "G-1 moved (status OPEN → ANSWERED) — revise draft, or say why it still holds",
      "person": "meera",
      "priority": 10,
      "target": "draft",
      "cause": "G-1",
      "review_item_id": 24,
      "lease": null
    },
    {
      "key": "draft:6",
      "kind": "draft",
      "lane": "agent",
      "initiative_id": 6,
      "initiative": "menu-sync-retries",
      "ref": null,
      "title": "Draft is DRAFTING",
      "why": "no_open_review_items_on_spec (draft)",
      "person": null,
      "priority": 30,
      "lease": null
    }
  ]
}
```

### GET /api/initiatives/5/next-work

What the caller may take now (not leased by someone else), priority order, each with a `context` bundle. `?kind=` and `?person=` filter; `GET /api/next-work` spans all initiatives.

`GET /api/initiatives/5/next-work` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Response:

```json
{
  "count": 2,
  "items": [
    {
      "key": "gap:5:G-2",
      "kind": "gap",
      "lane": "human",
      "initiative_id": 5,
      "initiative": "order-events",
      "ref": "G-2",
      "title": "The outbox table can't be added to the orders schema in time",
      "why": "waiting on arjun",
      "person": "arjun",
      "priority": 20,
      "overdue": false,
      "sla_hours": 24,
      "lease": null,
      "context": {
        "record": {
          "ref": "G-2",
          "type": "gap",
          "title": "The outbox table can't be added to the orders schema in time",
          "status": "OPEN",
          "pill": "red",
          "line": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
          "rev": 1,
          "fields": {
            "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
            "kind": "deviation",
            "domain": "engg",
            "level": "MUST",
            "asked_by": "runner-sdk/implement-task",
            "why_now": "Implementing T-1 hit the orders schema ownership rule: T-1 cannot finish as D-1 is written.",
            "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables …",
            "options": [
              {
                "key": "separate-schema",
                "label": "Outbox in a separate schema",
                "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."
              },
              "… (+2 more)"
            ],
            "recommendation": "cdc",
            "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
            "blocks": [
              "D-1",
              "… (+1 more)"
            ],
            "proposed_change": "D-1 verdict: outbox → CDC via Debezium on the orders table. Add AC: CDC lag over 5 s for 2 min fires the alert. LLD event delivery section rewritten."
          },
          "created_by": "runner-sdk/implement-task",
          "created_at": "2026-10-30T05:41:00Z",
          "updated_by": "runner-sdk/implement-task",
          "updated_at": "2026-10-30T05:41:00Z",
          "links": {
            "out": [
              {
                "kind": "blocks",
                "to": "D-1"
              },
              "… (+4 more)"
            ],
            "in": []
          },
          "stamps": {
            "question": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "kind": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "domain": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "level": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "asked_by": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "why_now": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "context": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "options": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "recommendation": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "recommendation_why": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "blocks": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            },
            "proposed_change": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-30T05:41:00"
            }
          },
          "stale": [],
          "review_items": []
        },
        "cites": {
          "D-1": {
            "type": "decision",
            "title": "Transactional outbox",
            "status": "DECIDED",
            "line": "Transactional outbox"
          },
          "T-1": {
            "type": "task",
            "title": "Outbox table and relay",
            "status": "BLOCKED",
            "line": "Write the event row in the order transaction and relay it to orders.events"
          }
        },
        "review_items": []
      }
    },
    "… (+1 more)"
  ]
}
```

### POST /api/leases/claim

Lease an item. 409 with `error_data {holder, expires_at}` when someone else holds it.

`POST /api/leases/claim` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Request:

```json
{
  "item_key": "task:5:T-2",
  "ttl_min": 15
}
```

Response:

```json
{
  "item_key": "task:5:T-2",
  "holder": "runner-sdk",
  "acquired_at": "2026-10-30T07:41:34Z",
  "heartbeat_at": "2026-10-30T07:41:34Z",
  "expires_at": "2026-10-30T07:56:34Z"
}
```

### POST /api/leases/task:5:T-2/heartbeat

`POST /api/leases/task:5:T-2/heartbeat` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Request:

```json
{
  "ttl_min": 30
}
```

Response:

```json
{
  "item_key": "task:5:T-2",
  "holder": "runner-sdk",
  "acquired_at": "2026-10-30T07:41:34Z",
  "heartbeat_at": "2026-10-30T07:41:34Z",
  "expires_at": "2026-10-30T08:11:34Z"
}
```

### DELETE /api/leases/task:5:T-2

`DELETE /api/leases/task:5:T-2` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Response:

```json
{
  "item_key": "task:5:T-2",
  "released": true
}
```

## Activity and events

### GET /api/initiatives/5/activity?limit=4

Revisions and review-queue moves, newest first. Filters: `since` (ISO), `ref`, `actor` (prefix), `limit`.

`GET /api/initiatives/5/activity?limit=4` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "kind": "revision",
    "at": "2026-10-30T07:41:34Z",
    "ref": "DEP-1",
    "type": "deploy",
    "rev": 1,
    "action": "created",
    "title": "production T-3 @ 0000000",
    "status": "FAILED",
    "actor": "github-actions",
    "actor_kind": "agent",
    "note": "deploy_guard NO-GO",
    "because": [],
    "batch_id": "b2522050-1124-4892-a2e7-32aa036364ce"
  },
  {
    "kind": "revision",
    "at": "2026-10-30T05:41:00Z",
    "ref": "G-2",
    "type": "gap",
    "rev": 1,
    "action": "created",
    "title": "The outbox table can't be added to the orders schema in time",
    "status": "OPEN",
    "actor": "runner-sdk/implement-task",
    "actor_kind": "agent",
    "note": "",
    "because": [],
    "batch_id": "5b4629d2-5ba1-4625-93e6-e4e38ed5267c"
  },
  {
    "kind": "revision",
    "at": "2026-10-28T11:41:00Z",
    "ref": "APR-2",
    "type": "approval",
    "rev": 1,
    "action": "created",
    "title": "engg approves T-3",
    "status": "CURRENT",
    "actor": "arjun",
    "actor_kind": "human",
    "note": "completed by the service",
    "because": [],
    "batch_id": "093e4a7b-ce02-4d37-a582-00446791384c"
  },
  {
    "kind": "revision",
    "at": "2026-10-28T07:41:00Z",
    "ref": "R-1",
    "type": "test_run",
    "rev": 1,
    "action": "created",
    "title": "infra-terraform plan + policy tests @ a41c09e",
    "status": "GREEN",
    "actor": "runner-sdk/write-tests",
    "actor_kind": "agent",
    "note": "",
    "because": [],
    "batch_id": "770381ba-669a-4e84-9dab-a49b72a1853a"
  }
]
```

### GET /api/initiatives/5/events?since=0&limit=3

The event log (`record_written`, `baseline_created`, `review_item_queued`, `review_item_resolved`, `gate_changed`, `initiative_created`, `lease_claimed`, `lease_released`). Poll with `since=<last id>`; `GET /api/events` spans all initiatives.

`GET /api/initiatives/5/events?since=0&limit=3` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "id": 202,
    "ts": "2026-10-24T07:41:00Z",
    "kind": "initiative_created",
    "subject": "order-events",
    "actor": "priya",
    "batch_id": "",
    "payload": {
      "work_item_url": "https://dev.azure.com/navanta/commerce/_workitems/edit/4821"
    }
  },
  {
    "id": 203,
    "ts": "2026-10-24T07:41:00Z",
    "kind": "record_written",
    "subject": "initiative",
    "actor": "priya",
    "batch_id": "11b5cd15-c316-422c-a83e-02b912157321",
    "payload": {
      "type": "initiative",
      "rev": 1,
      "action": "created",
      "actor_kind": "human"
    }
  },
  {
    "id": 204,
    "ts": "2026-10-24T07:41:00Z",
    "kind": "record_written",
    "subject": "A-1",
    "actor": "priya",
    "batch_id": "11b5cd15-c316-422c-a83e-02b912157321",
    "payload": {
      "type": "assignment",
      "rev": 1,
      "action": "created",
      "actor_kind": "human"
    }
  }
]
```

## Global scope: standards and learnings

### GET /api/standards

`GET /api/standards` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "ref": "STD-1",
    "type": "standard",
    "title": "Idempotent delivery",
    "status": "ENFORCED",
    "pill": "green",
    "line": "Events reach the broker exactly once per state change: no dual-writes, every consumer dedupes by event_id.",
    "rev": 1,
    "fields": {
      "rule": "Events reach the broker exactly once per state change: no dual-writes, every consumer dedupes by event_id.",
      "level": "MUST",
      "applies_to": "navanta/*",
      "owner": "platform",
      "state": "enforced"
    },
    "created_by": "priya",
    "created_at": "2026-09-30T07:41:00Z",
    "updated_by": "priya",
    "updated_at": "2026-09-30T07:41:00Z"
  },
  {
    "ref": "STD-2",
    "type": "standard",
    "title": "Retries with backoff and jitter",
    "status": "ACTIVE",
    "pill": "green",
    "line": "Outbound calls retry with exponential backoff and jitter, within a retry budget.",
    "rev": 1,
    "fields": {
      "rule": "Outbound calls retry with exponential backoff and jitter, within a retry budget.",
      "level": "SHOULD",
      "applies_to": "navanta/*",
      "owner": "platform",
      "state": "active"
    },
    "created_by": "priya",
    "created_at": "2026-09-30T07:41:00Z",
    "updated_by": "priya",
    "updated_at": "2026-09-30T07:41:00Z"
  },
  "… (+1 more)"
]
```

### GET /api/learnings

`GET /api/learnings` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "ref": "L-1",
    "type": "learning",
    "title": "Check for an existing platform CDC connector before designing an outbox.",
    "status": "DRAFT",
    "pill": "amber",
    "line": "Check for an existing platform CDC connector before designing an outbox.",
    "rev": 1,
    "fields": {
      "text": "Check for an existing platform CDC connector before designing an outbox.",
      "applies_to": "event publishing",
      "source": "inventory-sync-v3:G-1",
      "provenance": "inventory-sync-v3 delta sync deviation, answered by meera"
    },
    "created_by": "runner-sdk/retro-skill",
    "created_at": "2026-09-30T07:41:00Z",
    "updated_by": "runner-sdk/retro-skill",
    "updated_at": "2026-09-30T07:41:00Z"
  }
]
```

### POST /api/learnings/L-1/promote

**human** — promote a learning.

`POST /api/learnings/L-1/promote` — X-Actor: priya · X-Actor-Kind: human → **200**

Response:

```json
{
  "ok": true,
  "batch_id": "50c81000-fe4a-486f-abcb-cfad656ce89b",
  "results": [
    {
      "index": 0,
      "ref": "L-1",
      "type": "learning",
      "action": "updated",
      "rev": 2,
      "status": "PROMOTED",
      "errors": [],
      "warnings": []
    }
  ],
  "minted": {},
  "review_items": [],
  "stale": [],
  "gates_changed": [],
  "baseline": null,
  "replayed": false
}
```

### POST /api/global/records

Write standards / learnings (global scope, refs `STD-n` / `L-n`). Same op shape as record writes.

`POST /api/global/records` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Request:

```json
{
  "agent": "retro-skill",
  "ops": [
    {
      "type": "learning",
      "fields": {
        "text": "Replay endpoints need idempotency keys.",
        "source": "payment-webhooks:AC-2",
        "provenance": "QA sign-off"
      }
    }
  ]
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "bf698c48-052c-4079-9391-c2284fcb4259",
  "results": [
    {
      "index": 0,
      "ref": "L-2",
      "type": "learning",
      "action": "created",
      "rev": 1,
      "status": "DRAFT",
      "errors": [],
      "warnings": []
    }
  ],
  "minted": {
    "#0": "L-2"
  },
  "review_items": [],
  "stale": [],
  "gates_changed": [],
  "baseline": null,
  "replayed": false
}
```
