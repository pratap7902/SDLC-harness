---
name: write-tests
description: Write the acceptance tests for a task from its APPROVED acceptance criteria only — never from the implementation — one or more per AC at the AC's level, each named with its AC ref so CI's JUnit report maps back to the criterion. Runs under its own lease (tests:<initiative>:<T-n>), in parallel with implement-task, on the same branch. An untestable criterion raises a gap. Use for next_work kind `tests`.
---

# write-tests

The builder never grades its own work: you write the tests that decide whether the task is
done, from what the humans approved, not from what was built.

## Load

1. `read_record(initiative_id, "<T-n>")` → its `covers` and `repo`.
2. `read_record(initiative_id, [every covered AC-n])` — use only live ACs (APPROVED or
   ADDED_AFTER_BASELINE); skip RETIRED; skip `manual: "yes"` (QA signs those).
3. `drift_report(initiative_id, task="<T-n>")` — an AC changed after the baseline is tested
   in its **current** form.
4. In the repo: the test conventions (CLAUDE.md, README, existing test layout, fixtures) and
   the **interfaces and contracts** you test against — public functions, HTTP routes, message
   schemas, migrations. Do **not** read implementation bodies to decide what to assert; the AC
   decides. If the interface does not exist yet, write the test against the interface the
   decisions/LLD name (it will fail until implement-task lands — that is expected).

## Write

- At least one test per AC, at the AC's `level`: `unit` in the unit suite, `integration`
  against real dependencies the repo's integration suite uses, `e2e` in the e2e suite.
- **Name every test with its AC ref** so the JUnit report maps back:
  `test_AC_3_two_updates_share_partition_key` (pytest), `"AC-3: two updates share the
  partition key"` (jest/vitest), `testAc3TwoUpdatesSharePartitionKey` (JUnit). One AC per
  test name unless a test truly proves several.
- Given / when / then from the AC becomes arrange / act / assert. Assert the observable
  outcome the AC states — not internals.
- Make sure the suite writes JUnit XML where the repo registry says (`junit_path`); CI posts
  it to `POST /api/initiatives/{id}/test-runs/junit` with the PR head sha, which is how
  GATE_PR's `every_covered_ac_has_a_test` and GATE_VALIDATED see your tests.

## Untestable criteria

If an AC cannot be tested as written (ambiguous, not observable, needs an environment that
does not exist): raise a gap — `kind: untestable_ac`, `domain` of whoever owns the AC's
decision, `blocks: ["AC-n"]`, the reason and a proposed testable wording in
`proposed_change`. Do not rewrite the AC yourself.

## Never

- Read implementation code to decide expectations, or weaken a test to make it pass.
- Edit production code (that is implement-task) — test files, fixtures and test config only.
- Push or open a PR — the runner pushes your commits to the task's branch.
- Write `test_run` records yourself; evidence comes from CI at a sha.

Finish with: AC → test name(s) written, ACs skipped (manual) and gaps raised.
