# SDLC Record Service — REST API for the web UI

Every endpoint the UI needs, with **real** request/response examples captured from the
running service against the demo data (`make seed`). Regenerate with
`.venv/bin/python scripts/gen_api_docs.py`. Long lists are trimmed to their first items
(`"… (+N more)"`) and long strings to 200 chars — the shapes are exact.

## Conventions

- **Base URL**: `http://localhost:8791` (`make dev`). All JSON routes are under `/api`.
  The Vite dev server (`http://localhost:5173`) is allowed by CORS.
- **Who is calling** (AUTH_MODE=header): every request sends `X-Actor: <person handle>`.
  The web UI is a human: send `X-Actor-Kind: human` (it is also the default when no
  `agent` label is given). Agents send `X-Actor-Kind: agent`. Human-only endpoints (marked
  **human**) return **403** with `error_code: "HUMAN_ONLY"` to anyone else.
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
  `/i/<slug>/r/<ref>`.
- **Record JSON** (lists, detail, everywhere): `{ref, type, title, status, pill, line,
  rev, fields, created_by, created_at, updated_by, updated_at}`; the detail endpoint adds
  `links {out: [{kind, to}], in: [{kind, from}]}`, `stamps` (who set each field, and as
  what), `stale` (narratives to rewrite) and open `review_items`. `line` is the type's
  one-line summary field (a gap's question, a decision's verdict…). Field names, types,
  limits, vocabularies and which fields are human-only come from `GET /api/blueprint`.

## Page → endpoints

| Page | Reads | Writes |
|---|---|---|
| `/` home | `GET /api/initiatives`, `GET /api/people` | — |
| `/new` start a feature | — | `POST /api/initiatives` |
| `/inbox/:person` (touchpoint 2) | `GET /api/inbox/{person}` | `POST …/gaps/{ref}/answer`, `POST …/decisions/{ref}/rule`, `POST …/approvals`, `POST …/criteria/{ref}/sign`, `POST …/reviews/{id}/resolve` |
| `/i/:slug` initiative | `GET /api/initiatives/{slug}`, `GET …/worklist` | `POST …/snapshot` (re-pin requirement) |
| `/i/:slug/draft` (touchpoint 1) | `GET /api/initiatives/{slug}/draft` | `POST …/approvals` `{target: "draft", role: "dri"}`, `POST …/gaps/{ref}/answer` |
| `/i/:slug/drift` | `GET …/drift` (`?baseline=B-n` for older) | — |
| `/i/:slug/t/:ref` (touchpoint 3) | `GET …/tasks/{ref}` (task + GATE_PR + scoped drift) | `POST …/approvals` `{target: "T-n", role: "engg", at_sha}` |
| `/i/:slug/r/:ref` record | `GET …/records/{ref}`, `GET …/records/{ref}/history` | `POST …/criteria/{ref}/retire` (an AC) |
| `/i/:slug/reviews` | `GET …/reviews?status=open|upheld|revised|dismissed|all` | `POST …/reviews/{id}/resolve` |
| `/i/:slug/activity` | `GET …/activity`, `GET …/events?since=` | — |
| `/standards`, `/learnings` | `GET /api/standards`, `GET /api/learnings` | `POST /api/learnings/{ref}/promote` |
| `/blueprint` | `GET /api/blueprint`, `GET /api/blueprint/lifecycle` | — |

The three human touchpoints:

1. **Draft review** — `/i/:slug/draft`. Show the draft sections (`problem`, `hld`, `lld`,
   `scope_in`, `scope_out`, `test_strategy` — markdown), each decision with its `options`
   and `verdict`, each AC, each gap, the draft-phase catalog and `gate` (GATE_DRAFT, rule by
   rule). The **Approve** button is enabled when `can_approve` is true; otherwise list
   `approval_blockers`. Only the `approver` (the DRI) may approve.
2. **Gap reviews** — `/inbox/:person`. Each item has `kind` (`gap` · `decision` ·
   `approval` · `review_item` · `manual_ac`), its context, `options` + `recommendation`
   (gaps), `blocks`, `sla_hours`, `due_at`, `overdue`. Answer = pick an option (`choice`)
   or type (`answer`).
3. **Final PR review** — `/i/:slug/t/:ref`. Render `drift` (the task-scoped drift report:
   `entries` as a timeline between `approved_spec` and `current_spec`, `spec_diff`,
   `unexplained`), the `gate` (GATE_PR) and the PR. **Approve** posts the PR head sha
   (`task.fields.pr_sha`); the service pins the report's `digest`. A later push or new drift
   makes the approval `STALE` and the gate re-blocks on its own.

### The drift report (`GET /api/initiatives/{slug}/drift`)

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

`GET /health` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "healthy"
}
```

### GET /api/blueprint

Record types (fields with limits, vocabularies, `actor: human`, typed-link `targets`), status vocabularies, `open` statuses, pill colours. Lists trimmed to 1 here; the real response has every type and field.

`GET /api/blueprint` — X-Actor: chandra · X-Actor-Kind: human → **200**

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

`GET /api/blueprint/lifecycle` — X-Actor: chandra · X-Actor-Kind: human → **200**

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
      "text": "DONE if pr_state=merged and every covered AC has a green test run at pr_sha · STUCK if ci_attempts≥3 or review_rounds≥3 · BLOCKED if a depends_on task is not DONE or an implemented MUST decision is OP…"
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

Home page: every initiative with phase, people, counts, baseline and drift summary.

`GET /api/initiatives` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "slug": "refund-events",
    "title": "Refund events",
    "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4307",
    "created_by": "chandra",
    "created_at": "2026-10-26T09:00:00Z",
    "closed_at": null,
    "snapshot_hash": "5af69c931f5fef779dccc74e7f345e7a5893c914b230e7fe34fe1e9f62084450",
    "phase": "DRAFT",
    "pill": "amber",
    "summary": "",
    "dri": "chandra",
    "engg": "omar",
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
  {
    "slug": "order-events",
    "title": "Order events via an outbox",
    "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4211",
    "created_by": "chandra",
    "created_at": "2026-10-22T09:00:00Z",
    "closed_at": null,
    "snapshot_hash": "2499256f05741306b27d444332efe0bd4a78f9ff702bd7fddc0f101f754f39c3",
    "phase": "BUILD",
    "pill": "amber",
    "summary": "Replace order-table polling with order events (CloudEvents via an outbox).",
    "dri": "chandra",
    "engg": "priya",
    "counts": {
      "open_gaps": 0,
      "open_decisions": 0,
      "tasks": 2,
      "tasks_done": 0,
      "open_review_items": 0
    },
    "baseline": "B-1",
    "drift": {
      "changes": 3,
      "explained": 3,
      "unexplained": 0,
      "pending_gaps": 0,
      "pending_decisions": 0,
      "other_changes": 0
    }
  }
]
```

### POST /api/initiatives

**Start a feature** (the intake; `/new`). `requirement` (markdown), `title`, `dri`, `engg` are required; `slug` defaults from the title; `work_item_url` (Azure DevOps link), `product`, `design`, `qa`, `prd_refs` are optional. Pins `spec_snapshot` with its hash and writes the assignments. Returns the same body as `GET /api/initiatives/{slug}`. 422 lists every missing field in `error_data.errors`; 409 if an explicit `slug` exists.

`POST /api/initiatives` — X-Actor: chandra · X-Actor-Kind: human → **201**

Request:

```json
{
  "title": "Payment webhooks",
  "requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles.",
  "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
  "dri": "chandra",
  "engg": "priya",
  "product": "maya",
  "qa": "sam"
}
```

Response:

