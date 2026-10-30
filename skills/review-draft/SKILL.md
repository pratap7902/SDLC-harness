---
name: review-draft
description: First-pass review of a submitted draft before the DRI's GATE_DRAFT review — findings (F-n) bound to the draft revision, on hidden decisions, missing citations, untestable or uncovered criteria, provisional verdicts at MUST level, weak catalog answers. Never answers gaps or writes verdicts. Runs after draft-from-ticket submits.
---

# review-draft

You make touchpoint 1 faster and sharper: the DRI should read your findings and spend their
time on the real calls. You write **findings**, nothing else.

## Load

1. `get_state(initiative_id)`, then `read_record(initiative_id, "draft")` — note its `rev`
   and `submitted_rev`.
2. `read_record` every ref in `draft.decisions` and `draft.criteria`, and
   `search_records(initiative_id, type="gap")`.
3. `gate_status(initiative_id, "GATE_DRAFT")` — what the service already blocks on; do not
   repeat it as findings.
4. `search_records(0, type="standard")` for the standards in scope, and `kb_search` for the
   services the draft touches and precedent on its questions (`kb_get` to read). Cite KB
   material as `kb:outline/<doc-id>[#anchor]`.

## What to look for (in order of value)

1. **Hidden decisions** — a choice the HLD/LLD makes without a `D-n` (a store, a protocol, a
   retry policy, a new dependency). The top finding a draft can get.
2. **Per decision** — breaks a standard (cite `STD-n` or the KB page); contradicts precedent
   without saying why; verdict without citations; `provisional: yes` on a MUST decision (never
   allowed); wrong `domain` (a product call tagged engg routes to the wrong human); options
   that are straw men.
3. **Per AC** — covers a decision (`source`), atomic, testable at its `level`; `manual: yes`
   where automation is possible; a decision no AC covers.
4. **Whole draft** — scope drift from the pinned requirement; guesses that should be gaps
   (state what is being guessed); catalog `not_applicable` without a reason; rollback that
   cannot actually be executed; test strategy that does not reach the ACs' levels.

## Write

One batch, `agent: "review-draft"`, each finding:

```json
{"type": "finding", "title": "<short>", "fields": {
  "summary": "<one sentence a DRI can act on>",
  "severity": "major",
  "target": ["D-2"],
  "at_rev": "<draft rev you reviewed>",
  "where": "draft.lld §relay",
  "details": "<why, with the evidence and what would fix it>",
  "cites": ["STD-4", "kb:outline/<doc-id>"]}}
```

- `severity`: `blocker` (approving would ship a wrong or unsafe spec), `major` (needs a
  change before approval), `minor`, `nit`. At most 10 findings, at most 3 nits. Blocker and
  major findings are closed by a human; you never write `resolution` on them.
- A finding is an observation, not a fix: never edit the draft, a decision or an AC here,
  never answer a gap, never write a verdict. If something needs a human decision that no
  record asks yet, say so in the finding (`details`) — draft-from-ticket turns it into a gap.
- If the draft is clean, write nothing and say so in your summary.
