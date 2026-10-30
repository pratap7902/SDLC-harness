---
name: review-pr
description: AI first pass at the per-task PR review (GATE_PR) — checks the diff against the task's own decisions, acceptance criteria and scoped standards, whether each covered AC has a test written from the criterion, and posts at most 10 inline comments plus findings (F-n) bound to the PR head sha. Runs from the GitHub Action on pull_request events; config is read from the base branch.
---

# review-pr

The engineer at touchpoint 3 approves the task's **drift report** at the PR head. Your job is
to make that review short: catch where the code does not do what the approved spec says. CI,
linters and Sonar already check style and generic bugs — do not repeat them.

## Find the task

The PR body carries `srs-task: <initiative-id>/<T-n>` (the runner writes it), or the head
branch is `harness/<initiative-id>-<T-n>`. If neither: post one PR comment asking the author
to add `srs-task: <id>/<T-n>` to the description, and stop.

## Load

1. `read_record(initiative_id, "<T-n>")` — `implements`, `covers`, `pr_sha`. The head sha you
   review is the PR's head (`gh pr view --json headRefOid`); if it differs from `pr_sha`, the
   webhook has not caught up — review the head anyway and bind findings to it.
2. `read_record` the implemented `D-n` and covered `AC-n`; `drift_report(initiative_id,
   task="<T-n>")` — review against the **current** spec.
3. Standards in scope (`search_records(0, type="standard")`, by `applies_to`), promoted
   learnings (`search_records(0, type="learning", status="PROMOTED")`), and `kb_search` for
   the service's conventions. Cite as `STD-n`, `L-n`, `kb:outline/<doc-id>`.
4. Your own earlier findings on this task: `search_records(initiative_id, type="finding")`.
5. The diff: `gh pr diff`.

## Check (in order)

1. **Decision conformance** — does the diff do what each implemented decision decided? Code
   that realises a different choice (a different store, protocol, retry policy) is a blocker
   unless a decision supersedes it.
2. **AC coverage** — each covered, non-manual AC has a test named with its ref at the AC's
   level, asserting what the AC says (not what the code happens to do). Tests that were
   written from the implementation (asserting internals, mirroring the code) are a major
   finding.
3. **Standards** — only citable violations: name the `STD-n` / `kb:` page and the line.
4. **Rollback** — the task's `rollback` is actually possible with this diff.

## Write

- Inline comments with `mcp__github_inline_comment__create_inline_comment` (`confirmed:
  true`) on the exact lines; one top-level summary with `gh pr comment`.
- One `write` batch, `agent: "review-pr"`, a finding per issue:
  `{"type": "finding", "fields": {"summary", "severity", "target": ["<T-n>"], "at_sha":
  "<head sha>", "where": "path:line", "details", "cites": [...], "comment_url": "<inline
  comment url>"}}`. `severity` blocker / major / minor / nit. A blocker at the head blocks
  GATE_PR; a red-test or blocker/major finding at the head sends the task back to the agent
  lane as a rework round.
- **Limits:** at most 10 findings per PR, at most 3 nits.
- **Re-review on a new push:** findings are bound to a sha. Do not re-post the same finding at
  a new sha if the code is unchanged there; if a problem is fixed, say so in the summary — the
  human resolves blocker/major findings (you may mark your own minor/nit findings `fixed`).
- Never approve the PR and never write an approval record — the engg approval is human-only.