```json
{
  "initiative": {
    "slug": "payment-webhooks",
    "title": "Payment webhooks",
    "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
    "created_by": "chandra",
    "created_at": "2026-10-28T20:22:20Z",
    "closed_at": null,
    "snapshot_hash": "b1ed29dab1975f335bc0e6d16d4ea871a009e6e13d2622775a6a9c948a1a233b",
    "phase": "DRAFT",
    "pill": "amber",
    "summary": "",
    "spec_snapshot": {
      "requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles.",
      "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
      "created_by": "chandra",
      "at": "2026-10-28T20:22:20Z"
    }
  },
  "phase": "DRAFT",
  "assignments": [
    {
      "ref": "A-1",
      "person": "chandra",
      "role": "dri",
      "scope": [
        "initiative"
      ],
      "status": "ACTIVE"
    },
    {
      "ref": "A-2",
      "person": "priya",
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

### GET /api/initiatives/order-events

**Initiative state**: the initiative with its `spec_snapshot`, `phase`, assignments, initiative-scope gates (rule by rule), tasks with their GATE_PR status and drift summary, counts by type and status, open refs, the current baseline, drift summary, stale narratives, and every catalog (phase → items with `disposition`: `addressed` · `not_applicable` · `UNASSESSED`).

`GET /api/initiatives/order-events` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "initiative": {
    "slug": "order-events",
    "title": "Order events via an outbox",
    "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4211",
    "created_by": "chandra",
    "created_at": "2026-10-22T09:00:00Z",
    "closed_at": null,
    "snapshot_hash": "2499256f05741306b27d444332efe0bd4a78f9ff702bd7fddc0f101f754f39c3",
    "phase": "BUILD",
    "pill": "amber",
    "summary": "Replace order-table polling with order events (CloudEvents via an outbox).",
    "spec_snapshot": {
      "requirement": "# Order events\n\nDownstream services (billing, notifications, analytics) poll the `orders` table every\n30 seconds to find state changes. Polling costs ~400 QPS on the primary and adds up to 30s\nof late…",
      "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4211",
      "created_by": "chandra",
      "at": "2026-10-22T09:00:00Z"
    }
  },
  "phase": "BUILD",
  "assignments": [
    {
      "ref": "A-1",
      "person": "chandra",
      "role": "dri",
      "scope": [
        "initiative"
      ],
      "status": "ACTIVE"
    },
    {
      "ref": "A-2",
      "person": "priya",
      "role": "engg",
      "scope": [
        "initiative"
      ],
      "status": "ACTIVE"
    },
    {
      "ref": "A-3",
      "person": "maya",
      "role": "product",
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
          "passed": true,
          "failing": [],
          "detail": "",
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
      "note": "",
      "failing_rules": []
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
            "AC-3",
            "AC-4"
          ],
          "detail": "ACs whose latest covering run is not GREEN",
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
        "every_ac_green"
      ]
    }
  ],
  "tasks": [
    {
      "ref": "T-1",
      "type": "task",
      "title": "CDC transformer to order-events",
      "status": "IN_REVIEW",
      "pill": "amber",
      "line": "Map Debezium order row changes to CloudEvents on order-events",
      "rev": 3,
      "fields": {
        "goal": "Map Debezium order row changes to CloudEvents on order-events",
        "repo": "acme/orders-service",
        "template": "python-service-v3",
        "implements": [
          "D-2",
          "D-4"
        ],
        "covers": [
          "AC-1",
          "AC-2",
          "AC-5"
        ],
        "rollback": "Turn off order_events.enabled; the relay stops, the outbox drains on re-enable.",
        "pr_url": "https://github.com/acme/orders-service/pull/482",
        "pr_state": "open",
        "pr_sha": "9f3c2e1a7b4d",
        "ci_attempts": "1",
        "review_rounds": "1",
        "tracker_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4212"
      },
      "created_by": "runner-sdk/plan-skill",
      "created_at": "2026-10-24T09:20:00Z",
      "updated_by": "runner-sdk/implement-task",
      "updated_at": "2026-10-26T16:45:00Z",
      "gate_pr": {
        "status": "PASSED",
        "failing_rules": []
      },
      "drift": {
        "changes": 3,
        "explained": 3,
        "unexplained": 0,
        "pending_gaps": 0,
        "pending_decisions": 0,
        "other_changes": 0
      }
    },
    {
      "ref": "T-2",
      "type": "task",
      "title": "Envelope, partitioning and retention",
      "status": "IN_PROGRESS",
      "pill": "amber",
      "line": "CloudEvents envelope with order_id partition key; 7-day topic retention",
      "rev": 2,
      "fields": {
        "goal": "CloudEvents envelope with order_id partition key; 7-day topic retention",
        "repo": "acme/event-contracts",
        "template": "contracts-lib",
        "implements": [
          "D-2",
          "D-3"
        ],
        "covers": [
          "AC-3",
          "AC-4"
        ],
        "rollback": "Revert the contract version; the topic config is idempotent.",
        "pr_url": "https://github.com/acme/event-contracts/pull/91",
        "pr_state": "draft",
        "pr_sha": "c41d09e2"
      },
      "created_by": "runner-sdk/plan-skill",
      "created_at": "2026-10-24T09:20:00Z",
      "updated_by": "runner-sdk/implement-task",
      "updated_at": "2026-10-27T15:00:00Z",
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
        "pending_gaps": 0,
        "pending_decisions": 0,
        "other_changes": 3
      }
    }
  ],
  "counts": {
    "initiative": {
      "BUILD": 1
    },
    "assignment": {
      "ACTIVE": 5
    },
    "draft": {
      "APPROVED": 1
    },
    "decision": {
      "SUPERSEDED": 1,
      "DECIDED": 2,
      "PROVISIONAL": 1
    },
    "gap": {
      "ANSWERED": 2
    },
    "acceptance_criterion": {
      "APPROVED": 4,
      "ADDED_AFTER_BASELINE": 1
    },
    "task": {
      "IN_REVIEW": 1,
      "IN_PROGRESS": 1
    },
    "test_run": {
      "GREEN": 1
    },
    "deploy": {
      "PENDING": 1
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
    "gaps": [],
    "review_items": 0
  },
  "stuck": [],
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 1 approved by chandra",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "chandra",
    "draft_rev": "1",
    "members": [
      "draft",
      "D-1",
      "D-2",
      "… (+6 more)"
    ],
    "created_at": "2026-10-23T15:40:00Z"
  },
  "drift": {
    "changes": 3,
    "explained": 3,
    "unexplained": 0,
    "pending_gaps": 0,
    "pending_decisions": 0,
    "other_changes": 0
  },
  "stale": [
    "initiative.summary",
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
        "note": "Events carry order ids and states only; no PII. Bus topic ACL limited to the consumers listed in the HLD.",
        "refs": ""
      },
      {
        "item": "rollback_plan",
        "phase": "draft",
        "text": "how a bad deploy is undone",
        "derived": false,
        "disposition": "addressed",
        "note": "Feature flag order_events.enabled; consumers keep polling until the flag has been on for 7 days.",
        "refs": ""
      },
      {
        "item": "observability",
        "phase": "draft",
        "text": "metrics, logs, alerts that show it works",
        "derived": false,
        "disposition": "addressed",
        "note": "Publish lag p99, relay errors, events/s per type; alert on lag > 5s for 5 min.",
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

### GET /api/initiatives/refund-events/draft

**Draft review page** (touchpoint 1). `can_approve`, `approval_blockers[{rule, failing, detail}]` and `approver` drive the Approve button.

`GET /api/initiatives/refund-events/draft` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "initiative": {
    "slug": "refund-events",
    "title": "Refund events",
    "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4307",
    "created_by": "chandra",
    "created_at": "2026-10-26T09:00:00Z",
    "closed_at": null,
    "snapshot_hash": "5af69c931f5fef779dccc74e7f345e7a5893c914b230e7fe34fe1e9f62084450",
    "phase": "DRAFT",
    "pill": "amber",
    "summary": "",
    "spec_snapshot": {
      "requirement": "# Refund events\nFinance needs an event per refund (full and partial) to reconcile payouts daily. Today they export CSVs from the admin.\n\n- One event per refund state change.\n- Must reconcile to the pa…",
      "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4307",
      "created_by": "chandra",
      "at": "2026-10-26T09:00:00Z"
    }
  },
  "draft": {
    "ref": "draft",
    "type": "draft",
    "title": "Draft",
    "status": "DRAFTING",
    "pill": "amber",
    "line": null,
    "rev": 1,
    "fields": {
      "problem": "Finance reconciles refunds from CSV exports. Done = every refund state change is an event that reconciles to the provider report.",
      "hld": "CDC on `refunds` (D-1) through the order-events transformer; granularity per D-2 (open).",
      "test_strategy": "Integration tests with the provider sandbox; a reconciliation test over a fixed day of refunds.",
      "decisions": [
        "D-1",
        "D-2"
      ],
      "criteria": [
        "AC-1"
      ]
    },
    "created_by": "runner-sdk/draft-skill",
    "created_at": "2026-10-26T11:30:00Z",
    "updated_by": "runner-sdk/draft-skill",
    "updated_at": "2026-10-26T11:30:00Z",
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
        "… (+3 more)"
      ],
      "in": []
    },
    "stamps": {
      "problem": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-26T11:30:00"
      },
      "hld": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-26T11:30:00"
      },
      "test_strategy": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-26T11:30:00"
      },
      "decisions": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-26T11:30:00"
      },
      "criteria": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-26T11:30:00"
      }
    },
    "stale": [],
    "review_items": []
  },
  "decisions": [
    {
      "ref": "D-1",
      "type": "decision",
      "title": "Reuse the order-events pipeline",
      "status": "DECIDED",
      "pill": "green",
      "line": "Reuse the CDC pipeline from order-events (D-4 there) on the refunds table",
      "rev": 1,
      "fields": {
        "question": "Do refund events get their own pipeline?",
        "domain": "engg",
        "level": "SHOULD",
        "verdict": "Reuse the CDC pipeline from order-events (D-4 there) on the refunds table",
        "rationale": "Same delivery guarantees; one pipeline to operate.",
        "decided_by": "runner-sdk/draft-skill",
        "decided_on": "2026-10-26"
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-26T11:30:00Z",
      "updated_by": "runner-sdk/draft-skill",
      "updated_at": "2026-10-26T11:30:00Z",
      "links": {
        "out": [],
        "in": [
          {
            "kind": "contains",
            "from": "draft"
          },
          {
            "kind": "mentions",
            "from": "draft"
          },
          "… (+1 more)"
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "domain": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "level": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "verdict": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "rationale": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "decided_by": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "decided_on": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        }
      },
      "stale": [],
      "review_items": [],
      "superseded_by": [],
      "sourced_acs": [
        "AC-1"
      ]
    },
    {
      "ref": "D-2",
      "type": "decision",
      "title": "Partial refund granularity",
      "status": "OPEN",
      "pill": "red",
      "line": null,
      "rev": 1,
      "fields": {
        "question": "Is a partial refund one event, or one event per refunded line?",
        "domain": "product",
        "level": "MUST",
        "options": [
          {
            "name": "per-refund",
            "consequences": "one event with a lines[] array",
            "cost_risk": "finance sums lines"
          },
          {
            "name": "per-line",
            "consequences": "one event per refunded line",
            "cost_risk": "more events; simpler sums"
          }
        ]
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-26T11:30:00Z",
      "updated_by": "runner-sdk/draft-skill",
      "updated_at": "2026-10-26T11:30:00Z",
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
          "… (+2 more)"
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "domain": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "level": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "options": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        }
      },
      "stale": [],
      "review_items": [],
      "superseded_by": [],
      "sourced_acs": []
    }
  ],
  "criteria": [
    {
      "ref": "AC-1",
      "type": "acceptance_criterion",
      "title": "Given a refund reaches SETTLED, when CDC runs, then one refund event with the amount in minor units is published",
      "status": "PROPOSED",
      "pill": "amber",
      "line": "Given a refund reaches SETTLED, when CDC runs, then one refund event with the amount in minor units is published",
      "rev": 1,
      "fields": {
        "text": "Given a refund reaches SETTLED, when CDC runs, then one refund event with the amount in minor units is published",
        "level": "integration",
        "source": [
          "D-1"
        ]
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-26T11:30:00Z",
      "updated_by": "runner-sdk/draft-skill",
      "updated_at": "2026-10-26T11:30:00Z",
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
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "level": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "source": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        }
      },
      "stale": [],
      "review_items": []
    }
  ],
  "gaps": [
    {
      "ref": "G-1",
      "type": "gap",
      "title": "Partial refunds: one event or one per line?",
      "status": "OPEN",
      "pill": "red",
      "line": "When a customer is refunded 2 of 5 items, does finance want one event or one per refunded line?",
      "rev": 1,
      "fields": {
        "question": "When a customer is refunded 2 of 5 items, does finance want one event or one per refunded line?",
        "kind": "unknown",
        "domain": "product",
        "asked_by": "runner-sdk/draft-skill",
        "why_now": "D-2 (a MUST decision) cannot be ruled without it; the schema depends on it.",
        "context": "Order 90311: 5 items, items 2 and 4 refunded (€18.40 + €6.10). Per-refund: one event, lines[2]. Per-line: two events. The provider report lists one row per refund, not per line.",
        "options": [
          {
            "key": "per-refund",
            "label": "One event per refund",
            "consequence": "matches the provider report row for row"
          },
          {
            "key": "per-line",
            "label": "One event per line",
            "consequence": "finance aggregates lines to match the report"
          }
        ],
        "recommendation": "per-refund",
        "recommendation_why": "Reconciliation is against the provider report, which is per refund.",
        "blocks": [
          "D-2"
        ]
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-26T11:30:00Z",
      "updated_by": "runner-sdk/draft-skill",
      "updated_at": "2026-10-26T11:30:00Z",
      "links": {
        "out": [
          {
            "kind": "blocks",
            "to": "D-2"
          },
          {
            "kind": "mentions",
            "to": "D-2"
          }
        ],
        "in": []
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "kind": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "domain": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "asked_by": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "why_now": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "context": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "options": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "recommendation": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "recommendation_why": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
        },
        "blocks": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-26T11:30:00"
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
      "… (+3 more)"
    ]
  },
  "can_approve": false,
  "approver": "chandra",
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
    },
    "… (+2 more)"
  ],
  "approvals": [],
  "baselines": [],
  "review_items": []
}
```

### GET /api/initiatives/order-events/draft (approved)

The same page once approved: `gate.status` PASSED, `baselines[]`, `approvals[]`; D-1 shows `superseded_by: ["D-4"]`.

