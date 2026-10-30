---
name: draft-from-ticket
description: Turn an initiative's pinned requirement into the draft the DRI approves at GATE_DRAFT — decision records (D-n), gaps for every unknown (G-n), acceptance criteria (AC-n), the draft sections and the draft-phase catalog — grounded in the knowledge base. Also revises a REOPENED draft and answers review items on spec records. Use for next_work kinds `draft` and `review` (spec targets).
---

# draft-from-ticket

You write what the DRI approves at touchpoint 1. A misunderstanding caught here costs a
re-draft; one caught in a PR costs a rebuild. Optimise for a reviewer who approves or rejects
**decisions and acceptance criteria**, not prose.

## The record service (MCP server `srs`)

- Initiatives are addressed by numeric `initiative_id`. Records by ref: `draft`,
  `initiative` (singletons), `D-n`, `G-n`, `AC-n`, `T-n`, `F-n`.
- Call `blueprint` once (or `blueprint(type="decision")`) before your first write: it lists
  every field, its limit, which fields are HUMAN-ONLY, and the rules.
- `write(initiative_id, ops, batch_id, agent="draft-from-ticket")` is atomic. An op is
  `{ref?, type?, title?, fields, because?, note?, base_rev?, reviewed?}`; omit `ref` and give
  `type` to mint; `"#0"` names the ref op 0 of the same batch minted. Never send `status`
  (every status is derived). Re-send the same `batch_id` to retry safely; a new batch needs a
  new id (`<work item key>:<step>`).
- A write that comes back with errors saved nothing. Read the errors, fix every op, retry with
  a new batch_id.

## Start

1. `get_state(initiative_id)` — phase, gates, baseline, counts.
2. `read_record(initiative_id, "initiative")` — the pinned requirement is the spec snapshot
   (`initiatives` / the context bundle carry it); `prd_refs` and `work_item_url` link out.
   Work from the snapshot: it is what gets cited and diffed.
3. If a draft exists: `read_record(initiative_id, "draft", history=true)` and
   `search_records(initiative_id)` — you are revising, not starting over.
4. If the requirement visibly contradicts a linked PRD or work item you can read, do not draft
   around it: raise a gap with `kind: prd_drift` asking whether to re-pin (a human re-pins).

## Ground it in the knowledge base

- `kb_search(query)` for: the services and capabilities this touches (what already exists —
  never design what we already run), the standards that apply, past decisions on the same
  question (precedent), runbooks and rollback patterns.
- `kb_get("kb:outline/<doc-id>")` (add `#<heading-anchor>` for one section) to read a hit.
- Cite what you used: put the citation `kb:outline/<doc-id>` (or `kb:outline/<doc-id>#<anchor>`)
  in the record's `cites` (decisions), and name it in `rationale`. Standards in the service are
  cited as `STD-n`; prior decisions as `D-n`. A verdict with nothing to cite stays OPEN.
- If the knowledge base has nothing on a question that needs house knowledge, that is a gap,
  not a guess.

## Procedure

1. **Problem** — restate the outcome in 3–5 sentences: who, what changes for them, what
   "done" means. If you cannot say what done means, that is your first gap (domain product).
2. **Decisions** — any choice a reasonable engineer could make differently (storage,
   sync/async, contract shape, new service vs extending one, migration approach). Per decision:
   - `question`, `domain` (product | design | engg — who must own the answer), `level`:
     **MUST** when getting it wrong breaks a standard, a contract, data or security;
     **SHOULD** when it is a reversible default.
   - 2–3 real `options` rows `{name, consequences, cost_risk}`. No straw men.
   - Precedent first: if a `D-n` or a KB decision already settled this in the same context,
     reuse its verdict and cite it. Overturning precedent is a new decision that `cites` it and
     says why.
   - `verdict` + `rationale` + `decided_by: "<you>/draft-from-ticket"` + `decided_on` (today)
     only when the citations settle it. **On a MUST decision you may not write the verdict**
     (HUMAN-ONLY): leave it empty — it is OPEN, routed to the domain's assignee.
   - **Provisional only at SHOULD**: when work can continue on a cited default, set
     `verdict`, `provisional: "yes"` and say in `rationale` what would change it. Never
     provisional at MUST. The deploy guard never accepts a provisional verdict.
   - **Conflicts become OPEN decisions.** PRD vs a standard, or two standards: cite both
     sides, give options with consequences, never rank them yourself; draft everything that
     does not depend on it.
3. **Gaps** — every unknown you would otherwise guess: `question` (one question), `kind`
   (unknown | conflict | prd_drift | untestable_ac), `domain`, `level` (MUST blocks what it
   names; SHOULD lets work continue on your `recommendation`), `asked_by`, `why_now`,
   `context` (readable cold, with a concrete example), `options` rows `{key, label,
   consequence}`, `recommendation` + `recommendation_why`, and `blocks: [refs it blocks]`.
   You never write `answer`, `choice` or `answered_*` — humans answer in their inbox.
4. **Acceptance criteria** — given / when / then, atomic, one behaviour each, testable at its
   `level` (unit | integration | e2e). `source: [D-n]` (or `["initiative"]` for a
   requirement-level criterion). Every decision is covered by at least one AC.
   `manual: "yes"` only when it truly cannot be automated (QA signs it at GATE_VALIDATED); say
   why in the text.
5. **Draft** — `ref: "draft"` with `problem`, `hld` (cite `D-n` bare), `lld` (modules,
   interfaces, data, migrations), `scope_in`, `scope_out` (each implied-but-unstated item with
   a reason), `test_strategy` (levels, environments, what is manual and why), `summary`,
   `decisions: [D-…]`, `criteria: [AC-…]`.
6. **Catalog** — `ref: "initiative"`, `fields.catalog`: one row per draft-phase item
   (security_review, rollback_plan, observability, data_migration_assessed, test_strategy):
   `{item, phase: "draft", disposition: addressed | not_applicable, note, refs}`. A
   `not_applicable` needs a real reason.
7. **One batch** — decisions, gaps, ACs, the draft and the catalog in a single `write`, using
   `#n` for refs minted in the same batch.
8. **Submit** — when nothing you can resolve is left, set `submitted_rev` on the draft to the
   draft's current rev (a second small write). `gate_status(initiative_id, "GATE_DRAFT")`
   should then fail only on what humans own (OPEN MUST decisions, open MUST gaps, the DRI
   approval).

## Revising (REOPENED draft, review items, answered gaps)

- After a baseline (B-n), every material change to a draft section, a decision verdict or an
  AC **needs `because`**, and every cause must end in a human act: a gap a human answered, a
  decision a human ruled or a baseline approved, or a finding a human raised or resolved.
  Your own finding explains nothing. The write path refuses anything else.
- A DECIDED decision is never edited: write a new decision with `supersedes: ["D-3"]` and
  `because: ["G-4"]`. A new AC after the baseline needs `because`. You cannot retire an AC
  (HUMAN-ONLY `retired_because`): raise a gap asking for it.
- A review item ("D-2 ← G-1 moved"): re-read the target against the cause. Either revise it
  (with `because: [cause]`) — that closes the item as `revised` — or, if it still holds, write
  the target with `reviewed: true` and a `note` saying why; a human then upholds it.
- Then record on the gap what you did: `resolution: "D-5 supersedes D-2; AC-8 added"`.

## Never

- Guess product intent — raise a gap (domain product).
- Write a HUMAN-ONLY field: a gap's answer, an approval, a MUST verdict, an escalated
  verdict, AC retirement, QA sign-off.
- Change the spec after a baseline without `because`.
- Exceed about a 10-minute review: fewer decisions with sharper options beat many.
