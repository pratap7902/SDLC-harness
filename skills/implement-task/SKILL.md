---
name: implement-task
description: Implement one task (T-n) on the paved road in its repository clone — the decisions it implements, the repo's conventions and scoped standards — until the AC tests written by write-tests and the repo's checks pass. Does not write or edit AC tests. A wrong decision goes back as a deviation gap, never a quiet workaround. Use for next_work kind `task`, including rework rounds (red CI or review findings at the PR head).
---

# implement-task

You are in a working copy of the task's repository, on branch `harness/<initiative>-<task>`.
In local mode (the default) it is a sandbox worktree with no remote to push to: the branch and
its head sha are the change humans review, and the runner records them as the task's
`pr_url` (`local:<repo>@<branch>`) and `pr_sha`. In GitHub mode the runner pushes your commits
as the GitHub App and opens or updates the PR. Either way you never push, never open a PR,
never touch git remotes or config.

## Load (three calls get you the full context)

1. `read_record(initiative_id, "<T-n>")` — goal, repo, template, implements, covers,
   depends_on, rollback, pr_* and the attempt counters.
2. `read_record(initiative_id, [the implemented D-n…, the covered AC-n…])` and
   `drift_report(initiative_id, task="<T-n>")` — the spec you build is the **current** spec
   (approved baseline + explained drift), not the draft as first written.
3. Standards in scope: `search_records(0, type="standard")`, filtered by `applies_to` for this
   repo/paths. `kb_search` for the service's architecture page and conventions (`kb_get` to
   read; cite `kb:outline/<doc-id>` in a gap or note when you rely on one).

Then read the repo itself: its CLAUDE.md / README, the paved-road template the task names,
and the code you will change. Follow the house patterns you find over textbook ones.

## Build

- Generate from the named template; infrastructure changes set the IaC module's parameters
  only — no hand-written infra outside the templates.
- Implement exactly what the decisions say. Small, reviewable commits; messages start with the
  task ref (`T-3: relay retries with backoff`).
- Run the repo's checks the brief names (lint, unit, integration) and fix what fails.
- **Tests:** the AC tests are write-tests' job (from the approved criteria, separately). Do
  not write, rename, weaken, skip or delete a test whose name carries an AC ref (`AC-3`,
  `test_AC_3_…`). Unit tests for your own internals are fine.
- No secrets in code, config or commits. No new network endpoints, credentials or external
  services the decisions do not name.

## When the spec is wrong

If implementing exactly what a decision or AC says is impossible, unsafe or contradicts the
code you find: stop that line of work and **raise a gap** — `kind: deviation`, `domain` of
whoever owns the call, `blocks: ["<D-n or AC-n>", "<T-n>"]`, the evidence in `context`, the
exact change wanted in `proposed_change` (old → new), options and your recommendation. A MUST
gap blocks the task; leave the branch in a consistent state and finish. When the human has
answered (a later run), apply it with `because`: supersede the decision
(`supersedes: ["D-1"], because: ["G-4"]`), add the AC with `because`, update the task's
`implements` / `covers`. Every `because` must end in a human act — the write path refuses
anything else.

A SHOULD-level ambiguity you can resolve with a cited default: proceed on it and say so in
your summary; the reviewer sees it in the drift report.

## Rework rounds

The work item says `rework: ci` (tests RED/ERROR at the PR head — the run is in
`rework_refs`) or `rework: review` (open blocker/major findings at the head). Read those
records (`read_record`), fix the cause, and finish; the runner records the new head sha, which
makes old findings and approvals stale by itself. Never resolve a blocker/major finding
yourself (HUMAN-ONLY), nor any finding a human raised; on an agent-raised minor/nit you fixed
you may write `resolution: "fixed"` with a `resolution_note`.

**Handoff:** the runner counts CI attempts and review rounds on the task. At 3 of either the
task is STUCK and goes to a human — so if you see the same failure twice and do not know why,
say so plainly in your summary instead of guessing a third time.

## Finish

Leave the tree committed or uncommitted — the runner commits what is left. End with: what you
changed (files, decisions realised), what you raised (G-n), what the reviewer should look at.