`GET /api/initiatives/order-events/draft` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "initiative": {
    "slug": "order-events",
    "title": "Order events via an outbox",
    "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4211",
    "created_by": "chandra",
    "created_at": "2026-10-22T09:00:00Z",
    "closed_at": null,
    "snapshot_hash": "2499256f05741306b27d444332efe0bd4a78f9ff702bd7fddc0f101f754f39c3",
    "phase": "BUILD",
    "pill": "amber",
    "summary": "Replace order-table polling with order events (CloudEvents via an outbox).",
    "spec_snapshot": {
      "requirement": "# Order events\n\nDownstream services (billing, notifications, analytics) poll the `orders` table every\n30 seconds to find state changes. Polling costs ~400 QPS on the primary and adds up to 30s\nof late…",
      "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4211",
      "created_by": "chandra",
      "at": "2026-10-22T09:00:00Z"
    }
  },
  "draft": {
    "ref": "draft",
    "type": "draft",
    "title": "Draft",
    "status": "APPROVED",
    "pill": "green",
    "line": null,
    "rev": 1,
    "fields": {
      "summary": "Publish order state changes as CloudEvents (D-2) through a transactional outbox (D-1), kept 7 days for replay (D-3).",
      "problem": "Consumers poll `orders` every 30s (~400 QPS on the primary, up to 30s notification latency). Done = every state change is on the bus within 5s, none lost, replayable for 7 days.",
      "hld": "Order writes insert an `order_outbox` row in the same transaction (D-1). A relay publishes outbox rows as CloudEvents partitioned by `order_id` (D-2) to `order-events`, retained 7 days (D-3).\n\n```merm…",
      "lld": "- `order_outbox(id bigint pk, order_id, type, payload json, created_at, published_at null)`\n- Relay: `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`, publish, set `p…",
      "scope_in": [
        "All six order state transitions",
        "Relay with lag metrics and alert",
        "… (+1 more)"
      ],
      "scope_out": [
        "Backfill of historical orders",
        "Migrating consumers off polling (each team owns theirs)"
      ],
      "test_strategy": "Integration tests against MySQL + a local Kafka for AC-1..AC-3 (kill the relay mid-batch for AC-2). AC-4 runs in staging against the real topic retention. No manual ACs.",
      "decisions": [
        "D-1",
        "D-2",
        "… (+1 more)"
      ],
      "criteria": [
        "AC-1",
        "AC-2",
        "… (+2 more)"
      ],
      "submitted_rev": "1"
    },
    "created_by": "runner-sdk/draft-skill",
    "created_at": "2026-10-22T11:30:00Z",
    "updated_by": "runner-sdk/draft-skill",
    "updated_at": "2026-10-22T11:30:00Z",
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
        "… (+11 more)"
      ],
      "in": [
        {
          "kind": "approves",
          "from": "APR-1"
        }
      ]
    },
    "stamps": {
      "summary": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "problem": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "hld": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "lld": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "scope_in": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "scope_out": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "test_strategy": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "decisions": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "criteria": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
      },
      "submitted_rev": {
        "by": "runner-sdk/draft-skill",
        "kind": "agent",
        "at": "2026-10-22T11:30:00"
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
      "title": "Publish through a transactional outbox",
      "status": "SUPERSEDED",
      "pill": "grey",
      "line": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
      "rev": 1,
      "fields": {
        "question": "How do order state changes reach the event bus without being lost?",
        "domain": "engg",
        "level": "SHOULD",
        "options": [
          {
            "name": "outbox",
            "consequences": "order_outbox row written in the order transaction; a relay publishes it",
            "cost_risk": "one new table, a relay process"
          },
          {
            "name": "dual-write",
            "consequences": "publish after commit from the request handler",
            "cost_risk": "events lost on crash between commit and publish"
          },
          "… (+1 more)"
        ],
        "verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
        "rationale": "Atomic with the state change, no new infrastructure. Dual-write loses events on crash; CDC was not known to be available.",
        "decided_by": "runner-sdk/draft-skill",
        "decided_on": "2026-10-22"
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-22T11:30:00Z",
      "updated_by": "runner-sdk/draft-skill",
      "updated_at": "2026-10-22T11:30:00Z",
      "links": {
        "out": [],
        "in": [
          {
            "kind": "blocks",
            "from": "G-2"
          },
          {
            "kind": "contains",
            "from": "draft"
          },
          "… (+5 more)"
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "domain": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "level": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "options": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "verdict": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "rationale": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "decided_by": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "decided_on": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        }
      },
      "stale": [],
      "review_items": [],
      "superseded_by": [
        "D-4"
      ],
      "sourced_acs": [
        "AC-1",
        "AC-2"
      ]
    },
    {
      "ref": "D-2",
      "type": "decision",
      "title": "CloudEvents envelope, partitioned by order_id",
      "status": "DECIDED",
      "pill": "green",
      "line": "CloudEvents 1.0 JSON; partition key order_id",
      "rev": 2,
      "fields": {
        "question": "Which envelope and partition key do order events use?",
        "domain": "engg",
        "level": "SHOULD",
        "options": [
          {
            "name": "cloudevents",
            "consequences": "consumers reuse their CloudEvents parser",
            "cost_risk": "low"
          },
          {
            "name": "custom-json",
            "consequences": "one more schema to maintain",
            "cost_risk": "medium"
          }
        ],
        "verdict": "CloudEvents 1.0 JSON; partition key order_id",
        "rationale": "Billing, notifications and analytics already parse CloudEvents. G-1: billing needs per-order ordering, so order_id is the partition key.",
        "decided_by": "runner-sdk/draft-skill",
        "decided_on": "2026-10-22"
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-22T11:30:00Z",
      "updated_by": "runner-sdk/draft-skill",
      "updated_at": "2026-10-23T11:00:00Z",
      "links": {
        "out": [
          {
            "kind": "mentions",
            "to": "G-1"
          }
        ],
        "in": [
          {
            "kind": "blocks",
            "from": "G-1"
          },
          {
            "kind": "contains",
            "from": "draft"
          },
          "… (+5 more)"
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "domain": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "level": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "options": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "verdict": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "rationale": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-23T11:00:00"
        },
        "decided_by": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "decided_on": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        }
      },
      "stale": [],
      "review_items": [],
      "superseded_by": [],
      "sourced_acs": [
        "AC-3"
      ]
    },
    "… (+2 more)"
  ],
  "criteria": [
    {
      "ref": "AC-1",
      "type": "acceptance_criterion",
      "title": "Given an order state change, when the order transaction commits, then exactly one event for it is published",
      "status": "APPROVED",
      "pill": "green",
      "line": "Given an order state change, when the order transaction commits, then exactly one event for it is published",
      "rev": 1,
      "fields": {
        "text": "Given an order state change, when the order transaction commits, then exactly one event for it is published",
        "level": "integration",
        "source": [
          "D-1"
        ]
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-22T11:30:00Z",
      "updated_by": "runner-sdk/draft-skill",
      "updated_at": "2026-10-22T11:30:00Z",
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
          },
          "… (+2 more)"
        ]
      },
      "stamps": {
        "text": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "level": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "source": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        }
      },
      "stale": [],
      "review_items": []
    },
    {
      "ref": "AC-2",
      "type": "acceptance_criterion",
      "title": "Given the relay is down for 10 minutes, when it restarts, then every pending event is published with no loss",
      "status": "APPROVED",
      "pill": "green",
      "line": "Given the relay is down for 10 minutes, when it restarts, then every pending event is published with no loss",
      "rev": 1,
      "fields": {
        "text": "Given the relay is down for 10 minutes, when it restarts, then every pending event is published with no loss",
        "level": "integration",
        "source": [
          "D-1"
        ]
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-22T11:30:00Z",
      "updated_by": "runner-sdk/draft-skill",
      "updated_at": "2026-10-22T11:30:00Z",
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
          },
          "… (+2 more)"
        ]
      },
      "stamps": {
        "text": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "level": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "source": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        }
      },
      "stale": [],
      "review_items": []
    },
    "… (+3 more)"
  ],
  "gaps": [
    {
      "ref": "G-1",
      "type": "gap",
      "title": "Do consumers need per-order ordering?",
      "status": "ANSWERED",
      "pill": "green",
      "line": "Must events for one order arrive in the order they happened?",
      "rev": 2,
      "fields": {
        "question": "Must events for one order arrive in the order they happened?",
        "kind": "unknown",
        "domain": "product",
        "level": "MUST",
        "asked_by": "runner-sdk/draft-skill",
        "why_now": "It decides the partition key in D-2.",
        "context": "Billing replays PAID and CANCELLED to compute revenue. If CANCELLED for order 81723 arrives before PAID, billing counts revenue that was refunded.",
        "options": [
          {
            "key": "per-order",
            "label": "Yes — per order",
            "consequence": "partition by order_id; per-order ordering guaranteed"
          },
          {
            "key": "none",
            "label": "No ordering needed",
            "consequence": "round-robin partitions; consumers sort by timestamp"
          }
        ],
        "recommendation": "per-order",
        "recommendation_why": "Billing is order-sensitive; per-order partitioning costs nothing extra.",
        "blocks": [
          "D-2"
        ],
        "answer": "Yes — per order. Billing double-counts otherwise; analytics does not care.",
        "choice": "per-order",
        "answered_by": "maya",
        "answered_on": "2026-10-23T10:15:00Z"
      },
      "created_by": "runner-sdk/draft-skill",
      "created_at": "2026-10-22T11:30:00Z",
      "updated_by": "maya",
      "updated_at": "2026-10-23T10:15:00Z",
      "links": {
        "out": [
          {
            "kind": "blocks",
            "to": "D-2"
          },
          {
            "kind": "mentions",
            "to": "D-2"
          }
        ],
        "in": [
          {
            "kind": "mentions",
            "from": "D-2"
          }
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "kind": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "domain": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "level": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "asked_by": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "why_now": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "context": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "options": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "recommendation": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "recommendation_why": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "blocks": {
          "by": "runner-sdk/draft-skill",
          "kind": "agent",
          "at": "2026-10-22T11:30:00"
        },
        "answer": {
          "by": "maya",
          "kind": "human",
          "at": "2026-10-23T10:15:00"
        },
        "choice": {
          "by": "maya",
          "kind": "human",
          "at": "2026-10-23T10:15:00"
        },
        "answered_by": {
          "by": "maya",
          "kind": "human",
          "at": "2026-10-23T10:15:00"
        },
        "answered_on": {
          "by": "maya",
          "kind": "human",
          "at": "2026-10-23T10:15:00"
        }
      },
      "stale": [],
      "review_items": []
    },
    {
      "ref": "G-2",
      "type": "gap",
      "title": "Use the platform CDC pipeline instead of an outbox?",
      "status": "ANSWERED",
      "pill": "green",
      "line": "The orders DB already streams its binlog to Kafka via Debezium (platform team). Use CDC instead of the outbox table (D-1)?",
      "rev": 3,
      "fields": {
        "question": "The orders DB already streams its binlog to Kafka via Debezium (platform team). Use CDC instead of the outbox table (D-1)?",
        "kind": "deviation",
        "domain": "engg",
        "level": "MUST",
        "asked_by": "runner-sdk/implement-task",
        "why_now": "Implementing T-1: the outbox needs a migration on a table the orders team does not want to own.",
        "context": "Platform runs Debezium on orders-primary (connector `orders-cdc`, lag p99 1.2s). An outbox adds `order_outbox`, a relay process, and a nightly cleanup job.",
        "options": [
          {
            "key": "cdc",
            "label": "Switch to CDC",
            "consequence": "supersede D-1; add an AC for CDC lag; no new table"
          },
          {
            "key": "outbox",
            "label": "Keep the outbox",
            "consequence": "no spec change; orders team owns the table"
          }
        ],
        "recommendation": "cdc",
        "recommendation_why": "Same delivery guarantee, no new table, the pipeline already exists.",
        "blocks": [
          "D-1",
          "T-1"
        ],
        "proposed_change": "D-1 verdict: outbox → CDC via Debezium on orders-primary. Add AC: given CDC lag > 5s for 5 min, the lag alert fires. T-1 implements the new decision.",
        "answer": "Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.",
        "choice": "cdc",
        "answered_by": "priya",
        "answered_on": "2026-10-25T13:30:00Z",
        "resolution": "D-4 supersedes D-1; AC-5 added for CDC lag; T-1 re-scoped."
      },
      "created_by": "runner-sdk/implement-task",
      "created_at": "2026-10-25T10:05:00Z",
      "updated_by": "runner-sdk/implement-task",
      "updated_at": "2026-10-25T14:10:00Z",
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
          "… (+4 more)"
        ],
        "in": [
          {
            "kind": "because",
            "from": "D-4"
          },
          {
            "kind": "mentions",
            "from": "D-4"
          }
        ]
      },
      "stamps": {
        "question": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "kind": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "domain": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "level": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "asked_by": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "why_now": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "context": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "options": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "recommendation": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "recommendation_why": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "blocks": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "proposed_change": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T10:05:00"
        },
        "answer": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-25T13:30:00"
        },
        "choice": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-25T13:30:00"
        },
        "answered_by": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-25T13:30:00"
        },
        "answered_on": {
          "by": "priya",
          "kind": "human",
          "at": "2026-10-25T13:30:00"
        },
        "resolution": {
          "by": "runner-sdk/implement-task",
          "kind": "agent",
          "at": "2026-10-25T14:10:00"
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
      "note": "Events carry order ids and states only; no PII. Bus topic ACL limited to the consumers listed in the HLD.",
      "refs": ""
    },
    {
      "item": "rollback_plan",
      "phase": "draft",
      "text": "how a bad deploy is undone",
      "derived": false,
      "disposition": "addressed",
      "note": "Feature flag order_events.enabled; consumers keep polling until the flag has been on for 7 days.",
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
        "passed": true,
        "failing": [],
        "detail": "",
        "args": {}
      },
      "… (+5 more)"
    ],
    "note": "",
    "failing_rules": []
  },
  "can_approve": false,
  "approver": "chandra",
  "approval_blockers": [],
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
        "approved_rev": "1",
        "note": "Good scope. Ship behind the flag."
      },
      "created_by": "chandra",
      "created_at": "2026-10-23T15:40:00Z",
      "updated_by": "chandra",
      "updated_at": "2026-10-23T15:40:00Z"
    }
  ],
  "baselines": [
    {
      "ref": "B-1",
      "label": "B-1 — draft rev 1 approved by chandra",
      "status": "CURRENT",
      "approval": "APR-1",
      "approved_by": "chandra",
      "draft_rev": "1",
      "members": [
        "draft",
        "D-1",
        "… (+7 more)"
      ],
      "created_at": "2026-10-23T15:40:00Z"
    }
  ],
  "review_items": []
}
```

## Records

### GET /api/initiatives/order-events/records?type=decision

Filters: `type`, `status`, `q` (free text over ref, title and fields), `since` (ISO).

`GET /api/initiatives/order-events/records?type=decision` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "ref": "D-1",
    "type": "decision",
    "title": "Publish through a transactional outbox",
    "status": "SUPERSEDED",
    "pill": "grey",
    "line": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
    "rev": 1,
    "fields": {
      "question": "How do order state changes reach the event bus without being lost?",
      "domain": "engg",
      "level": "SHOULD",
      "options": [
        {
          "name": "outbox",
          "consequences": "order_outbox row written in the order transaction; a relay publishes it",
          "cost_risk": "one new table, a relay process"
        },
        {
          "name": "dual-write",
          "consequences": "publish after commit from the request handler",
          "cost_risk": "events lost on crash between commit and publish"
        },
        "… (+1 more)"
      ],
      "verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
      "rationale": "Atomic with the state change, no new infrastructure. Dual-write loses events on crash; CDC was not known to be available.",
      "decided_by": "runner-sdk/draft-skill",
      "decided_on": "2026-10-22"
    },
    "created_by": "runner-sdk/draft-skill",
    "created_at": "2026-10-22T11:30:00Z",
    "updated_by": "runner-sdk/draft-skill",
    "updated_at": "2026-10-22T11:30:00Z"
  },
  {
    "ref": "D-2",
    "type": "decision",
    "title": "CloudEvents envelope, partitioned by order_id",
    "status": "DECIDED",
    "pill": "green",
    "line": "CloudEvents 1.0 JSON; partition key order_id",
    "rev": 2,
    "fields": {
      "question": "Which envelope and partition key do order events use?",
      "domain": "engg",
      "level": "SHOULD",
      "options": [
        {
          "name": "cloudevents",
          "consequences": "consumers reuse their CloudEvents parser",
          "cost_risk": "low"
        },
        {
          "name": "custom-json",
          "consequences": "one more schema to maintain",
          "cost_risk": "medium"
        }
      ],
      "verdict": "CloudEvents 1.0 JSON; partition key order_id",
      "rationale": "Billing, notifications and analytics already parse CloudEvents. G-1: billing needs per-order ordering, so order_id is the partition key.",
      "decided_by": "runner-sdk/draft-skill",
      "decided_on": "2026-10-22"
    },
    "created_by": "runner-sdk/draft-skill",
    "created_at": "2026-10-22T11:30:00Z",
    "updated_by": "runner-sdk/draft-skill",
    "updated_at": "2026-10-23T11:00:00Z"
  },
  "… (+2 more)"
]
```

