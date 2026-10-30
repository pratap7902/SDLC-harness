# SDLC Record Service — read this first

Three domains, two adapters:

- `app/blueprint` — loads and lints `blueprint/*.yaml` (record types, vocabularies, the
  lifecycle: derived-status rules, catalogs, gates, routing) and validates records against
  it. No database tables.
- `app/initiatives` — initiatives, records, typed links, revisions, review items, leases,
  events. `RecordService.write` is the ONLY write path; REST, MCP, the intake and the human
  endpoints all go through it.
- `app/mcp` — agent tools. Adapter only: call services, format with `formatters.py`.
  Output is compact text, never JSON dumps (every token is paid for by an agent). Every MCP
  caller is an agent; never add a human-only operation as a tool.
- `app/web` — serves the React build at the listed page paths. Adapter only.

Rules specific to this service:

- A new field, record type, status value, catalog item or gate rule is a `blueprint/` edit
  plus `make check` — never a column or a migration. Migrations are for the generic tables.
- Every status is derived. A new status rule is a `rule:` in `lifecycle.yaml` AND a
  `@rule(...)` function in `status_rules.py` (same for gate rules in `gate_rules.py`);
  `make check` fails when either side is missing.
- Repositories flush; only `RecordService.write` (and the lease / review endpoints for
  their own rows) commit. A batch is atomic: collect every error, roll back everything.
- Every write path takes an `Actor` (principal + kind) and passes it to `RecordService`;
  never default it. Callers are authenticated only by `app/auth/services/authenticator.py`
  (bearer token; X-Actor headers in local/testing header mode, missing kind = agent) — never
  build an Actor from a header elsewhere. `system` is the service's own kind (never a
  caller's); it gets no exemptions in the write path. Fields a human must own get
  `actor: human` in `objects.yaml`; conditional ones `actor_rules` (judged before AND after,
  and loosening a rule is itself human-only). Human REST endpoints depend on `Human`
  (`app/auth/dependencies.py`). Upholding / dismissing review items is human.
- An explanation (`because`) must end in a human act: a human answer, a human ruling, a
  baseline approval, or a finding a human raised or resolved. Do not add a cause type that
  an agent can produce on its own.
- Evidence is bound to a commit: a gate rule about test runs filters by `at_sha`.
- Integrations (`app/teams`, `app/knowledge`, `app/azure_devops`) are plain services plus
  settings; secrets and every tenant-specific value (hosts, org, tenant ids) come from env,
  never the code. HTTP goes through `app.core.utils.http.client()` (tests set
  `http.TRANSPORT` — no real network in tests). They write only through
  `RecordService.write`: as the mapped human (`via=teams`), or as the service
  (`SERVICE.with_agent(...)`). Webhooks live on the public `hooks_router` and verify their
  own signature / secret first. People are one row each (`app/people`); never create a
  person from an integration automatically — unmatched accounts go to the review list.
- After a baseline, a spec change must carry `because`. Do not add a write path that moves
  a draft section, a decision verdict or an AC without going through `_cause_errors`.
- The drift report reads only stored data (revisions, links, baselines). If it needs a new
  fact, store it on the revision in the write path — never compute history elsewhere.
- Fields hold markdown with bare refs (`D-4`); never store links to records. Refs fields
  (`type: refs`) are how typed edges are made.
- JSON keys are snake_case; one builder per shape in `services/views.py`. When a response
  shape changes, regenerate `docs/api.md` (`.venv/bin/python scripts/gen_api_docs.py`) —
  the frontend builds against that file alone.
- Time comes from `app.core.utils.time.utcnow()` (the seed script shifts it).

## Layering (from the FastAPI template)

```
request → routes.py → controller / service → repository → model
                         ▲ RecordService.write is the transaction boundary
```

- One domain per package under `app/`; cross-domain calls go through services.
- snake_case files; suffixes `_service.py`, `_repository.py`, `_controller.py`; models
  are bare nouns (`record.py`).
- Requests are pydantic models in `requests/`; exceptions are `app.exceptions.*`
  (`ValidationException` → 422 with `error_data`, `NotFoundException` → 404,
  `ConflictException` → 409, `ForbiddenException` → 403), rendered as RFC 9457 problem JSON
  by `app/core/exception_handlers.py`.
- Tests: `tests/unit` (pure: graphs built in memory, the validator, the loader,
  formatters) and `tests/e2e` (TestClient over a fresh in-memory SQLite per test;
  `TEST_DATABASE_URL` points them at MySQL). The `api` fixture drives REST as a named
  human or agent; `tests/fixtures/slice.py` holds the vertical slice's content.
