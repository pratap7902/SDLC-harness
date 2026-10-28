#!/usr/bin/env python3
"""Load a realistic demo into the dev DB (SQLite var/dev.db by default) so the UI has data.

    make seed                 # wipes the dev DB's rows first
    SEED_KEEP=1 make seed     # keeps them (fails if the demo slugs exist)

It drives the real REST API in-process (TestClient), as the people and the runner would,
over a six-day timeline:

  order-events  — "Order events via an outbox": draft with 3 decisions, a product gap
                  answered, baseline B-1 approved by the DRI; T-1 hits a deviation
                  (G-2: use CDC), the engineer answers, D-4 supersedes D-1 and AC-5 is
                  added `because` D-4 — T-1's drift report: 3 changes, 0 unexplained, PR
                  approved at its sha, deploy guard GO on staging; T-2 has a CLEAN drift
                  report (PR in draft); a learning and a standard in the global scope.
  refund-events — "Refund events": still in DRAFT with an OPEN, overdue product gap.
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.base.models.mysql_base import Base  # noqa: E402
from app.core.database import engine_primary  # noqa: E402
from app.core.utils.time import set_clock  # noqa: E402
from config.database import db_settings  # noqa: E402
from main import app  # noqa: E402

DAY0 = datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0) - timedelta(days=6)
CLIENTS: dict = {}


def at(day: int, hour: int, minute: int = 0) -> None:
    set_clock(DAY0.replace(hour=hour, minute=minute) + timedelta(days=day))


def who(person: str, kind: str = "human") -> TestClient:
    key = (person, kind)
    if key not in CLIENTS:
        CLIENTS[key] = TestClient(app, headers={"X-Actor": person, "X-Actor-Kind": kind})
    return CLIENTS[key]


RUNNER = ("runner-sdk", "agent")


def call(method: str, path: str, person=RUNNER, **kw):
    client = who(*person) if isinstance(person, tuple) else who(person)
    r = client.request(method, path, **kw)
    if r.status_code >= 300:
        raise SystemExit(f"{method} {path} → {r.status_code}: {r.text[:1500]}")
    return r.json()


def write(slug: str, ops: list, agent: str, person=RUNNER, because=None) -> dict:
    return call("POST", f"/api/initiatives/{slug}/records", person, json={"ops": ops, "agent": agent})


# ── order-events ─────────────────────────────────────────────────────────────

ORDER_REQUIREMENT = """# Order events

Downstream services (billing, notifications, analytics) poll the `orders` table every
30 seconds to find state changes. Polling costs ~400 QPS on the primary and adds up to 30s
of latency to customer notifications.

**Ask:** publish an event for every order state change (`CREATED`, `PAID`, `PACKED`,
`SHIPPED`, `DELIVERED`, `CANCELLED`) to the event bus, so consumers can stop polling.