### GET /api/initiatives/order-events/records/G-2

Record detail: links both ways, per-field stamps (`by`, `kind`, `at`), stale narratives, open review items.

`GET /api/initiatives/order-events/records/G-2` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "ref": "G-2",
  "type": "gap",
  "title": "Use the platform CDC pipeline instead of an outbox?",
  "status": "ANSWERED",
  "pill": "green",
  "line": "The orders DB already streams its binlog to Kafka via Debezium (platform team). Use CDC instead of the outbox table (D-1)?",
  "rev": 3,
  "fields": {
    "question": "The orders DB already streams its binlog to Kafka via Debezium (platform team). Use CDC instead of the outbox table (D-1)?",
    "kind": "deviation",
    "domain": "engg",
    "level": "MUST",
    "asked_by": "runner-sdk/implement-task",
    "why_now": "Implementing T-1: the outbox needs a migration on a table the orders team does not want to own.",
    "context": "Platform runs Debezium on orders-primary (connector `orders-cdc`, lag p99 1.2s). An outbox adds `order_outbox`, a relay process, and a nightly cleanup job.",
    "options": [
      {
        "key": "cdc",
        "label": "Switch to CDC",
        "consequence": "supersede D-1; add an AC for CDC lag; no new table"
      },
      {
        "key": "outbox",
        "label": "Keep the outbox",
        "consequence": "no spec change; orders team owns the table"
      }
    ],
    "recommendation": "cdc",
    "recommendation_why": "Same delivery guarantee, no new table, the pipeline already exists.",
    "blocks": [
      "D-1",
      "T-1"
    ],
    "proposed_change": "D-1 verdict: outbox → CDC via Debezium on orders-primary. Add AC: given CDC lag > 5s for 5 min, the lag alert fires. T-1 implements the new decision.",
    "answer": "Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.",
    "choice": "cdc",
    "answered_by": "priya",
    "answered_on": "2026-10-25T13:30:00Z",
    "resolution": "D-4 supersedes D-1; AC-5 added for CDC lag; T-1 re-scoped."
  },
  "created_by": "runner-sdk/implement-task",
  "created_at": "2026-10-25T10:05:00Z",
  "updated_by": "runner-sdk/implement-task",
  "updated_at": "2026-10-25T14:10:00Z",
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
      "… (+4 more)"
    ],
    "in": [
      {
        "kind": "because",
        "from": "D-4"
      },
      {
        "kind": "mentions",
        "from": "D-4"
      }
    ]
  },
  "stamps": {
    "question": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "kind": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "domain": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "level": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "asked_by": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "why_now": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "context": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "options": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "recommendation": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "recommendation_why": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "blocks": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "proposed_change": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T10:05:00"
    },
    "answer": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-25T13:30:00"
    },
    "choice": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-25T13:30:00"
    },
    "answered_by": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-25T13:30:00"
    },
    "answered_on": {
      "by": "priya",
      "kind": "human",
      "at": "2026-10-25T13:30:00"
    },
    "resolution": {
      "by": "runner-sdk/implement-task",
      "kind": "agent",
      "at": "2026-10-25T14:10:00"
    }
  },
  "stale": [],
  "review_items": []
}
```

### GET /api/initiatives/order-events/records/D-1/history

Every revision, newest first: `actor`, `actor_kind`, `because`, `note`, the full `fields` at that rev.

`GET /api/initiatives/order-events/records/D-1/history` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "rev": 1,
    "ref": "D-1",
    "title": "Publish through a transactional outbox",
    "status": "DECIDED",
    "fields": {
      "question": "How do order state changes reach the event bus without being lost?",
      "domain": "engg",
      "level": "SHOULD",
      "options": [
        {
          "name": "outbox",
          "consequences": "order_outbox row written in the order transaction; a relay publishes it",
          "cost_risk": "one new table, a relay process"
        },
        {
          "name": "dual-write",
          "consequences": "publish after commit from the request handler",
          "cost_risk": "events lost on crash between commit and publish"
        },
        "… (+1 more)"
      ],
      "verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
      "rationale": "Atomic with the state change, no new infrastructure. Dual-write loses events on crash; CDC was not known to be available.",
      "decided_by": "runner-sdk/draft-skill",
      "decided_on": "2026-10-22"
    },
    "links": [],
    "actor": "runner-sdk/draft-skill",
    "actor_kind": "agent",
    "batch_id": "1d5bef3a-f880-4f9b-88b9-f624fc067942",
    "note": "",
    "because": [],
    "at": "2026-10-22T11:30:00Z"
  }
]
```

### POST /api/initiatives/payment-webhooks/records

