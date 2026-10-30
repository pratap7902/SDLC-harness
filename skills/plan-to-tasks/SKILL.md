---
name: plan-to-tasks
description: Split an approved draft (GATE_DRAFT passed, baseline B-n) into tasks (T-n) that each deploy and roll back on their own — repo and paved-road template from the repo registry, implements D-n, covers AC-n, depends_on. Missing repo or template → a gap, never invented infra. Use for next_work kind `plan` (and review items on tasks).
---

# plan-to-tasks

## Check first

1. `gate_status(initiative_id, "GATE_DRAFT")` must be PASSED. If not, stop: write nothing.
2. `read_record(initiative_id, "draft")`, every `D-n` in it and every live `AC-n`
   (`search_records(initiative_id, type="acceptance_criterion")` — skip RETIRED).
3. `search_records(initiative_id, type="task")` — existing tasks; never duplicate one.
4. `repos()` — the repo registry: each repository's default branch, test command, JUnit path,
   paved-road `templates` and owners. `kb_search` the services involved (architecture,
   ownership, deploy units) and cite what you used as `kb:outline/<doc-id>` in the task's
   `rollback`/goal text where it matters.

## Slice

- Map each decision to the service / repo / module that realises it.
- A task is one deploy unit: it never spans two repos, deploys alone and rolls back alone.
  Use expand–contract for schema changes, feature flags for behaviour, infra first when code
  depends on it (`depends_on`).
- Every live AC is covered by **exactly one** task (`covers`); every task `implements` at
  least one decision. Manual ACs still belong to a task (QA signs them).
- `repo` must be a registered repository name (`owner/name` from `repos`). `template` must be
  one of that repository's `templates`. If the right repo is not registered, or no template
  fits, **raise a gap** (kind unknown, domain engg, `blocks: ["#<task op>"]` or the decision)
  — never invent infrastructure or a template id.
- `rollback`: the concrete steps (flag off, revert migration N, redeploy previous image).

## Write

One batch, `agent: "plan-to-tasks"`:

```json
{"type": "task", "title": "Outbox table and relay", "fields": {
  "goal": "…", "repo": "example/orders", "template": "python-service",
  "implements": ["D-1", "D-2"], "covers": ["AC-1", "AC-2"],
  "depends_on": ["#0"], "rollback": "Disable order_events.enabled; the table stays (expand only)."}}
```

Then `get_state` — the phase moves to BUILD only when every live AC is covered; the
`every_ac_covered_by_a_task` and `every_task_has_template` catalog items must hold.

## Review items on a task

A review item "T-2 ← D-5" means a decision it implements moved. Re-read: update
`implements`/`covers` (the write closes the item as `revised`), or write the task with
`reviewed: true` and a `note` saying why it still holds.

## Never

- Change a decision, an AC or the draft (that is draft-from-ticket, with `because`).
- Plan before GATE_DRAFT passes.
- Name a repo or template the registry does not list.
