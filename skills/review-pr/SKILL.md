---
name: review-pr
description: AI first pass at the per-task change review (GATE_PR) — checks the branch diff against the task's own decisions, acceptance criteria and scoped standards, whether each covered AC has a test written from the criterion, and writes findings (F-n, at most 10) bound to the head sha. Local mode (default) runs it in the runner against `git diff <base>...<branch>`; GitHub mode runs it from the Action on pull_request events with inline comments.
---

# review-pr

The engineer at touchpoint 3 approves the task's **drift report** at the head sha. Your job is
to make that review short: catch where the code does not do what the approved spec says. CI,
linters and Sonar already check style and generic bugs — do not repeat them.

## Where you are

- **Local mode (the runner, the default):** the work item names the task; the working
  directory is a sandbox worktree of branch `harness/<initiative-id>-<T-n>`; the brief gives
  the base branch and the HEAD SHA. The task's `pr_url` is `local:<repo>@<branch>`. There is
  no GitHub: read the change with `git diff <base>...<branch>` / `git log <base>..<branch>`
  / `git show`, and your findings are the review.
- **GitHub mode (the Action):** the PR body carries `srs-task: <initiative-id>/<T-n>` or the
  head branch is `harness/<initiative-id>-<T-n>`; if neither, post one PR comment asking for
  the marker and stop. The diff is `gh pr diff`; the head is `gh pr view --json headRefOid`.

## Load

1. `read_record(initiative_id, "<T-n>")` — `implements`, `covers`, `pr_sha`. Review the
   head you were given; if it differs from `pr_sha`, review the head anyway and bind findings
   to it.
2. `read_record` the implemented `D-n` and covered `AC-n`; `drift_report(initiative_id,
   task="<T-n>")` — review against the **current** spec.
3. Standards in scope (`search_records(0, type="standard")`, by `applies_to`), promoted
   learnings (`search_records(0, type="learning", status="PROMOTED")`), and `kb_search` for
   the service's conventions. Cite as `STD-n`, `L-n`, `kb:outline/<doc-id>`.
4. Your own earlier findings on this task: `search_records(initiative_id, type="finding")`.
5. The diff (see above).

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

- One `write` batch, `agent: "review-pr"`, a finding per issue:
  `{"type": "finding", "fields": {"summary", "severity", "target": ["<T-n>"], "at_sha":
  "<head sha>", "where": "path:line", "details", "cites": [...]}}`. `severity` blocker /
  major / minor / nit. A blocker at the head blocks GATE_PR; a blocker/major finding at the
  head sends the task back to the agent lane as a rework round.
- GitHub mode only: also inline comments with
  `mcp__github_inline_comment__create_inline_comment` (`confirmed: true`) on the exact
  lines, their URL in the finding's `comment_url`, and one summary with `gh pr comment`.
- **Limits:** at most 10 findings per review, at most 3 nits. A clean change gets no
  findings — say so in your summary.
- **Re-review at a new sha:** findings are bound to a sha. Do not re-file the same finding at
  a new sha if the code is unchanged there; if a problem is fixed, say so in the summary — the
  human resolves blocker/major findings (you may mark your own minor/nit findings `fixed`).
- Never edit code, never commit, never approve and never write an approval record — the engg
  approval of the head sha is a human's, in the harness UI.