**Write a batch** (agents and the UI's generic editor). Atomic: every op or none. An op is `{ref?, type?, title?, fields, link?, unlink?, note?, base_rev?, because?, reviewed?}` — omit `ref` and give `type` to mint; `#n` = the ref op n minted; `null` deletes a field; never send `status`. Reusing a `batch_id` with the same ops returns the stored result (`replayed: true`).

`POST /api/initiatives/payment-webhooks/records` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

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

### POST /api/initiatives/order-events/records (rejected)

A rejected batch: **422**, nothing saved, each op's errors in `error_data.results[].errors` (ops that were fine say `not saved`). Here: after baseline B-1 an agent may not move the spec without `because` (a human-answered gap, a grounded decision, or a finding).

`POST /api/initiatives/order-events/records` — X-Actor: runner-sdk · X-Actor-Kind: agent → **422**

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
          "D-4"
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
  "instance": "http://testserver/api/initiatives/order-events/records",
  "error_code": "VALIDATION_ERROR",
  "error_data": {
    "ok": false,
    "batch_id": "6acba9fb-f379-4dbf-a4b3-911c48309286",
    "results": [
      {
        "index": 0,
        "ref": "draft",
        "type": "draft",
        "action": "error",
        "rev": null,
        "status": null,
        "errors": [
          "because: spec change after baseline B-1 needs `because` (a gap answer, a decision, a finding) — draft is a member of the baseline; moved: lld: “- `order_outbox(id bigint pk, order_id, type, payload js…"
        ],
        "warnings": []
      },
      {
        "index": 1,
        "ref": "AC-6",
        "type": "acceptance_criterion",
        "action": "error",
        "rev": null,
        "status": null,
        "errors": [
          "because: spec change after baseline B-1 needs `because` (a gap answer, a decision, a finding) — AC-6 is added after the baseline; moved: new acceptance_criterion"
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

### GET /api/inbox/maya

One person's inbox across initiatives, overdue first. `kind`: `gap` (answer it), `decision` (rule it: MUST or escalated), `approval` (`target`: `draft` or a task; tasks carry `drift` and `digest`), `review_item` (`review_item_id`, `what_moved`), `manual_ac` (sign it). `route` says why it landed here (`role`, `domain`, `fallback` = routed to the DRI because nobody holds the role).

`GET /api/inbox/maya` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "person": "maya",
  "count": 2,
  "overdue": 2,
  "counts": {
    "gap": 1,
    "decision": 1
  },
  "items": [
    {
      "key": "gap:refund-events:G-1",
      "kind": "gap",
      "initiative": "refund-events",
      "initiative_title": "Refund events",
      "ref": "G-1",
      "route": {
        "person": "maya",
        "role": "product",
        "domain": "product",
        "fallback": false
      },
      "person": "maya",
      "since": "2026-10-26T11:30:00Z",
      "age_hours": 56.9,
      "sla_hours": 24,
      "due_at": "2026-10-27T11:30:00Z",
      "overdue": true,
      "priority": 10,
      "title": "Partial refunds: one event or one per line?",
      "record": {
        "ref": "G-1",
        "type": "gap",
        "title": "Partial refunds: one event or one per line?",
        "status": "OPEN",
        "pill": "red",
        "line": "When a customer is refunded 2 of 5 items, does finance want one event or one per refunded line?",
        "rev": 1,
        "fields": {
          "question": "When a customer is refunded 2 of 5 items, does finance want one event or one per refunded line?",
          "kind": "unknown",
          "domain": "product",
          "asked_by": "runner-sdk/draft-skill",
          "why_now": "D-2 (a MUST decision) cannot be ruled without it; the schema depends on it.",
          "context": "Order 90311: 5 items, items 2 and 4 refunded (€18.40 + €6.10). Per-refund: one event, lines[2]. Per-line: two events. The provider report lists one row per refund, not per line.",
          "options": [
            {
              "key": "per-refund",
              "label": "One event per refund",
              "consequence": "matches the provider report row for row"
            },
            {
              "key": "per-line",
              "label": "One event per line",
              "consequence": "finance aggregates lines to match the report"
            }
          ],
          "recommendation": "per-refund",
          "recommendation_why": "Reconciliation is against the provider report, which is per refund.",
          "blocks": [
            "D-2"
          ]
        },
        "created_by": "runner-sdk/draft-skill",
        "created_at": "2026-10-26T11:30:00Z",
        "updated_by": "runner-sdk/draft-skill",
        "updated_at": "2026-10-26T11:30:00Z"
      },
      "question": "When a customer is refunded 2 of 5 items, does finance want one event or one per refunded line?",
      "context": "Order 90311: 5 items, items 2 and 4 refunded (€18.40 + €6.10). Per-refund: one event, lines[2]. Per-line: two events. The provider report lists one row per refund, not per line.",
      "options": [
        {
          "key": "per-refund",
          "label": "One event per refund",
          "consequence": "matches the provider report row for row"
        },
        {
          "key": "per-line",
          "label": "One event per line",
          "consequence": "finance aggregates lines to match the report"
        }
      ],
      "recommendation": "per-refund",
      "recommendation_why": "Reconciliation is against the provider report, which is per refund.",
      "blocks": [
        "D-2"
      ],
      "level": "MUST"
    },
    {
      "key": "decision:refund-events:D-2",
      "kind": "decision",
      "initiative": "refund-events",
      "initiative_title": "Refund events",
      "ref": "D-2",
      "route": {
        "person": "maya",
        "role": "product",
        "domain": "product",
        "fallback": false
      },
      "person": "maya",
      "since": "2026-10-26T11:30:00Z",
      "age_hours": 56.9,
      "sla_hours": 24,
      "due_at": "2026-10-27T11:30:00Z",
      "overdue": true,
      "priority": 10,
      "title": "Partial refund granularity",
      "record": {
        "ref": "D-2",
        "type": "decision",
        "title": "Partial refund granularity",
        "status": "OPEN",
        "pill": "red",
        "line": null,
        "rev": 1,
        "fields": {
          "question": "Is a partial refund one event, or one event per refunded line?",
          "domain": "product",
          "level": "MUST",
          "options": [
            {
              "name": "per-refund",
              "consequences": "one event with a lines[] array",
              "cost_risk": "finance sums lines"
            },
            {
              "name": "per-line",
              "consequences": "one event per refunded line",
              "cost_risk": "more events; simpler sums"
            }
          ]
        },
        "created_by": "runner-sdk/draft-skill",
        "created_at": "2026-10-26T11:30:00Z",
        "updated_by": "runner-sdk/draft-skill",
        "updated_at": "2026-10-26T11:30:00Z"
      },
      "question": "Is a partial refund one event, or one event per refunded line?",
      "options": [
        {
          "name": "per-refund",
          "consequences": "one event with a lines[] array",
          "cost_risk": "finance sums lines"
        },
        {
          "name": "per-line",
          "consequences": "one event per refunded line",
          "cost_risk": "more events; simpler sums"
        }
      ],
      "provisional_verdict": null,
      "level": "MUST",
      "blocks": []
    }
  ]
}
```

### GET /api/people

Everyone with an assignment and their inbox size (the inbox switcher).

`GET /api/people` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "person": "chandra",
    "roles": [
      {
        "initiative": "payment-webhooks",
        "role": "dri"
      },
      {
        "initiative": "refund-events",
        "role": "dri"
      },
      "… (+1 more)"
    ],
    "inbox": 1
  },
  {
    "person": "leo",
    "roles": [
      {
        "initiative": "order-events",
        "role": "design"
      }
    ],
    "inbox": 0
  },
  "… (+4 more)"
]
```

### POST /api/initiatives/refund-events/gaps/G-1/answer

**human** — answer a gap: `choice` (an option key) and/or `answer` (text; defaults to the option's label). Returns the write result; `review_items` lists what the answer put up for review and who it went to.

`POST /api/initiatives/refund-events/gaps/G-1/answer` — X-Actor: maya · X-Actor-Kind: human → **200**

Request:

```json
{
  "choice": "per-refund",
  "answer": "One event per refund — finance reconciles against the provider report, which is per refund."
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "78b61318-ee17-4ad3-85d3-7fbd343ca01a",
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
    "D-2 ← G-1: status OPEN → ANSWERED (→ maya)"
  ],
  "stale": [],
  "gates_changed": [],
  "baseline": null,
  "replayed": false
}
```

### POST /api/initiatives/refund-events/decisions/D-2/rule

**human** — rule an OPEN or PROVISIONAL decision (MUST-level or escalated decisions can only be ruled here). A DECIDED decision returns 422: supersede it instead.

`POST /api/initiatives/refund-events/decisions/D-2/rule` — X-Actor: maya · X-Actor-Kind: human → **200**

Request:

```json
{
  "verdict": "One event per refund with a lines[] array",
  "rationale": "G-1: matches the provider report row for row."
}
```

Response:

```json
{
  "ok": true,
  "batch_id": "21f08953-33bf-46f7-987b-3ecd30c83663",
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

### POST /api/initiatives/payment-webhooks/approvals

**human** — approve. `role` dri → `target: "draft"` (creates baseline B-n: see `baseline` in the result); engg → a task ref, with `at_sha` = the PR head (the service pins the drift `digest`); qa → a manual AC. The caller must hold the role on the initiative, and the gate's other rules must pass — else 422 naming them.

`POST /api/initiatives/payment-webhooks/approvals` — X-Actor: chandra · X-Actor-Kind: human → **201**

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
  "batch_id": "820a265d-ccb6-4c54-900e-3c9f97758598",
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

### POST /api/initiatives/payment-webhooks/criteria/AC-2/sign

**human** (qa) — sign a manual AC at a sha.

`POST /api/initiatives/payment-webhooks/criteria/AC-2/sign` — X-Actor: sam · X-Actor-Kind: human → **200**

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
  "batch_id": "d6480ee7-f36d-4d13-9044-d46f0eed898f",
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

### POST /api/initiatives/payment-webhooks/criteria/AC-1/retire

**human** — retire an AC (shows as `ac_retired` drift).

`POST /api/initiatives/payment-webhooks/criteria/AC-1/retire` — X-Actor: chandra · X-Actor-Kind: human → **200**

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
  "batch_id": "28f42c41-bf1c-43ac-aae1-022c626bcc1c",
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

### POST /api/initiatives/payment-webhooks/snapshot

**human** — re-pin the requirement (a material change: the draft goes up for review, and the drift report shows `requirement_repinned`). Returns `{state, write}`.

`POST /api/initiatives/payment-webhooks/snapshot` — X-Actor: chandra · X-Actor-Kind: human → **200**

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
      "slug": "payment-webhooks",
      "title": "Payment webhooks",
      "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
      "created_by": "chandra",
      "created_at": "2026-10-28T20:22:20Z",
      "closed_at": null,
      "snapshot_hash": "252ab9fbe206849ac011ed14e952f95a3025afa063c3b6820d8e5f463bcfd724",
      "phase": "PLAN",
      "pill": "amber",
      "summary": "",
      "spec_snapshot": {
        "requirement": "# Payment webhooks\nMerchants want a webhook when a payment settles **or is refunded**.",
        "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4410",
        "created_by": "chandra",
        "at": "2026-10-28T20:22:20Z",
        "previous_hash": "b1ed29dab1975f335bc0e6d16d4ea871a009e6e13d2622775a6a9c948a1a233b",
        "previous_at": "2026-10-28T20:22:20Z"
      }
    },
    "phase": "PLAN",
    "assignments": [
      {
        "ref": "A-1",
        "person": "chandra",
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
      "label": "B-1 — draft rev 1 approved by chandra",
      "status": "CURRENT",
      "approval": "APR-1",
      "approved_by": "chandra",
      "draft_rev": "1",
      "members": [
        "draft",
        "… (+3 more)"
      ],
      "created_at": "2026-10-28T20:22:20Z"
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
    "batch_id": "aa8a760c-1b2f-4aa6-b13a-8739d7996b34",
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
      "draft ← initiative: snapshot_hash: “b1ed29dab1975f335bc0e6d16d4ea871a009e6e13d2622775a6a9c948a1…” → “252ab9fbe206849ac011ed14e952f95a3025afa063c3b6820d8e5f463bc…” (→ chandra)"
    ],
    "stale": [],
    "gates_changed": [],
    "baseline": null,
    "replayed": false
  }
}
```

## Review queue

### GET /api/initiatives/payment-webhooks/reviews

Open review items (`?status=open` default; `upheld`, `revised`, `dismissed`, `all`). Each: `cause` moved (`what_moved`), so `target` may no longer hold; `route_to` is who should look.

`GET /api/initiatives/payment-webhooks/reviews` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "id": 5,
    "target": "draft",
    "cause": "initiative",
    "cause_rev": 3,
    "what_moved": "snapshot_hash: “b1ed29dab1975f335bc0e6d16d4ea871a009e6e13d2622775a6a9c948a1…” → “252ab9fbe206849ac011ed14e952f95a3025afa063c3b6820d8e5f463bc…”",
    "path": "scope",
    "status": "open",
    "route_to": "chandra",
    "domain": null,
    "note": null,
    "created_by": "chandra",
    "created_at": "2026-10-28T20:22:20Z",
    "resolved_by": null,
    "resolved_at": null
  }
]
```

### POST /api/initiatives/payment-webhooks/reviews/5/resolve

Resolve: `upheld` (still holds — say why) · `revised` · `dismissed`. `note` required.

`POST /api/initiatives/payment-webhooks/reviews/5/resolve` — X-Actor: chandra · X-Actor-Kind: human → **200**

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
  "id": 5,
  "target": "draft",
  "cause": "initiative",
  "cause_rev": 3,
  "what_moved": "snapshot_hash: “b1ed29dab1975f335bc0e6d16d4ea871a009e6e13d2622775a6a9c948a1…” → “252ab9fbe206849ac011ed14e952f95a3025afa063c3b6820d8e5f463bc…”",
  "path": "scope",
  "status": "upheld",
  "route_to": "chandra",
  "domain": null,
  "note": "Refunds are a separate initiative; the draft holds.",
  "created_by": "chandra",
  "created_at": "2026-10-28T20:22:20Z",
  "resolved_by": "chandra",
  "resolved_at": "2026-10-28T20:22:20Z"
}
```

## Drift, gates, tasks (touchpoint 3)

### GET /api/initiatives/order-events/tasks/T-1

**Task page**: the task (detail), its GATE_PR (rule by rule), its task-scoped drift report (full shape below), the approver, test runs, findings, deploys.

`GET /api/initiatives/order-events/tasks/T-1` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "task": {
    "ref": "T-1",
    "type": "task",
    "title": "CDC transformer to order-events",
    "status": "IN_REVIEW",
    "pill": "amber",
    "line": "Map Debezium order row changes to CloudEvents on order-events",
    "rev": 3,
    "fields": {
      "goal": "Map Debezium order row changes to CloudEvents on order-events",
      "repo": "acme/orders-service",
      "template": "python-service-v3",
      "implements": [
        "D-2",
        "D-4"
      ],
      "covers": [
        "AC-1",
        "AC-2",
        "AC-5"
      ],
      "rollback": "Turn off order_events.enabled; the relay stops, the outbox drains on re-enable.",
      "pr_url": "https://github.com/acme/orders-service/pull/482",
      "pr_state": "open",
      "pr_sha": "9f3c2e1a7b4d",
      "ci_attempts": "1",
      "review_rounds": "1",
      "tracker_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4212"
    },
    "created_by": "runner-sdk/plan-skill",
    "created_at": "2026-10-24T09:20:00Z",
    "updated_by": "runner-sdk/implement-task",
    "updated_at": "2026-10-26T16:45:00Z",
    "links": {
      "out": [
        {
          "kind": "covers",
          "to": "AC-1"
        },
        {
          "kind": "covers",
          "to": "AC-2"
        },
        {
          "kind": "covers",
          "to": "AC-5"
        },
        "… (+2 more)"
      ],
      "in": [
        {
          "kind": "approves",
          "from": "APR-2"
        },
        {
          "kind": "blocks",
          "from": "G-2"
        },
        {
          "kind": "deploys",
          "from": "DEP-1"
        },
        "… (+2 more)"
      ]
    },
    "stamps": {
      "goal": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-25T14:10:00"
      },
      "repo": {
        "by": "runner-sdk/plan-skill",
        "kind": "agent",
        "at": "2026-10-24T09:20:00"
      },
      "template": {
        "by": "runner-sdk/plan-skill",
        "kind": "agent",
        "at": "2026-10-24T09:20:00"
      },
      "implements": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-25T14:10:00"
      },
      "covers": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-25T14:10:00"
      },
      "rollback": {
        "by": "runner-sdk/plan-skill",
        "kind": "agent",
        "at": "2026-10-24T09:20:00"
      },
      "pr_url": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-26T16:45:00"
      },
      "pr_state": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-26T16:45:00"
      },
      "pr_sha": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-26T16:45:00"
      },
      "ci_attempts": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-26T16:45:00"
      },
      "review_rounds": {
        "by": "runner-sdk/implement-task",
        "kind": "agent",
        "at": "2026-10-26T16:45:00"
      },
      "tracker_url": {
        "by": "runner-sdk/plan-skill",
        "kind": "agent",
        "at": "2026-10-24T09:20:00"
      }
    },
    "stale": [],
    "review_items": []
  },
  "gate": {
    "gate": "GATE_PR",
    "scope": "task",
    "target": "T-1",
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
    "status": "EXPLAINED",
    "initiative": "order-events",
    "task": "T-1",
    "baseline": {
      "ref": "B-1",
      "label": "B-1 — draft rev 1 approved by chandra",
      "status": "CURRENT",
      "approval": "APR-1",
      "approved_by": "chandra",
      "draft_rev": "1",
      "created_at": "2026-10-23T15:40:00Z",
      "members": 9
    },
    "until": null,
    "scope_refs": [
      "AC-1",
      "AC-2",
      "AC-3",
      "… (+6 more)"
    ],
    "summary": {
      "changes": 3,
      "explained": 3,
      "unexplained": 0,
      "pending_gaps": 0,
      "pending_decisions": 0,
      "other_changes": 0
    },
    "digest": "6979e7a1e17d3c5ac7dd744956d5a7defc0ee90cb68292bdbbcee3b4930c835f",
    "entries": [
      {
        "id": "gap_answered:G-2@2",
        "kind": "gap_answered",
        "ref": "G-2",
        "type": "gap",
        "rev": 2,
        "at": "2026-10-25T13:30:00Z",
        "actor": "priya",
        "actor_kind": "human",
        "summary": "G-2 answered by priya: “Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.”",
        "what_moved": [],
        "because": [],
        "explained": true,
        "explanation": [
          {
            "ref": null,
            "ok": true,
            "why": "a human answer (priya)"
          }
        ],
        "related": [
          "D-1",
          "T-1"
        ],
        "detail": {
          "question": "The orders DB already streams its binlog to Kafka via Debezium (platform team). Use CDC instead of the outbox table (D-1)?",
          "answer": "Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.",
          "choice": "cdc",
          "answered_by": "priya",
          "blocks": [
            "D-1",
            "T-1"
          ],
          "resolution": "D-4 supersedes D-1; AC-5 added for CDC lag; T-1 re-scoped.",
          "kind": "deviation",
          "proposed_change": "D-1 verdict: outbox → CDC via Debezium on orders-primary. Add AC: given CDC lag > 5s for 5 min, the lag alert fires. T-1 implements the new decision."
        },
        "in_scope": true
      },
      {
        "id": "decision_superseded:D-4@1",
        "kind": "decision_superseded",
        "ref": "D-4",
        "type": "decision",
        "rev": 1,
        "at": "2026-10-25T14:10:00Z",
        "actor": "runner-sdk/implement-task",
        "actor_kind": "agent",
        "summary": "D-4 supersedes D-1: verdict “Transactional outbox: order_outbox row written in the order transaction, published by a r…” → “CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents”",
        "what_moved": [
          "verdict: “Transactional outbox: order_outbox row written in the order transaction, published by a relay” → “CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents”"
        ],
        "because": [
          "G-2"
        ],
        "explained": true,
        "explanation": [
          {
            "ref": "G-2",
            "ok": true,
            "why": "answered by priya: “Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.”"
          }
        ],
        "related": [
          "D-1",
          "G-2"
        ],
        "detail": {
          "superseded": "D-1",
          "old_verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
          "new_verdict": "CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents",
          "question": "How do order state changes reach the event bus without being lost?",
          "level": "SHOULD",
          "rationale": "G-2: platform already runs Debezium with 1.2s p99 lag; no new table or relay to own.",
          "related_gaps": [
            "G-2"
          ]
        },
        "in_scope": true
      },
      {
        "id": "ac_added:AC-5@1",
        "kind": "ac_added",
        "ref": "AC-5",
        "type": "acceptance_criterion",
        "rev": 1,
        "at": "2026-10-25T14:10:00Z",
        "actor": "runner-sdk/implement-task",
        "actor_kind": "agent",
        "summary": "AC-5 added: “Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call” (level: integration)",
        "what_moved": [],
        "because": [
          "D-4"
        ],
        "explained": true,
        "explanation": [
          {
            "ref": "D-4",
            "ok": true,
            "why": "“CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents” because G-2 answered by priya: “Switch to CDC — the outbox adds a table we don't own, and platform guarantees the conne…"
          }
        ],
        "related": [
          "D-4"
        ],
        "detail": {
          "text": "Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call",
          "level": "integration",
          "source": [
            "D-4"
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
            "new": "D-4",
            "old_verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
            "new_verdict": "CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents"
          }
        ],
        "changed": [],
        "unchanged": 1
      },
      "criteria": {
        "added": [
          {
            "ref": "AC-5",
            "text": "Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call",
            "level": "integration",
            "because": [
              "D-4"
            ]
          }
        ],
        "retired": [],
        "changed": [],
        "unchanged": 3
      }
    },
    "approved_spec": {
      "draft": {
        "problem": "Consumers poll `orders` every 30s (~400 QPS on the primary, up to 30s notification latency). Done = every state change is on the bus within 5s, none lost, replayable for 7 days.",
        "hld": "Order writes insert an `order_outbox` row in the same transaction (D-1). A relay publishes outbox rows as CloudEvents partitioned by `order_id` (D-2) to `order-events`, retained 7 days (D-3).\n\n```merm…",
        "lld": "- `order_outbox(id bigint pk, order_id, type, payload json, created_at, published_at null)`\n- Relay: `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`, publish, set `p…",
        "scope_in": [
          "All six order state transitions",
          "Relay with lag metrics and alert",
          "Consumer contract docs"
        ],
        "scope_out": [
          "Backfill of historical orders",
          "Migrating consumers off polling (each team owns theirs)"
        ],
        "test_strategy": "Integration tests against MySQL + a local Kafka for AC-1..AC-3 (kill the relay mid-batch for AC-2). AC-4 runs in staging against the real topic retention. No manual ACs."
      },
      "decisions": [
        {
          "ref": "D-1",
          "title": "Publish through a transactional outbox",
          "question": "How do order state changes reach the event bus without being lost?",
          "verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
          "level": "SHOULD",
          "status": "DECIDED"
        },
        {
          "ref": "D-2",
          "title": "CloudEvents envelope, partitioned by order_id",
          "question": "Which envelope and partition key do order events use?",
          "verdict": "CloudEvents 1.0 JSON; partition key order_id",
          "level": "SHOULD",
          "status": "DECIDED"
        }
      ],
      "criteria": [
        {
          "ref": "AC-1",
          "text": "Given an order state change, when the order transaction commits, then exactly one event for it is published",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        {
          "ref": "AC-2",
          "text": "Given the relay is down for 10 minutes, when it restarts, then every pending event is published with no loss",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        {
          "ref": "AC-3",
          "text": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        }
      ]
    },
    "current_spec": {
      "draft": {
        "problem": "Consumers poll `orders` every 30s (~400 QPS on the primary, up to 30s notification latency). Done = every state change is on the bus within 5s, none lost, replayable for 7 days.",
        "hld": "Order writes insert an `order_outbox` row in the same transaction (D-1). A relay publishes outbox rows as CloudEvents partitioned by `order_id` (D-2) to `order-events`, retained 7 days (D-3).\n\n```merm…",
        "lld": "- `order_outbox(id bigint pk, order_id, type, payload json, created_at, published_at null)`\n- Relay: `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`, publish, set `p…",
        "scope_in": [
          "All six order state transitions",
          "Relay with lag metrics and alert",
          "Consumer contract docs"
        ],
        "scope_out": [
          "Backfill of historical orders",
          "Migrating consumers off polling (each team owns theirs)"
        ],
        "test_strategy": "Integration tests against MySQL + a local Kafka for AC-1..AC-3 (kill the relay mid-batch for AC-2). AC-4 runs in staging against the real topic retention. No manual ACs."
      },
      "decisions": [
        {
          "ref": "D-2",
          "title": "CloudEvents envelope, partitioned by order_id",
          "question": "Which envelope and partition key do order events use?",
          "verdict": "CloudEvents 1.0 JSON; partition key order_id",
          "level": "SHOULD",
          "status": "DECIDED"
        },
        {
          "ref": "D-4",
          "title": "Publish order events via platform CDC",
          "question": "How do order state changes reach the event bus without being lost?",
          "verdict": "CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents",
          "level": "SHOULD",
          "status": "DECIDED"
        }
      ],
      "criteria": [
        {
          "ref": "AC-1",
          "text": "Given an order state change, when the order transaction commits, then exactly one event for it is published",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        {
          "ref": "AC-2",
          "text": "Given the relay is down for 10 minutes, when it restarts, then every pending event is published with no loss",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        {
          "ref": "AC-3",
          "text": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order",
          "level": "integration",
          "manual": "",
          "status": "APPROVED"
        },
        "… (+1 more)"
      ]
    },
    "approvals": [
      {
        "ref": "APR-2",
        "by": "priya",
        "status": "CURRENT",
        "at_sha": "9f3c2e1a7b4d",
        "drift_digest": "6979e7a1e17d3c5ac7dd744956d5a7defc0ee90cb68292bdbbcee3b4930c835f",
        "matches_digest": true,
        "note": "Drift is the CDC switch I asked for; tests cover the lag alert.",
        "at": "2026-10-27T10:30:00Z"
      }
    ]
  },
  "approver": "priya",
  "test_runs": [
    {
      "ref": "R-1",
      "type": "test_run",
      "title": "orders-service integration suite @ 9f3c2e1",
      "status": "GREEN",
      "pill": "green",
      "line": "CDC transformer integration suite (MySQL + Kafka + Debezium in docker)",
      "rev": 1,
      "fields": {
        "summary": "CDC transformer integration suite (MySQL + Kafka + Debezium in docker)",
        "level": "integration",
        "result": "GREEN",
        "at_sha": "9f3c2e1a7b4d",
        "run_url": "https://github.com/acme/orders-service/actions/runs/1180042",
        "environment": "ci",
        "task": [
          "T-1"
        ],
        "covers": [
          {
            "ac": "AC-1",
            "result": "GREEN",
            "test_id": "test_one_event_per_commit",
            "evidence": "48/48 transitions"
          },
          {
            "ac": "AC-2",
            "result": "GREEN",
            "test_id": "test_connector_restart_no_loss",
            "evidence": "0 lost of 10k"
          },
          {
            "ac": "AC-5",
            "result": "GREEN",
            "test_id": "test_lag_alert_fires",
            "evidence": "alert at 5m02s"
          }
        ],
        "run_on": "2026-10-27T13:00"
      },
      "created_by": "runner-sdk/write-tests",
      "created_at": "2026-10-26T16:45:00Z",
      "updated_by": "runner-sdk/write-tests",
      "updated_at": "2026-10-26T16:45:00Z"
    }
  ],
  "findings": [],
  "deploys": [
    {
      "ref": "DEP-1",
      "type": "deploy",
      "title": "staging T-1 @ 9f3c2e1a7b",
      "status": "PENDING",
      "pill": "amber",
      "line": "staging",
      "rev": 1,
      "fields": {
        "environment": "staging",
        "at_sha": "9f3c2e1a7b4d",
        "task": [
          "T-1"
        ],
        "guard_result": "GO",
        "result": "PENDING"
      },
      "created_by": "github-actions",
      "created_at": "2026-10-27T11:00:00Z",
      "updated_by": "github-actions",
      "updated_at": "2026-10-27T11:00:00Z"
    }
  ]
}
```

### GET /api/initiatives/order-events/drift?task=T-1

The task-scoped drift report. Without `task`: the whole initiative. `baseline=B-n`: from an older baseline up to the next one.

`GET /api/initiatives/order-events/drift?task=T-1` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "EXPLAINED",
  "initiative": "order-events",
  "task": "T-1",
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 1 approved by chandra",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "chandra",
    "draft_rev": "1",
    "created_at": "2026-10-23T15:40:00Z",
    "members": 9
  },
  "until": null,
  "scope_refs": [
    "AC-1",
    "AC-2",
    "AC-3",
    "… (+6 more)"
  ],
  "summary": {
    "changes": 3,
    "explained": 3,
    "unexplained": 0,
    "pending_gaps": 0,
    "pending_decisions": 0,
    "other_changes": 0
  },
  "digest": "6979e7a1e17d3c5ac7dd744956d5a7defc0ee90cb68292bdbbcee3b4930c835f",
  "entries": [
    {
      "id": "gap_answered:G-2@2",
      "kind": "gap_answered",
      "ref": "G-2",
      "type": "gap",
      "rev": 2,
      "at": "2026-10-25T13:30:00Z",
      "actor": "priya",
      "actor_kind": "human",
      "summary": "G-2 answered by priya: “Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.”",
      "what_moved": [],
      "because": [],
      "explained": true,
      "explanation": [
        {
          "ref": null,
          "ok": true,
          "why": "a human answer (priya)"
        }
      ],
      "related": [
        "D-1",
        "T-1"
      ],
      "detail": {
        "question": "The orders DB already streams its binlog to Kafka via Debezium (platform team). Use CDC instead of the outbox table (D-1)?",
        "answer": "Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.",
        "choice": "cdc",
        "answered_by": "priya",
        "blocks": [
          "D-1",
          "T-1"
        ],
        "resolution": "D-4 supersedes D-1; AC-5 added for CDC lag; T-1 re-scoped.",
        "kind": "deviation",
        "proposed_change": "D-1 verdict: outbox → CDC via Debezium on orders-primary. Add AC: given CDC lag > 5s for 5 min, the lag alert fires. T-1 implements the new decision."
      },
      "in_scope": true
    },
    {
      "id": "decision_superseded:D-4@1",
      "kind": "decision_superseded",
      "ref": "D-4",
      "type": "decision",
      "rev": 1,
      "at": "2026-10-25T14:10:00Z",
      "actor": "runner-sdk/implement-task",
      "actor_kind": "agent",
      "summary": "D-4 supersedes D-1: verdict “Transactional outbox: order_outbox row written in the order transaction, published by a r…” → “CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents”",
      "what_moved": [
        "verdict: “Transactional outbox: order_outbox row written in the order transaction, published by a relay” → “CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents”"
      ],
      "because": [
        "G-2"
      ],
      "explained": true,
      "explanation": [
        {
          "ref": "G-2",
          "ok": true,
          "why": "answered by priya: “Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.”"
        }
      ],
      "related": [
        "D-1",
        "G-2"
      ],
      "detail": {
        "superseded": "D-1",
        "old_verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
        "new_verdict": "CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents",
        "question": "How do order state changes reach the event bus without being lost?",
        "level": "SHOULD",
        "rationale": "G-2: platform already runs Debezium with 1.2s p99 lag; no new table or relay to own.",
        "related_gaps": [
          "G-2"
        ]
      },
      "in_scope": true
    },
    {
      "id": "ac_added:AC-5@1",
      "kind": "ac_added",
      "ref": "AC-5",
      "type": "acceptance_criterion",
      "rev": 1,
      "at": "2026-10-25T14:10:00Z",
      "actor": "runner-sdk/implement-task",
      "actor_kind": "agent",
      "summary": "AC-5 added: “Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call” (level: integration)",
      "what_moved": [],
      "because": [
        "D-4"
      ],
      "explained": true,
      "explanation": [
        {
          "ref": "D-4",
          "ok": true,
          "why": "“CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents” because G-2 answered by priya: “Switch to CDC — the outbox adds a table we don't own, and platform guarantees the conne…"
        }
      ],
      "related": [
        "D-4"
      ],
      "detail": {
        "text": "Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call",
        "level": "integration",
        "source": [
          "D-4"
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
          "new": "D-4",
          "old_verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
          "new_verdict": "CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents"
        }
      ],
      "changed": [],
      "unchanged": 1
    },
    "criteria": {
      "added": [
        {
          "ref": "AC-5",
          "text": "Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call",
          "level": "integration",
          "because": [
            "D-4"
          ]
        }
      ],
      "retired": [],
      "changed": [],
      "unchanged": 3
    }
  },
  "approved_spec": {
    "draft": {
      "problem": "Consumers poll `orders` every 30s (~400 QPS on the primary, up to 30s notification latency). Done = every state change is on the bus within 5s, none lost, replayable for 7 days.",
      "hld": "Order writes insert an `order_outbox` row in the same transaction (D-1). A relay publishes outbox rows as CloudEvents partitioned by `order_id` (D-2) to `order-events`, retained 7 days (D-3).\n\n```merm…",
      "lld": "- `order_outbox(id bigint pk, order_id, type, payload json, created_at, published_at null)`\n- Relay: `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`, publish, set `p…",
      "scope_in": [
        "All six order state transitions",
        "Relay with lag metrics and alert",
        "Consumer contract docs"
      ],
      "scope_out": [
        "Backfill of historical orders",
        "Migrating consumers off polling (each team owns theirs)"
      ],
      "test_strategy": "Integration tests against MySQL + a local Kafka for AC-1..AC-3 (kill the relay mid-batch for AC-2). AC-4 runs in staging against the real topic retention. No manual ACs."
    },
    "decisions": [
      {
        "ref": "D-1",
        "title": "Publish through a transactional outbox",
        "question": "How do order state changes reach the event bus without being lost?",
        "verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
        "level": "SHOULD",
        "status": "DECIDED"
      },
      {
        "ref": "D-2",
        "title": "CloudEvents envelope, partitioned by order_id",
        "question": "Which envelope and partition key do order events use?",
        "verdict": "CloudEvents 1.0 JSON; partition key order_id",
        "level": "SHOULD",
        "status": "DECIDED"
      }
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given an order state change, when the order transaction commits, then exactly one event for it is published",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-2",
        "text": "Given the relay is down for 10 minutes, when it restarts, then every pending event is published with no loss",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-3",
        "text": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      }
    ]
  },
  "current_spec": {
    "draft": {
      "problem": "Consumers poll `orders` every 30s (~400 QPS on the primary, up to 30s notification latency). Done = every state change is on the bus within 5s, none lost, replayable for 7 days.",
      "hld": "Order writes insert an `order_outbox` row in the same transaction (D-1). A relay publishes outbox rows as CloudEvents partitioned by `order_id` (D-2) to `order-events`, retained 7 days (D-3).\n\n```merm…",
      "lld": "- `order_outbox(id bigint pk, order_id, type, payload json, created_at, published_at null)`\n- Relay: `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`, publish, set `p…",
      "scope_in": [
        "All six order state transitions",
        "Relay with lag metrics and alert",
        "Consumer contract docs"
      ],
      "scope_out": [
        "Backfill of historical orders",
        "Migrating consumers off polling (each team owns theirs)"
      ],
      "test_strategy": "Integration tests against MySQL + a local Kafka for AC-1..AC-3 (kill the relay mid-batch for AC-2). AC-4 runs in staging against the real topic retention. No manual ACs."
    },
    "decisions": [
      {
        "ref": "D-2",
        "title": "CloudEvents envelope, partitioned by order_id",
        "question": "Which envelope and partition key do order events use?",
        "verdict": "CloudEvents 1.0 JSON; partition key order_id",
        "level": "SHOULD",
        "status": "DECIDED"
      },
      {
        "ref": "D-4",
        "title": "Publish order events via platform CDC",
        "question": "How do order state changes reach the event bus without being lost?",
        "verdict": "CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents",
        "level": "SHOULD",
        "status": "DECIDED"
      }
    ],
    "criteria": [
      {
        "ref": "AC-1",
        "text": "Given an order state change, when the order transaction commits, then exactly one event for it is published",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-2",
        "text": "Given the relay is down for 10 minutes, when it restarts, then every pending event is published with no loss",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      {
        "ref": "AC-3",
        "text": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      "… (+1 more)"
    ]
  },
  "approvals": [
    {
      "ref": "APR-2",
      "by": "priya",
      "status": "CURRENT",
      "at_sha": "9f3c2e1a7b4d",
      "drift_digest": "6979e7a1e17d3c5ac7dd744956d5a7defc0ee90cb68292bdbbcee3b4930c835f",
      "matches_digest": true,
      "note": "Drift is the CDC switch I asked for; tests cover the lag alert.",
      "at": "2026-10-27T10:30:00Z"
    }
  ]
}
```

### GET /api/initiatives/order-events/drift?task=T-1&format=md

The same report as the PR's sticky comment.

`GET /api/initiatives/order-events/drift?task=T-1&format=md` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response (`text/markdown; charset=utf-8`):

````markdown
## Drift since baseline B-1 (approved by chandra, 2026-10-23, draft rev 1) — scope: T-1
**3 changes · 3 explained · 0 unexplained** · digest `6979e7a1…`

| when | who | change | because | |
|---|---|---|---|---|
| 10-25 13:30 | priya (human) | G-2 answered by priya: “Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag.” | — | ✓ |
| 10-25 14:10 | runner-sdk/implement-task | D-4 supersedes D-1: verdict “Transactional outbox: order_outbox row written in the order transaction, published by a r…” → “CDC: Debezium on orders-primary; a transformer maps row… | G-2 | ✓ |
| 10-25 14:10 | runner-sdk/implement-task | AC-5 added: “Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call” (level: integration) | D-4 | ✓ |

### Spec diff · decisions: 1 superseded · criteria: +1
- D-1 → D-4: “Transactional outbox: order_outbox row written in the order transaction, published by a relay” → “CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents”
- AC-5 added (integration): Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call
````

### GET /api/initiatives/order-events/drift?task=T-2 (CLEAN)

A task with nothing changed in its scope: `status: CLEAN`, `other_changes` counts the initiative's changes outside it.

`GET /api/initiatives/order-events/drift?task=T-2` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "CLEAN",
  "initiative": "order-events",
  "task": "T-2",
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 1 approved by chandra",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "chandra",
    "draft_rev": "1",
    "created_at": "2026-10-23T15:40:00Z",
    "members": 9
  },
  "until": null,
  "scope_refs": [
    "AC-3",
    "… (+5 more)"
  ],
  "summary": {
    "changes": 0,
    "explained": 0,
    "unexplained": 0,
    "pending_gaps": 0,
    "pending_decisions": 0,
    "other_changes": 3
  },
  "digest": "38361c9a266a8cdd82bba0413719d6f70347bb70f5d017e89fc3ddbe77d75401",
  "entries": [],
  "unexplained": [],
  "pending_gaps": [],
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
      "unchanged": 2
    }
  },
  "approved_spec": {
    "draft": {
      "problem": "Consumers poll `orders` every 30s (~400 QPS on the primary, up to 30s notification latency). Done = every state change is on the bus within 5s, none lost, replayable for 7 days.",
      "hld": "Order writes insert an `order_outbox` row in the same transaction (D-1). A relay publishes outbox rows as CloudEvents partitioned by `order_id` (D-2) to `order-events`, retained 7 days (D-3).\n\n```merm…",
      "lld": "- `order_outbox(id bigint pk, order_id, type, payload json, created_at, published_at null)`\n- Relay: `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`, publish, set `p…",
      "scope_in": [
        "All six order state transitions",
        "… (+2 more)"
      ],
      "scope_out": [
        "Backfill of historical orders",
        "… (+1 more)"
      ],
      "test_strategy": "Integration tests against MySQL + a local Kafka for AC-1..AC-3 (kill the relay mid-batch for AC-2). AC-4 runs in staging against the real topic retention. No manual ACs."
    },
    "decisions": [
      {
        "ref": "D-2",
        "title": "CloudEvents envelope, partitioned by order_id",
        "question": "Which envelope and partition key do order events use?",
        "verdict": "CloudEvents 1.0 JSON; partition key order_id",
        "level": "SHOULD",
        "status": "DECIDED"
      },
      "… (+1 more)"
    ],
    "criteria": [
      {
        "ref": "AC-3",
        "text": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      "… (+1 more)"
    ]
  },
  "current_spec": {
    "draft": {
      "problem": "Consumers poll `orders` every 30s (~400 QPS on the primary, up to 30s notification latency). Done = every state change is on the bus within 5s, none lost, replayable for 7 days.",
      "hld": "Order writes insert an `order_outbox` row in the same transaction (D-1). A relay publishes outbox rows as CloudEvents partitioned by `order_id` (D-2) to `order-events`, retained 7 days (D-3).\n\n```merm…",
      "lld": "- `order_outbox(id bigint pk, order_id, type, payload json, created_at, published_at null)`\n- Relay: `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`, publish, set `p…",
      "scope_in": [
        "All six order state transitions",
        "… (+2 more)"
      ],
      "scope_out": [
        "Backfill of historical orders",
        "… (+1 more)"
      ],
      "test_strategy": "Integration tests against MySQL + a local Kafka for AC-1..AC-3 (kill the relay mid-batch for AC-2). AC-4 runs in staging against the real topic retention. No manual ACs."
    },
    "decisions": [
      {
        "ref": "D-2",
        "title": "CloudEvents envelope, partitioned by order_id",
        "question": "Which envelope and partition key do order events use?",
        "verdict": "CloudEvents 1.0 JSON; partition key order_id",
        "level": "SHOULD",
        "status": "DECIDED"
      },
      "… (+1 more)"
    ],
    "criteria": [
      {
        "ref": "AC-3",
        "text": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order",
        "level": "integration",
        "manual": "",
        "status": "APPROVED"
      },
      "… (+1 more)"
    ]
  },
  "approvals": []
}
```

### GET /api/initiatives/payment-webhooks/drift (initiative scope)

Initiative scope after an AC retirement and a requirement re-pin by humans.

`GET /api/initiatives/payment-webhooks/drift` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "status": "EXPLAINED",
  "initiative": "payment-webhooks",
  "task": null,
  "baseline": {
    "ref": "B-1",
    "label": "B-1 — draft rev 1 approved by chandra",
    "status": "CURRENT",
    "approval": "APR-1",
    "approved_by": "chandra",
    "draft_rev": "1",
    "created_at": "2026-10-28T20:22:20Z",
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
  "digest": "ad92e12cebd1578bbe3060cb43699839363132afbcc570d9afdb3f429f287fcd",
  "entries": [
    {
      "id": "requirement_repinned:initiative@3",
      "kind": "requirement_repinned",
      "ref": "initiative",
      "type": "initiative",
      "rev": 3,
      "at": "2026-10-28T20:22:20Z",
      "actor": "chandra",
      "actor_kind": "human",
      "summary": "requirement re-pinned by chandra (hash 252ab9fb)",
      "what_moved": [
        "snapshot_hash"
      ],
      "because": [],
      "explained": true,
      "explanation": [
        {
          "ref": null,
          "ok": true,
          "why": "made by a human (chandra)"
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
      "at": "2026-10-28T20:22:20Z",
      "actor": "chandra",
      "actor_kind": "human",
      "summary": "AC-1 retired: Signature checks move to the shared webhook library.",
      "what_moved": [],
      "because": [],
      "explained": true,
      "explanation": [
        {
          "ref": null,
          "ok": true,
          "why": "made by a human (chandra)"
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

### GET /api/initiatives/order-events/gates

Every gate: initiative gates once, task gates per task. Each: `{gate, scope, target, status, human_role, text, rules[{name, passed, failing, detail, args}], note, failing_rules}`.

`GET /api/initiatives/order-events/gates` — X-Actor: chandra · X-Actor-Kind: human → **200**

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
        "passed": true,
        "failing": [],
        "detail": "",
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
    "note": "",
    "failing_rules": []
  },
  {
    "gate": "GATE_PR",
    "scope": "task",
    "target": "T-1",
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
        "detail": "pr_state is draft; needs open | approved",
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
          "AC-3",
          "AC-4"
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
  "… (+1 more)"
]
```

