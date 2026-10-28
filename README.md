# SDLC Record Service (`srs`)

The system of record for the automated SDLC pipeline. Agents (the runner and its skills)
write **typed records** through one validated write path; statuses, gates, the worklist
and the **drift report** are derived from those records on read. Humans touch the work at
exactly three points, and the service shapes each of them.

Built from the [custom-integration-service](../../custom-integration-service) (CIS)
pattern: FastAPI DDD layout, a generic record store governed by YAML, an MCP adapter for
agents. Conventions for editing this repo: [`ai.md`](./ai.md). REST contract for the web
UI: [`docs/api.md`](./docs/api.md).

## Run it

```bash
make install   # .venv with Python 3.12 (override: make install PYTHON=/path/to/python3.12)
make seed      # migrate + load the demo scenario into var/dev.db (SQLite)
make dev       # http://localhost:8791 · OpenAPI at /docs · MCP at /mcp · /health
make test      # the suite, on in-memory SQLite
make check     # lint blueprint/*.yaml (types, vocab, lifecycle, rule ↔ code pairing)
make frontend  # build the web UI into frontend/dist (see "The web UI" below)
```

MySQL instead of SQLite: `make db` (MySQL 8 in docker on port 3311, db `srs`), then set
`DB_MYSQL_HOST=127.0.0.1` (or `DATABASE_URL=mysql+mysqlconnector://root:srs@127.0.0.1:3311/srs`)
in `.env` and `make migrate`. `make test-mysql` runs the suite against `srs_test`. Settings:
[`.env.example`](./.env.example).

Agents connect with the checked-in [`.mcp.json`](./.mcp.json), or
`claude mcp add --transport http srs http://localhost:8791/mcp`. Without MCP:
`scripts/srs.py <tool> '<json args>'` (`scripts/srs.py --tools` lists them).

The demo (`make seed`): **order-events** — a draft with three decisions, a product gap
answered by maya, baseline B-1 approved by chandra; mid-build T-1 hits a deviation (G-2:
use the platform CDC pipeline), priya answers, the runner supersedes D-1 with D-4 and adds
AC-5 *because* D-4; T-1's drift report shows that chain with 0 unexplained, priya approved
it at the PR head and the deploy guard says GO; T-2's drift report is CLEAN. **refund-events**
— still in DRAFT with an open, overdue product gap and an open MUST decision in maya's
inbox. People: chandra (dri), priya and omar (engg), maya (product), leo (design), sam (qa).

## The three human touchpoints

| # | Touchpoint | The human sees | The service does |
|---|---|---|---|
| 1 | **Draft review** (`GATE_DRAFT`, `/i/:slug/draft`) | The draft (problem, HLD, LLD, scope, test strategy), its decisions with options, its acceptance criteria, its gaps, the draft-phase catalog. One button: *Approve*. | Refuses the approval while a decision is OPEN, a MUST gap blocks the spec, a spec record is up for review, the catalog is unaddressed, or a decision has no AC. The approval writes baseline **B-n**: a frozen snapshot of the draft and every decision, AC and gap. From then on every spec change must be *explained*. |
| 2 | **Gap reviews** (`/inbox/:person`) | A personal inbox: gaps and decisions to rule, routed by domain (product / design / engg → the assignee of that role; unroutable → the DRI), with context, options, a recommendation, what they block, an SLA. | A gap's `answer` is `actor: human` — agents cannot write it. Answering is a material change: what the gap blocks goes up for review (routed too), and the answer becomes the provenance of the drift that follows. MUST-level gaps block what they name; SHOULD-level ones let work continue. |
| 3 | **Final PR review, per task** (`GATE_PR`, `/i/:slug/t/:ref`) | The task-scoped **drift report**: "approved baseline B-1 → these answers/decisions changed the spec for T-1 → resulting spec; 0 unexplained". The reviewer approves the drift, not the feature. | `GATE_PR` needs the PR open, no open blocker finding at the head, every covered AC tested, `drift_report(task).unexplained == []`, and an engg approval **pinned to the PR sha and the report's digest**. A new push or new drift makes the approval STALE: the gate re-blocks and the deploy guard goes NO-GO without anyone flipping a bit. |

## The drift report

*Given approved baseline B-k, what is different in the spec now, and which human decision
authorised each difference?* (`GET /api/initiatives/{slug}/drift?task=T-n`, MCP
`drift_report`, `format=json|md|text`.)

It is a pure query over what the write path already stores: the baseline's members and
snapshot, every revision after it (who, `actor_kind`, `because`), and the typed links. It
returns a chronological timeline of **entries** — `gap_answered`, `decision_superseded`,
`decision_added`, `decision_changed`, `decision_confirmed`, `ac_added`, `ac_changed`,
`ac_retired`, `draft_edited`, `requirement_repinned` — each with its `because` and an
`explanation` per cause; the **unexplained** ones; open gaps raised since; a **spec diff**
(unified diffs of draft sections; decisions added / superseded / changed; criteria added /
retired / changed); the **approved spec** and the **current spec** side by side; and a
**digest** (sha256 of entries + diff) that an engg approval pins.

