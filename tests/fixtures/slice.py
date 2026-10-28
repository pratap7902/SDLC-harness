"""The vertical slice's content (an order-events outbox feature), shared by tests."""

SLUG = "order-events"

CATALOG = [
    {"item": "security_review", "phase": "draft", "disposition": "addressed", "note": "no new PII; events carry order ids only"},
    {"item": "rollback_plan", "phase": "draft", "disposition": "addressed", "note": "feature flag order_events.enabled"},
    {"item": "observability", "phase": "draft", "disposition": "addressed", "note": "lag metric + alert"},
    {"item": "data_migration_assessed", "phase": "draft", "disposition": "not_applicable", "note": "new table only"},
    {"item": "test_strategy", "phase": "draft", "disposition": "addressed", "note": "see draft.test_strategy"},
]


def draft_batch() -> list:
    """D-1, D-2, G-1 (blocks D-2), AC-1..3, the draft, the catalog — one atomic batch."""
    return [
        {  # 0 → D-1
            "type": "decision",
            "title": "How order events leave the service",
            "fields": {
                "question": "How do order state changes reach the event bus?",
                "domain": "engg",
                "level": "SHOULD",
                "options": [
                    {"name": "outbox", "consequences": "one extra table, exactly-once with the order write", "cost_risk": "low"},
                    {"name": "cdc", "consequences": "Debezium on the orders binlog", "cost_risk": "new infra"},
                ],
                "verdict": "Transactional outbox table written in the order transaction, relayed by a poller",
                "rationale": "Keeps the event atomic with the state change; no new infra.",
                "decided_by": "runner-sdk/draft-skill",
                "decided_on": "2026-10-29",
            },
        },
        {  # 1 → D-2
            "type": "decision",
            "title": "Event envelope",
            "fields": {
                "question": "Which envelope do order events use?",
                "domain": "engg",
                "level": "SHOULD",
                "verdict": "CloudEvents 1.0 JSON with order_id as the partition key",
                "rationale": "Consumers already parse CloudEvents.",
                "decided_by": "runner-sdk/draft-skill",
                "decided_on": "2026-10-29",
            },
        },
        {  # 2 → G-1
            "type": "gap",
            "title": "Do consumers need per-order ordering?",
            "fields": {
                "question": "Do downstream consumers need events for one order in order?",
                "kind": "unknown",
                "domain": "product",
                "asked_by": "runner-sdk/draft-skill",
                "why_now": "Decides the partition key in D-2",
                "context": "Billing replays order events; if PAID can arrive before CREATED it double-counts.",
                "options": [
                    {"key": "yes", "label": "Yes, per order", "consequence": "partition by order_id"},
                    {"key": "no", "label": "No ordering needed", "consequence": "round-robin partitions"},
                ],
                "recommendation": "yes",
                "recommendation_why": "Billing is order-sensitive.",
                "blocks": ["#1"],
            },
        },
        {  # 3 → AC-1
            "type": "acceptance_criterion",
            "fields": {"text": "Given an order update, when it commits, then exactly one outbox row is written in the same transaction", "level": "integration", "source": ["#0"]},
        },
        {  # 4 → AC-2
            "type": "acceptance_criterion",
            "fields": {"text": "Given an outbox row, when the relay runs, then the event is published within 5s", "level": "integration", "source": ["#0"]},
        },
        {  # 5 → AC-3
            "type": "acceptance_criterion",
            "fields": {"text": "Given two updates to one order, when published, then they share the partition key order_id", "level": "unit", "source": ["#1"]},
        },
        {  # 6 → draft
            "ref": "draft",
            "fields": {
                "problem": "Downstream services poll the orders table; emit events instead.",
                "hld": "Write events through an outbox (D-1) in CloudEvents (D-2).",
                "lld": "Table order_outbox(id, order_id, type, payload, created_at); relay polls every 1s.",
                "scope_in": ["order state changes"],
                "scope_out": ["historical backfill"],
                "test_strategy": "Integration tests against MySQL for AC-1/AC-2; unit test for AC-3.",
                "decisions": ["#0", "#1"],
                "criteria": ["#3", "#4", "#5"],
                "submitted_rev": "1",
            },
        },
        {"ref": "initiative", "fields": {"catalog": CATALOG}},  # 7
    ]