### GET /api/initiatives/order-events/tasks/T-2/gates

`GET /api/initiatives/order-events/tasks/T-2/gates` — X-Actor: chandra · X-Actor-Kind: human → **200**

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
        "detail": "pr_state is draft; needs open | approved",
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

### GET /api/deploy-guard?initiative=order-events&task=T-1&sha=9f3c2e1a7b4d&environment=staging

CI/CD asks before a deploy: `decision` GO | NO-GO, `reasons`, each check.

`GET /api/deploy-guard?initiative=order-events&task=T-1&sha=9f3c2e1a7b4d&environment=staging` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "decision": "GO",
  "initiative": "order-events",
  "task": "T-1",
  "sha": "9f3c2e1a7b4d",
  "environment": "staging",
  "reasons": [],
  "checks": [
    {
      "name": "GATE_PR",
      "passed": true,
      "detail": "passed"
    },
    {
      "name": "sha_matches_pr",
      "passed": true,
      "detail": "PR head 9f3c2e1a7b4d, deploying 9f3c2e1a7b4d"
    },
    "… (+3 more)"
  ],
  "drift": {
    "changes": 3,
    "explained": 3,
    "unexplained": 0,
    "pending_gaps": 0,
    "pending_decisions": 0,
    "other_changes": 0,
    "digest": "6979e7a1e17d3c5ac7dd744956d5a7defc0ee90cb68292bdbbcee3b4930c835f",
    "status": "EXPLAINED"
  }
}
```

### POST /api/deploy-guard

Same check, recorded as a `deploy` row (`deploy` in the response).

`POST /api/deploy-guard` — X-Actor: github-actions · X-Actor-Kind: system → **200**

Request:

```json
{
  "initiative": "order-events",
  "task": "T-1",
  "sha": "0000000",
  "environment": "production"
}
```

Response:

```json
{
  "decision": "NO-GO",
  "initiative": "order-events",
  "task": "T-1",
  "sha": "0000000",
  "environment": "production",
  "reasons": [
    "sha_matches_pr: PR head 9f3c2e1a7b4d, deploying 0000000",
    "approved_at_sha: engg approved at 9f3c2e1a7b4d"
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
      "detail": "PR head 9f3c2e1a7b4d, deploying 0000000"
    },
    "… (+3 more)"
  ],
  "drift": {
    "changes": 3,
    "explained": 3,
    "unexplained": 0,
    "pending_gaps": 0,
    "pending_decisions": 0,
    "other_changes": 0,
    "digest": "6979e7a1e17d3c5ac7dd744956d5a7defc0ee90cb68292bdbbcee3b4930c835f",
    "status": "EXPLAINED"
  },
  "deploy": "DEP-2"
}
```

## Worklist, next work, leases

### GET /api/initiatives/refund-events/worklist

Every open item of an initiative, both lanes (`agent` / `human`), grouped by kind, with leases.

`GET /api/initiatives/refund-events/worklist` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "initiative": "refund-events",
  "count": 1,
  "groups": {
    "draft": [
      {
        "key": "draft:refund-events",
        "kind": "draft",
        "lane": "agent",
        "initiative": "refund-events",
        "ref": null,
        "title": "Draft is DRAFTING",
        "why": "catalog_addressed (security_review, rollback_plan, observability, data_migration_assessed, test_strategy); every_decision_covered_by_an_ac (D-2)",
        "person": null,
        "priority": 30,
        "lease": null
      }
    ]
  },
  "items": [
    {
      "key": "draft:refund-events",
      "kind": "draft",
      "lane": "agent",
      "initiative": "refund-events",
      "ref": null,
      "title": "Draft is DRAFTING",
      "why": "catalog_addressed (security_review, rollback_plan, observability, data_migration_assessed, test_strategy); every_decision_covered_by_an_ac (D-2)",
      "person": null,
      "priority": 30,
      "lease": null
    }
  ]
}
```

