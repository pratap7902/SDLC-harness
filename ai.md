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
  never default it. Fields a human must own get `actor: human` in `objects.yaml`; human
  REST endpoints depend on `require_human`.
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