def task_op() -> dict:
    return {
        "type": "task",
        "title": "Outbox table and relay",
        "fields": {
            "goal": "Write order events through the outbox and relay them",
            "repo": "acme/orders",
            "template": "python-service",
            "implements": ["D-1", "D-2"],
            "covers": ["AC-1", "AC-2", "AC-3"],
            "rollback": "Disable order_events.enabled",
        },
    }


def deviation_gap() -> dict:
    return {
        "type": "gap",
        "title": "Use CDC instead of the outbox?",
        "fields": {
            "question": "The orders DB already streams its binlog to Kafka via Debezium — use CDC instead of the outbox (D-1)?",
            "kind": "deviation",
            "domain": "engg",
            "asked_by": "runner-sdk/implement-task",
            "why_now": "Implementing T-1 found the platform CDC pipeline",
            "context": "The outbox adds a table the orders team does not own; CDC is already running.",
            "options": [
                {"key": "cdc", "label": "Switch to CDC", "consequence": "supersede D-1; add a lag AC"},
                {"key": "outbox", "label": "Keep the outbox", "consequence": "no change"},
            ],
            "recommendation": "cdc",
            "recommendation_why": "No new table, infra already exists.",
            "blocks": ["D-1", "T-1"],
            "proposed_change": "D-1 verdict: outbox → CDC via Debezium; add AC: CDC lag alert.",
        },
    }


def supersede_batch() -> list:
    return [
        {  # 0 → D-3
            "type": "decision",
            "title": "Order events via CDC",
            "fields": {
                "question": "How do order state changes reach the event bus?",
                "domain": "engg",
                "level": "SHOULD",
                "verdict": "CDC via Debezium on the orders binlog",
                "rationale": "G-2: the platform already runs Debezium; the outbox adds a table we don't own.",
                "decided_by": "runner-sdk/implement-task",
                "decided_on": "2026-10-31",
                "supersedes": ["D-1"],
                "because": ["G-2"],
            },
        },
        {  # 1 → AC-4
            "type": "acceptance_criterion",
            "fields": {
                "text": "Given a row update, when CDC lags more than 5s, then the lag alert fires",
                "level": "integration",
                "source": ["#0"],
                "because": ["#0"],
            },
        },
        {"ref": "T-1", "fields": {"implements": ["D-2", "#0"], "covers": ["AC-1", "AC-2", "AC-3", "#1"]}, "note": "follows D-3"},
        {"ref": "G-2", "fields": {"resolution": "D-3 supersedes D-1; AC-4 added for CDC lag"}},
    ]


def to_baseline(api) -> None:
    """Start the feature, write the draft, answer G-1, revise D-2, DRI approves → B-1."""
    api.start()
    api.write(SLUG, draft_batch())
    api.answer(SLUG, "G-1", choice="yes", person="maya")
    api.write(SLUG, [{"ref": "D-2", "fields": {"rationale": "G-1: billing needs per-order ordering."}, "note": "per G-1"}])
    api.approve(SLUG, "draft", "dri", "chandra")


def to_task(api) -> None:
    to_baseline(api)
    api.write(SLUG, [task_op()])


def pr_open(api, sha="abc123", acs=("AC-1", "AC-2", "AC-3")) -> None:
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_state": "open", "pr_url": "https://github.com/acme/orders/pull/77", "pr_sha": sha}}])
    api.write(
        SLUG,
        [
            {
                "type": "test_run",
                "fields": {
                    "summary": "suite",
                    "level": "integration",
                    "result": "GREEN",
                    "at_sha": sha,
                    "run_url": "https://ci.acme.dev/runs/1",
                    "run_on": "2026-10-31T15:00",
                    "task": ["T-1"],
                    "covers": [{"ac": ac, "result": "GREEN"} for ac in acs],
                },
            }
        ],
    )