A change is *explained* when it was made by a human, or when every `because` ref is a gap a
human answered, a decision that is itself grounded (ruled by a human, approved in a
baseline, or explained by its own `because` — one chain), or a finding that was not
rejected. Task scope = the task's `implements` and `covers`, expanded through supersede
chains, the decisions its ACs come from, the ACs sourced from or caused by those
decisions, and the draft when it cites them; gaps whose `blocks` touch that scope. Changes
outside the scope are counted (`other_changes`), not listed.

Three write-path rules make the report complete rather than best-effort:

1. After a baseline, an agent's material edit to a spec record (draft sections, a
   decision's verdict, an AC's text) needs `because`, and every cause must explain.
2. A DECIDED decision is never edited — it is superseded by a new decision that carries
   `because` ("ADRs are superseded, never edited").
3. An AC that appears after the baseline needs `because`; one that disappears needs a
   human's `retired_because`.

So agents cannot change the spec silently: the only path is to raise a gap (touchpoint 2)
or cite a finding, and the human answer becomes the drift entry's provenance. If a cause
later stops explaining (a finding is rejected), the entry turns UNEXPLAINED, the draft is
REOPENED, and GATE_PR blocks.

## How it fits together

```
blueprint/*.yaml ──► app/blueprint      record types, vocabularies, lifecycle (derived-status
   (engineers edit)                     rules, catalogs, gates, routing) — `make check`
                          │ validates every write
                          ▼
runner/agents ─► /mcp ─┐
web UI ───────► /api ──┼─► app/initiatives  RecordService.write — the single write path:
intake (and later ADO) ┘        │           idempotent atomic batches, minted refs, typed
                                │           links, revisions (actor, actor_kind, because),
                                │           human-only fields, post-baseline `because`,
                                │           approval → baseline, review queue, events
                                ▼
                    SQLite / MySQL          initiatives · records · record_revisions ·
                                            record_links · review_items · write_batches ·
                                            leases · ref_counters · events
                                ▲
     RecordGraph (on read) ─────┘  StatusRules → every status · GateRules → gates ·
                                   DriftService → the drift report · worklist / inbox
```

- **The database is generic; the blueprint is the schema.** `records.type` and
  `records.fields` are governed by [`blueprint/objects.yaml`](./blueprint/objects.yaml). A
  new field, type or status is a YAML edit — no migration.
- **Every status is derived** ([`blueprint/lifecycle.yaml`](./blueprint/lifecycle.yaml)
  names each rule in plain English; `app/initiatives/services/status_rules.py` implements
  it; `make check` pairs them both ways). A write that sends `status` is refused. The
  `status` column is a cache the write path fills.
- **Gates are evaluated on read, never stored**: `GATE_DRAFT`, `GATE_PR` (per task),
  `GATE_VALIDATED`; plus `deploy_guard(initiative, task, sha, environment)` for CI/CD.
- **Who wrote it, and as what.** Every revision records `actor` and `actor_kind`
  (`human | agent | system`). Fields marked `actor: human` (a gap's answer, approvals, a
  MUST or escalated verdict, AC retirement, QA sign-off, learning promotion) refuse agent
  writes; the human REST endpoints return 403 to agents; MCP callers are always agents and
  there are no human-only MCP tools.
- **A change puts what rests on it up for review** (CIS review queue): a material change
  queues linked or mentioning records of the types the blueprint's `propagates_to` names,
  routed to a person; editing the target (`revised`) or saying why it holds (`upheld`)
  closes it.
- **The worklist is the pipeline's cursor**: `next_work` returns the items a caller may
  take now (not leased by someone else), each with a context bundle; `claim` /
  `heartbeat` / `release` lease them (expiry is evaluated on read).

Layout: `app/blueprint` (loader, validator), `app/initiatives` (models, repositories,
services: `record_service`, `record_graph`, `status_rules`, `gate_rules`, `drift_service`,
`drift_render`, `review_service`, `routing`, `inbox_service`, `worklist_service`,
`initiative_service` (intake), `deploy_guard`, `activity_service`, `views`), `app/mcp`
(tools + compact text formatters), `app/web` (SPA serving), `migrations/` (one hand-written
portable migration), `scripts/` (`seed_demo.py`, `gen_api_docs.py`, `srs.py`).

## Starting a feature (intake) — and Azure DevOps later