### GET /api/initiatives/order-events/next-work

What the caller may take now (not leased by someone else), priority order, each with a `context` bundle. `?kind=` and `?person=` filter; `GET /api/next-work` spans all initiatives.

`GET /api/initiatives/order-events/next-work` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Response:

```json
{
  "count": 1,
  "items": [
    {
      "key": "tests:order-events:T-2",
      "kind": "tests",
      "lane": "agent",
      "initiative": "order-events",
      "ref": "T-2",
      "title": "Tests for T-2",
      "why": "no test run row for AC-3, AC-4",
      "person": null,
      "priority": 50,
      "lease": null,
      "context": {
        "record": {
          "ref": "T-2",
          "type": "task",
          "title": "Envelope, partitioning and retention",
          "status": "IN_PROGRESS",
          "pill": "amber",
          "line": "CloudEvents envelope with order_id partition key; 7-day topic retention",
          "rev": 2,
          "fields": {
            "goal": "CloudEvents envelope with order_id partition key; 7-day topic retention",
            "repo": "acme/event-contracts",
            "template": "contracts-lib",
            "implements": [
              "D-2",
              "… (+1 more)"
            ],
            "covers": [
              "AC-3",
              "… (+1 more)"
            ],
            "rollback": "Revert the contract version; the topic config is idempotent.",
            "pr_url": "https://github.com/acme/event-contracts/pull/91",
            "pr_state": "draft",
            "pr_sha": "c41d09e2"
          },
          "created_by": "runner-sdk/plan-skill",
          "created_at": "2026-10-24T09:20:00Z",
          "updated_by": "runner-sdk/implement-task",
          "updated_at": "2026-10-27T15:00:00Z",
          "links": {
            "out": [
              {
                "kind": "covers",
                "to": "AC-3"
              },
              "… (+3 more)"
            ],
            "in": []
          },
          "stamps": {
            "goal": {
              "by": "runner-sdk/plan-skill",
              "kind": "agent",
              "at": "2026-10-24T09:20:00"
            },
            "repo": {
              "by": "runner-sdk/plan-skill",
              "kind": "agent",
              "at": "2026-10-24T09:20:00"
            },
            "template": {
              "by": "runner-sdk/plan-skill",
              "kind": "agent",
              "at": "2026-10-24T09:20:00"
            },
            "implements": {
              "by": "runner-sdk/plan-skill",
              "kind": "agent",
              "at": "2026-10-24T09:20:00"
            },
            "covers": {
              "by": "runner-sdk/plan-skill",
              "kind": "agent",
              "at": "2026-10-24T09:20:00"
            },
            "rollback": {
              "by": "runner-sdk/plan-skill",
              "kind": "agent",
              "at": "2026-10-24T09:20:00"
            },
            "pr_url": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-27T15:00:00"
            },
            "pr_state": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-27T15:00:00"
            },
            "pr_sha": {
              "by": "runner-sdk/implement-task",
              "kind": "agent",
              "at": "2026-10-27T15:00:00"
            }
          },
          "stale": [],
          "review_items": []
        },
        "cites": {
          "D-2": {
            "type": "decision",
            "title": "CloudEvents envelope, partitioned by order_id",
            "status": "DECIDED",
            "line": "CloudEvents 1.0 JSON; partition key order_id"
          },
          "D-3": {
            "type": "decision",
            "title": "Keep 7 days of events for replay",
            "status": "PROVISIONAL",
            "line": "7 days of retention on the order-events topic"
          },
          "AC-3": {
            "type": "acceptance_criterion",
            "title": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order",
            "status": "APPROVED",
            "line": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order"
          },
          "AC-4": {
            "type": "acceptance_criterion",
            "title": "Given an event older than 6 days, when billing replays the topic, then the event is still readable",
            "status": "APPROVED",
            "line": "Given an event older than 6 days, when billing replays the topic, then the event is still readable"
          }
        },
        "review_items": [],
        "catalog": [],
        "drift": {
          "changes": 0,
          "explained": 0,
          "unexplained": 0,
          "pending_gaps": 0,
          "pending_decisions": 0,
          "other_changes": 3
        }
      }
    }
  ]
}
```