- Events must not be lost when the order write commits.
- Billing must be able to replay a day of events.
- Out of scope: backfilling historical orders.
"""

CATALOG = [
    {"item": "security_review", "phase": "draft", "disposition": "addressed", "note": "Events carry order ids and states only; no PII. Bus topic ACL limited to the consumers listed in the HLD."},
    {"item": "rollback_plan", "phase": "draft", "disposition": "addressed", "note": "Feature flag order_events.enabled; consumers keep polling until the flag has been on for 7 days."},
    {"item": "observability", "phase": "draft", "disposition": "addressed", "note": "Publish lag p99, relay errors, events/s per type; alert on lag > 5s for 5 min."},
    {"item": "data_migration_assessed", "phase": "draft", "disposition": "not_applicable", "note": "No change to existing tables."},
    {"item": "test_strategy", "phase": "draft", "disposition": "addressed", "note": "See draft.test_strategy."},
]


def order_events() -> None:
    slug = "order-events"
    at(0, 9)
    call(
        "POST",
        "/api/initiatives",
        "chandra",
        json={
            "title": "Order events via an outbox",
            "slug": slug,
            "requirement": ORDER_REQUIREMENT,
            "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4211",
            "dri": "chandra",
            "engg": "priya",
            "product": "maya",
            "design": "leo",
            "qa": "sam",
        },
    )

    at(0, 11, 30)
    write(
        slug,
        [
            {  # 0 D-1
                "type": "decision",
                "title": "Publish through a transactional outbox",
                "fields": {
                    "question": "How do order state changes reach the event bus without being lost?",
                    "domain": "engg",
                    "level": "SHOULD",
                    "options": [
                        {"name": "outbox", "consequences": "order_outbox row written in the order transaction; a relay publishes it", "cost_risk": "one new table, a relay process"},
                        {"name": "dual-write", "consequences": "publish after commit from the request handler", "cost_risk": "events lost on crash between commit and publish"},
                        {"name": "cdc", "consequences": "Debezium tails the orders binlog", "cost_risk": "depends on the platform CDC pipeline"},
                    ],
                    "verdict": "Transactional outbox: order_outbox row written in the order transaction, published by a relay",
                    "rationale": "Atomic with the state change, no new infrastructure. Dual-write loses events on crash; CDC was not known to be available.",
                    "decided_by": "runner-sdk/draft-skill",
                    "decided_on": (DAY0).date().isoformat(),
                },
            },
            {  # 1 D-2
                "type": "decision",
                "title": "CloudEvents envelope, partitioned by order_id",
                "fields": {
                    "question": "Which envelope and partition key do order events use?",
                    "domain": "engg",
                    "level": "SHOULD",
                    "options": [
                        {"name": "cloudevents", "consequences": "consumers reuse their CloudEvents parser", "cost_risk": "low"},
                        {"name": "custom-json", "consequences": "one more schema to maintain", "cost_risk": "medium"},
                    ],
                    "verdict": "CloudEvents 1.0 JSON; partition key order_id",
                    "rationale": "Billing, notifications and analytics already parse CloudEvents.",
                    "decided_by": "runner-sdk/draft-skill",
                    "decided_on": DAY0.date().isoformat(),
                },
            },
            {  # 2 D-3
                "type": "decision",
                "title": "Keep 7 days of events for replay",
                "fields": {
                    "question": "How long can a consumer replay events?",
                    "domain": "product",
                    "level": "SHOULD",
                    "verdict": "7 days of retention on the order-events topic",
                    "rationale": "Billing's month-end reconciliation re-reads at most a week.",
                    "decided_by": "runner-sdk/draft-skill",
                    "decided_on": DAY0.date().isoformat(),
                    "provisional": "yes",
                },
            },
            {  # 3 G-1
                "type": "gap",
                "title": "Do consumers need per-order ordering?",
                "fields": {
                    "question": "Must events for one order arrive in the order they happened?",
                    "kind": "unknown",
                    "domain": "product",
                    "level": "MUST",
                    "asked_by": "runner-sdk/draft-skill",
                    "why_now": "It decides the partition key in D-2.",
                    "context": "Billing replays PAID and CANCELLED to compute revenue. If CANCELLED for order 81723 arrives before PAID, billing counts revenue that was refunded.",
                    "options": [
                        {"key": "per-order", "label": "Yes — per order", "consequence": "partition by order_id; per-order ordering guaranteed"},
                        {"key": "none", "label": "No ordering needed", "consequence": "round-robin partitions; consumers sort by timestamp"},
                    ],
                    "recommendation": "per-order",
                    "recommendation_why": "Billing is order-sensitive; per-order partitioning costs nothing extra.",
                    "blocks": ["#1"],
                },
            },
            {"type": "acceptance_criterion", "fields": {"text": "Given an order state change, when the order transaction commits, then exactly one event for it is published", "level": "integration", "source": ["#0"]}},  # 4 AC-1
            {"type": "acceptance_criterion", "fields": {"text": "Given the relay is down for 10 minutes, when it restarts, then every pending event is published with no loss", "level": "integration", "source": ["#0"]}},  # 5 AC-2
            {"type": "acceptance_criterion", "fields": {"text": "Given two state changes of one order, when published, then they carry partition key order_id and arrive in commit order", "level": "integration", "source": ["#1"]}},  # 6 AC-3
            {"type": "acceptance_criterion", "fields": {"text": "Given an event older than 6 days, when billing replays the topic, then the event is still readable", "level": "e2e", "source": ["#2"]}},  # 7 AC-4
            {  # 8 draft
                "ref": "draft",
                "fields": {
                    "summary": "Publish order state changes as CloudEvents (D-2) through a transactional outbox (D-1), kept 7 days for replay (D-3).",
                    "problem": "Consumers poll `orders` every 30s (~400 QPS on the primary, up to 30s notification latency). Done = every state change is on the bus within 5s, none lost, replayable for 7 days.",
                    "hld": "Order writes insert an `order_outbox` row in the same transaction (D-1). A relay publishes outbox rows as CloudEvents partitioned by `order_id` (D-2) to `order-events`, retained 7 days (D-3).\n\n```mermaid\nflowchart LR\n  API --> orders[(orders)] & outbox[(order_outbox)]\n  outbox --> relay --> bus[[order-events]]\n```",
                    "lld": "- `order_outbox(id bigint pk, order_id, type, payload json, created_at, published_at null)`\n- Relay: `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED`, publish, set `published_at`.\n- Rows older than 7 days are deleted nightly.",
                    "scope_in": ["All six order state transitions", "Relay with lag metrics and alert", "Consumer contract docs"],
                    "scope_out": ["Backfill of historical orders", "Migrating consumers off polling (each team owns theirs)"],
                    "test_strategy": "Integration tests against MySQL + a local Kafka for AC-1..AC-3 (kill the relay mid-batch for AC-2). AC-4 runs in staging against the real topic retention. No manual ACs.",
                    "decisions": ["#0", "#1", "#2"],
                    "criteria": ["#4", "#5", "#6", "#7"],
                    "submitted_rev": "1",
                },
            },
            {"ref": "initiative", "fields": {"catalog": CATALOG, "summary": "Replace order-table polling with order events (CloudEvents via an outbox)."}},
        ],
        "draft-skill",
    )

    at(1, 10, 15)
    call("POST", f"/api/initiatives/{slug}/gaps/G-1/answer", "maya", json={"choice": "per-order", "answer": "Yes — per order. Billing double-counts otherwise; analytics does not care."})
    at(1, 11, 0)
    write(slug, [{"ref": "D-2", "fields": {"rationale": "Billing, notifications and analytics already parse CloudEvents. G-1: billing needs per-order ordering, so order_id is the partition key."}, "note": "re-read against G-1: holds, rationale updated"}], "draft-skill")
    at(1, 15, 40)
    call("POST", f"/api/initiatives/{slug}/approvals", "chandra", json={"target": "draft", "role": "dri", "note": "Good scope. Ship behind the flag."})

    at(2, 9, 20)
    write(
        slug,
        [
            {
                "type": "task",
                "title": "Outbox table and relay",
                "fields": {
                    "goal": "Write order_outbox rows in the order transaction and relay them to order-events",
                    "repo": "acme/orders-service",
                    "template": "python-service-v3",
                    "implements": ["D-1", "D-2"],
                    "covers": ["AC-1", "AC-2"],
                    "rollback": "Turn off order_events.enabled; the relay stops, the outbox drains on re-enable.",
                    "tracker_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4212",
                },
            },
            {
                "type": "task",
                "title": "Envelope, partitioning and retention",
                "fields": {
                    "goal": "CloudEvents envelope with order_id partition key; 7-day topic retention",
                    "repo": "acme/event-contracts",
                    "template": "contracts-lib",
                    "implements": ["D-2", "D-3"],
                    "covers": ["AC-3", "AC-4"],
                    "rollback": "Revert the contract version; the topic config is idempotent.",
                },
            },
        ],
        "plan-skill",
    )

    at(3, 10, 5)
    call("POST", "/api/leases/claim", RUNNER, json={"item_key": f"task:{slug}:T-1", "ttl_min": 240})
    write(
        slug,
        [
            {
                "type": "gap",
                "title": "Use the platform CDC pipeline instead of an outbox?",
                "fields": {
                    "question": "The orders DB already streams its binlog to Kafka via Debezium (platform team). Use CDC instead of the outbox table (D-1)?",
                    "kind": "deviation",
                    "domain": "engg",
                    "level": "MUST",
                    "asked_by": "runner-sdk/implement-task",
                    "why_now": "Implementing T-1: the outbox needs a migration on a table the orders team does not want to own.",
                    "context": "Platform runs Debezium on orders-primary (connector `orders-cdc`, lag p99 1.2s). An outbox adds `order_outbox`, a relay process, and a nightly cleanup job.",
                    "options": [
                        {"key": "cdc", "label": "Switch to CDC", "consequence": "supersede D-1; add an AC for CDC lag; no new table"},
                        {"key": "outbox", "label": "Keep the outbox", "consequence": "no spec change; orders team owns the table"},
                    ],
                    "recommendation": "cdc",
                    "recommendation_why": "Same delivery guarantee, no new table, the pipeline already exists.",
                    "blocks": ["D-1", "T-1"],
                    "proposed_change": "D-1 verdict: outbox → CDC via Debezium on orders-primary. Add AC: given CDC lag > 5s for 5 min, the lag alert fires. T-1 implements the new decision.",
                },
            }
        ],
        "implement-task",
    )
    at(3, 13, 30)
    call("POST", f"/api/initiatives/{slug}/gaps/G-2/answer", "priya", json={"choice": "cdc", "answer": "Switch to CDC — the outbox adds a table we don't own, and platform guarantees the connector. Keep the flag."})
    at(3, 14, 10)
    write(
        slug,
        [
            {
                "type": "decision",
                "title": "Publish order events via platform CDC",
                "fields": {
                    "question": "How do order state changes reach the event bus without being lost?",
                    "domain": "engg",
                    "level": "SHOULD",
                    "verdict": "CDC: Debezium on orders-primary; a transformer maps row changes to CloudEvents",
                    "rationale": "G-2: platform already runs Debezium with 1.2s p99 lag; no new table or relay to own.",
                    "decided_by": "runner-sdk/implement-task",
                    "decided_on": (DAY0 + timedelta(days=3)).date().isoformat(),
                    "supersedes": ["D-1"],
                    "because": ["G-2"],
                },
            },
            {"type": "acceptance_criterion", "fields": {"text": "Given CDC lag above 5s for 5 minutes, when the alert rule evaluates, then the order-events lag alert pages the on-call", "level": "integration", "source": ["#0"], "because": ["#0"]}},
            {"ref": "T-1", "title": "CDC transformer to order-events", "fields": {"goal": "Map Debezium order row changes to CloudEvents on order-events", "implements": ["D-2", "#0"], "covers": ["AC-1", "AC-2", "#1"]}, "note": "follows D-4"},
            {"ref": "G-2", "fields": {"resolution": "D-4 supersedes D-1; AC-5 added for CDC lag; T-1 re-scoped."}},
        ],
        "implement-task",
    )

    at(4, 16, 45)
    sha = "9f3c2e1a7b4d"
    write(slug, [{"ref": "T-1", "fields": {"pr_state": "open", "pr_url": "https://github.com/acme/orders-service/pull/482", "pr_sha": sha, "ci_attempts": "1", "review_rounds": "1"}}], "implement-task")
    write(
        slug,
        [
            {
                "type": "test_run",
                "title": "orders-service integration suite @ 9f3c2e1",
                "fields": {
                    "summary": "CDC transformer integration suite (MySQL + Kafka + Debezium in docker)",
                    "level": "integration",
                    "result": "GREEN",
                    "at_sha": sha,
                    "run_url": "https://github.com/acme/orders-service/actions/runs/1180042",
                    "environment": "ci",
                    "task": ["T-1"],
                    "run_on": (DAY0 + timedelta(days=4, hours=17)).isoformat(timespec="minutes"),
                    "covers": [
                        {"ac": "AC-1", "result": "GREEN", "test_id": "test_one_event_per_commit", "evidence": "48/48 transitions"},
                        {"ac": "AC-2", "result": "GREEN", "test_id": "test_connector_restart_no_loss", "evidence": "0 lost of 10k"},
                        {"ac": "AC-5", "result": "GREEN", "test_id": "test_lag_alert_fires", "evidence": "alert at 5m02s"},
                    ],
                },
            }
        ],
        "write-tests",
    )
    call("DELETE", f"/api/leases/task:{slug}:T-1", RUNNER)
    at(5, 10, 30)
    call("POST", f"/api/initiatives/{slug}/approvals", "priya", json={"target": "T-1", "role": "engg", "at_sha": sha, "note": "Drift is the CDC switch I asked for; tests cover the lag alert."})
    at(5, 11, 0)
    call("POST", "/api/deploy-guard", ("github-actions", "system"), json={"initiative": slug, "task": "T-1", "sha": sha, "environment": "staging"})

    at(5, 15, 0)
    write(slug, [{"ref": "T-2", "fields": {"pr_state": "draft", "pr_url": "https://github.com/acme/event-contracts/pull/91", "pr_sha": "c41d09e2"}}], "implement-task")


def global_scope() -> None:
    at(5, 16, 0)
    call(
        "POST",
        "/api/global/records",
        "chandra",
        json={
            "ops": [
                {"type": "standard", "title": "Events carry no PII", "fields": {"rule": "Event payloads carry ids and states only — never names, emails, addresses or payment data.", "level": "MUST", "applies_to": "acme/*", "owner": "security", "state": "enforced"}},
            ]
        },
    )
    call(
        "POST",
        "/api/global/records",
        RUNNER,
        json={
            "agent": "retro-skill",
            "ops": [
                {"type": "learning", "fields": {"text": "Check for an existing platform CDC connector before designing an outbox.", "applies_to": "event publishing", "source": "order-events:G-2", "provenance": "order-events T-1 deviation, answered by priya"}},
            ],
        },
    )


# ── refund-events ────────────────────────────────────────────────────────────


def refund_events() -> None:
    slug = "refund-events"
    at(4, 9, 0)
    call(
        "POST",
        "/api/initiatives",
        "chandra",
        json={
            "title": "Refund events",
            "slug": slug,
            "requirement": "# Refund events\nFinance needs an event per refund (full and partial) to reconcile payouts daily. Today they export CSVs from the admin.\n\n- One event per refund state change.\n- Must reconcile to the payment provider's report to the cent.",
            "work_item_url": "https://dev.azure.com/acme/commerce/_workitems/edit/4307",
            "dri": "chandra",
            "engg": "omar",
            "product": "maya",
        },
    )
    at(4, 11, 30)
    write(
        slug,
        [
            {
                "type": "decision",
                "title": "Reuse the order-events pipeline",
                "fields": {
                    "question": "Do refund events get their own pipeline?",
                    "domain": "engg",
                    "level": "SHOULD",
                    "verdict": "Reuse the CDC pipeline from order-events (D-4 there) on the refunds table",
                    "rationale": "Same delivery guarantees; one pipeline to operate.",
                    "decided_by": "runner-sdk/draft-skill",
                    "decided_on": (DAY0 + timedelta(days=4)).date().isoformat(),
                },
            },
            {
                "type": "decision",
                "title": "Partial refund granularity",
                "fields": {
                    "question": "Is a partial refund one event, or one event per refunded line?",
                    "domain": "product",
                    "level": "MUST",
                    "options": [
                        {"name": "per-refund", "consequences": "one event with a lines[] array", "cost_risk": "finance sums lines"},
                        {"name": "per-line", "consequences": "one event per refunded line", "cost_risk": "more events; simpler sums"},
                    ],
                },
            },
            {
                "type": "gap",
                "title": "Partial refunds: one event or one per line?",
                "fields": {
                    "question": "When a customer is refunded 2 of 5 items, does finance want one event or one per refunded line?",
                    "kind": "unknown",
                    "domain": "product",
                    "asked_by": "runner-sdk/draft-skill",
                    "why_now": "D-2 (a MUST decision) cannot be ruled without it; the schema depends on it.",
                    "context": "Order 90311: 5 items, items 2 and 4 refunded (€18.40 + €6.10). Per-refund: one event, lines[2]. Per-line: two events. The provider report lists one row per refund, not per line.",
                    "options": [
                        {"key": "per-refund", "label": "One event per refund", "consequence": "matches the provider report row for row"},
                        {"key": "per-line", "label": "One event per line", "consequence": "finance aggregates lines to match the report"},
                    ],
                    "recommendation": "per-refund",
                    "recommendation_why": "Reconciliation is against the provider report, which is per refund.",
                    "blocks": ["#1"],
                },
            },
            {"type": "acceptance_criterion", "fields": {"text": "Given a refund reaches SETTLED, when CDC runs, then one refund event with the amount in minor units is published", "level": "integration", "source": ["#0"]}},
            {
                "ref": "draft",
                "fields": {
                    "problem": "Finance reconciles refunds from CSV exports. Done = every refund state change is an event that reconciles to the provider report.",
                    "hld": "CDC on `refunds` (D-1) through the order-events transformer; granularity per D-2 (open).",
                    "test_strategy": "Integration tests with the provider sandbox; a reconciliation test over a fixed day of refunds.",
                    "decisions": ["#0", "#1"],
                    "criteria": ["#3"],
                },
            },
        ],
        "draft-skill",
    )


def main() -> int:
    url = db_settings.url()
    if url.startswith("sqlite"):
        Path("var").mkdir(exist_ok=True)
    Base.metadata.create_all(engine_primary)  # no-op once `make migrate` has run
    if not os.environ.get("SEED_KEEP"):
        with engine_primary.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
    order_events()
    global_scope()
    refund_events()
    set_clock(None)
    print(f"seeded {url}")
    print("  order-events  — baseline B-1, G-2 answered mid-build, D-4 supersedes D-1, AC-5 added;")
    print("                  T-1 drift explained + approved (deploy guard GO), T-2 drift CLEAN")
    print("  refund-events — DRAFT, G-1 open and overdue in maya's inbox")
    print("  people: chandra (dri) · priya, omar (engg) · maya (product) · leo (design) · sam (qa)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
