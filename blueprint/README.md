# blueprint/ — what a record may be, and how the lifecycle works

Engineer-edited YAML, loaded and linted at service start and by `make check`. The
database holds generic records; this directory defines their types, fields and rules.

```
vocab.yaml       vocabularies (derived-status sets and field enums), `open` statuses
                 (worklist membership), `answers`, pill colours for the UI
objects.yaml     record types: ref scheme, status vocabulary, fields, rules, actor rules
lifecycle.yaml   phases, the derived-status rule of every type, per-phase catalogs,
                 gates (GATE_DRAFT · GATE_PR · GATE_VALIDATED), deploy_guard, routing, SLAs
```

## objects.yaml conventions

- `ref: {prefix: D}` — minted per initiative (`D-1`, `D-2`…); `{singleton: draft}` — one per
  initiative, ref is the name.
- `status: decision_status` — the vocabulary the DERIVED status comes from. Statuses are
  never written; `lifecycle.yaml status_rules` names the rule.
- Field types: `string` (one line), `markdown`, `narrative` (fingerprinted summary),
  `bullets`, `rows` (`columns`, `row_key`, `column_vocab`), `enum` (`vocab`), `date`,
  `refs` (`targets: [decision, …, external]`, `link_kind`), `json`.
- `material: true` — a change propagates to `propagates_to` types (the review queue) and,
  on spec types, is drift.
- `actor: human` — only a human may write the field; `actor_rules` make it conditional
  (`when: {level: [MUST]}, human: [verdict]`).
- `post_baseline_cause: true` — after a baseline, an agent's material edit needs `because`.
- `rules: [{when: {status: [DECIDED]}, require: [...]}]` — required fields by status or by
  field value.
- `scope: global` — lives in initiative 0 (`_global`): standards, learnings.

## lifecycle.yaml

`status_rules` and `gates.*.all_of` name rules implemented in
`app/initiatives/services/status_rules.py` and `gate_rules.py`. `make check` refuses a rule
with no code and code with no rule. Catalog items marked `derived: true` are answered by the
service; the rest are rows of `initiative.catalog` with a `disposition`.