### POST /api/leases/claim

Lease an item. 409 with `error_data {holder, expires_at}` when someone else holds it.

`POST /api/leases/claim` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Request:

```json
{
  "item_key": "task:order-events:T-2",
  "ttl_min": 15
}
```

Response:

```json
{
  "item_key": "task:order-events:T-2",
  "holder": "runner-sdk",
  "acquired_at": "2026-10-28T20:22:21Z",
  "heartbeat_at": "2026-10-28T20:22:21Z",
  "expires_at": "2026-10-28T20:37:21Z"
}
```

### POST /api/leases/task:order-events:T-2/heartbeat

`POST /api/leases/task:order-events:T-2/heartbeat` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Request:

```json
{
  "ttl_min": 30
}
```

Response:

```json
{
  "item_key": "task:order-events:T-2",
  "holder": "runner-sdk",
  "acquired_at": "2026-10-28T20:22:21Z",
  "heartbeat_at": "2026-10-28T20:22:21Z",
  "expires_at": "2026-10-28T20:52:21Z"
}
```

### DELETE /api/leases/task:order-events:T-2

`DELETE /api/leases/task:order-events:T-2` — X-Actor: runner-sdk · X-Actor-Kind: agent → **200**

Response:

```json
{
  "item_key": "task:order-events:T-2",
  "released": true
}
```

## Activity and events

### GET /api/initiatives/order-events/activity?limit=4

Revisions and review-queue moves, newest first. Filters: `since` (ISO), `ref`, `actor` (prefix), `limit`.

`GET /api/initiatives/order-events/activity?limit=4` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "kind": "revision",
    "at": "2026-10-28T20:22:21Z",
    "ref": "DEP-2",
    "type": "deploy",
    "rev": 1,
    "action": "created",
    "title": "production T-1 @ 0000000",
    "status": "FAILED",
    "actor": "github-actions",
    "actor_kind": "system",
    "note": "deploy_guard NO-GO",
    "because": [],
    "batch_id": "3bd983df-6466-4863-aaee-0b1ff7b42696"
  },
  {
    "kind": "revision",
    "at": "2026-10-27T15:00:00Z",
    "ref": "T-2",
    "type": "task",
    "rev": 2,
    "action": "updated",
    "title": "Envelope, partitioning and retention",
    "status": "IN_PROGRESS",
    "actor": "runner-sdk/implement-task",
    "actor_kind": "agent",
    "note": "",
    "because": [],
    "batch_id": "4510286a-5857-49ea-ab70-d2c147128a5a"
  },
  {
    "kind": "revision",
    "at": "2026-10-27T11:00:00Z",
    "ref": "DEP-1",
    "type": "deploy",
    "rev": 1,
    "action": "created",
    "title": "staging T-1 @ 9f3c2e1a7b",
    "status": "PENDING",
    "actor": "github-actions",
    "actor_kind": "system",
    "note": "deploy_guard GO",
    "because": [],
    "batch_id": "19982852-aa24-4846-9c38-ffd8efcecb23"
  },
  {
    "kind": "revision",
    "at": "2026-10-27T10:30:00Z",
    "ref": "APR-2",
    "type": "approval",
    "rev": 1,
    "action": "created",
    "title": "engg approves T-1",
    "status": "CURRENT",
    "actor": "priya",
    "actor_kind": "human",
    "note": "completed by the service",
    "because": [],
    "batch_id": "3dcadabf-58c4-42a1-baf9-4f7f041b8f58"
  }
]
```

### GET /api/initiatives/order-events/events?since=0&limit=3

The event log (`record_written`, `baseline_created`, `review_item_queued`, `review_item_resolved`, `gate_changed`, `initiative_created`, `lease_claimed`, `lease_released`). Poll with `since=<last id>`; `GET /api/events` spans all initiatives.

`GET /api/initiatives/order-events/events?since=0&limit=3` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "id": 1,
    "ts": "2026-10-22T09:00:00Z",
    "kind": "initiative_created",
    "subject": "order-events",
    "actor": "chandra",
    "batch_id": "",
    "payload": {
      "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4211"
    }
  },
  {
    "id": 2,
    "ts": "2026-10-22T09:00:00Z",
    "kind": "record_written",
    "subject": "initiative",
    "actor": "chandra",
    "batch_id": "b607a2ff-78f0-470a-8ada-34a22c6059b6",
    "payload": {
      "type": "initiative",
      "rev": 1,
      "action": "created",
      "actor_kind": "human"
    }
  },
  {
    "id": 3,
    "ts": "2026-10-22T09:00:00Z",
    "kind": "record_written",
    "subject": "A-1",
    "actor": "chandra",
    "batch_id": "b607a2ff-78f0-470a-8ada-34a22c6059b6",
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

`GET /api/standards` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
[
  {
    "ref": "STD-1",
    "type": "standard",
    "title": "Events carry no PII",
    "status": "ENFORCED",
    "pill": "green",
    "line": "Event payloads carry ids and states only — never names, emails, addresses or payment data.",
    "rev": 1,
    "fields": {
      "rule": "Event payloads carry ids and states only — never names, emails, addresses or payment data.",
      "level": "MUST",
      "applies_to": "acme/*",
      "owner": "security",
      "state": "enforced"
    },
    "created_by": "chandra",
    "created_at": "2026-10-27T16:00:00Z",
    "updated_by": "chandra",
    "updated_at": "2026-10-27T16:00:00Z"
  }
]
```

### GET /api/learnings

`GET /api/learnings` — X-Actor: chandra · X-Actor-Kind: human → **200**

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
      "source": "order-events:G-2",
      "provenance": "order-events T-1 deviation, answered by priya"
    },
    "created_by": "runner-sdk/retro-skill",
    "created_at": "2026-10-27T16:00:00Z",
    "updated_by": "runner-sdk/retro-skill",
    "updated_at": "2026-10-27T16:00:00Z"
  }
]
```

### POST /api/learnings/L-1/promote

**human** — promote a learning.

`POST /api/learnings/L-1/promote` — X-Actor: chandra · X-Actor-Kind: human → **200**

Response:

```json
{
  "ok": true,
  "batch_id": "8cb8aa11-c4e1-4723-8712-26f03b9d32d7",
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
  "batch_id": "c71cc0b0-395c-44f8-b056-c3d9187a55fb",
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