Features start inside the service: `POST /api/initiatives` (the UI's `/new` page) or the
MCP tool `create_initiative`, with `{title, slug?, requirement (markdown), work_item_url?,
dri, engg, product?, design?, qa?}`. It creates the initiative, pins `spec_snapshot =
{requirement, work_item_url, created_by, at}` and its sha256, and writes the `assignment`
records in the same batch. A human may re-pin the requirement
(`POST /api/initiatives/{slug}/snapshot`) — a material change that puts the draft up for
review and shows in the drift report.

Both paths call one function, `IntakeService.start(StartFeature, actor)`
(`app/initiatives/services/initiative_service.py`). An **Azure DevOps importer** (deferred)
maps a work item to the same `StartFeature` — description → `requirement`, the work item
link → `work_item_url`, assigned people → roles — and calls it with a `system` actor; no
other code changes.

## The web UI (`frontend/`)

React 18 · react-router 6 · Vite 5 · Tailwind 3 · TypeScript, laid out like CIS's frontend
(`src/{main.tsx,api.ts,index.css,shell/,pages/,components/,lib/}`). No private packages:
plain Tailwind components in `components/ui.tsx`; the palette (pink = needs a human, indigo
= agent, green / amber / red) lives in `tailwind.config.cjs`.

```bash
# dev: hot reload on :5173, /api proxied to the backend on :8791
make seed && make dev          # terminal 1
make frontend-dev              # terminal 2 → http://localhost:5173

# built: the backend serves frontend/dist at the page paths
make frontend                  # npm ci only when package-lock.json changed, then tsc + vite build
make dev                       # → http://localhost:8791
```

- **Viewing as** (sidebar): the person the UI acts as. Every request sends
  `X-Actor: <person>` and `X-Actor-Kind: human` (AUTH_MODE=header, dev only); the choice is
  kept in localStorage. Answers, rulings, approvals and sign-offs are recorded under it, and
  buttons for another role are disabled with the reason.
- Pages: `/` features (decisions waiting across every inbox, PR approvals, all features),
  `/new`, `/inbox/:person` (touchpoint 2), `/i/:slug`, `/i/:slug/draft` (touchpoint 1),
  `/i/:slug/t/:ref` (touchpoint 3, the task's drift report), `/i/:slug/drift`,
  `/i/:slug/r/:ref`, `/i/:slug/reviews`, `/i/:slug/activity`, `/standards`, `/learnings`,
  `/blueprint`. `app/web/spa.py` serves `index.html` at exactly these paths (listed, never a
  catch-all) and `/assets/*`: a new page is a route in `src/main.tsx` and a path there.
- Composed from existing endpoints, no UI-only API: "decisions waiting" = `GET /api/people`
  then each non-empty `GET /api/inbox/{person}`; "agents working" = the worklist's agent
  lane; "recently resolved" = each initiative's `activity?actor=<person>`. **Request
  changes** (draft or PR) writes a `finding` on the target through `POST …/records`
  (severity `major` on the draft; `blocker` at the PR head, so GATE_PR blocks until fixed).
- Types for every response: `frontend/src/api.ts`; fetch helpers / `useJson`: `src/lib/api.ts`.

## Deviations from the plan

- **No Linear.** No `/hooks/linear`, no `intake_events`; features start in the service
  (above). `ticket_url` is `work_item_url` (optional) everywhere.
- **JSON is snake_case** (CIS used camelCase aliases): one shape for REST, MCP `as_json`
  and the docs.
- **Baseline members** are every decision, AC and gap of the initiative at approval (plus
  the draft), not only those linked from the draft: nothing in scope can be missed by a
  forgotten `contains` link.
- **`GATE_DRAFT` holds once approved**: its other rules are preconditions checked when the
  DRI approves; afterwards the gate passes while the approval is CURRENT (draft not
  REOPENED). Mid-build open gaps do not regress the phase.
- **`deploy_guard` scopes `GATE_VALIDATED` to the task's ACs** (tasks deploy
  independently); the initiative-level `GATE_VALIDATED` still needs every live AC green.
- **The concurrent-write window** (CIS: a field another writer set in the last 15 min is
  only overwritten with `base_rev`) applies to agents; a human edit is deliberate.
- **The approver must hold the role** (an ACTIVE assignment for dri / engg / qa) — in
  header mode this stands in for token roles.
- **Unexplained drift by agents is refused at write time**; it can still appear later when
  a cause stops explaining (a rejected finding) — that is what the UNEXPLAINED state,
  REOPENED draft and blocked GATE_PR show.
- **Standards and learnings** (global scope, initiative 0, no FK) are included minimally:
  write, list, human promotion.
- Ref counters are seeded from the highest existing ref the first time a prefix is used.

## Deferred

- **Azure DevOps ingestion** (importer calling `IntakeService.start`; tracker sync of
  `task.tracker_*`).
- **Auth tokens** (`AUTH_MODE=token`, `actor_tokens`, `mint_token.py`, Cloudflare Access
  for humans). Today `AUTH_MODE=header` trusts `X-Actor` / `X-Actor-Kind` — dev only.
- **GitHub PR sync** (CIS `pr_readiness.py` → `task.pr_state/pr_sha/review_rounds`); CI
  attempt counting; the runner writes these fields for now.
- SLA escalation notifications (the inbox computes `due_at` / `overdue`; nudging is a
  runner's job), WIP limits in `next_work`, the LLM review judge (rules only), evidence
  attachments, docs-as-code `baseline.at_sha`, multi-repo per-task gate evaluation.
