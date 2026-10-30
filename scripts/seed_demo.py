#!/usr/bin/env python3
"""Load the prototype's demo story into the dev DB (SQLite var/dev.db by default).

    make seed                 # wipes the dev DB's rows first
    SEED_KEEP=1 make seed     # keeps them (fails if the demo slugs exist)

Everything goes through the real REST API in-process (TestClient), as the people and the
runner would, on a timeline that ends now — so statuses, gates, drift, routing and the
review queue are derived, not written. People: arjun (engg), priya (DRI), meera (product),
sam (QA), nikhil (engg; DRI of payouts-v2), rahul (DRI).

  order-events       BUILD. B-1 approved by priya (D-1 outbox, a MUST she ruled; D-2
                     provisional; AC-1..AC-7; G-1 answered before approval). T-3 approved at
                     a41c09e; T-1 paused on an OPEN deviation G-2 routed to arjun (separate
                     schema / CDC, recommended / dual-write); T-2, T-4 wait on dependencies.
  menu-sync-retries  DRAFT rev 2, product gap G-1 open for meera (blocks D-2 and the draft).
  loyalty-expiry     BUILD, draft REOPENED: AC-4 was changed after approval citing finding
                     F-1, and nikhil rejected F-1 — the change is now unexplained.
  payouts-v2         BUILD. STD-3 changed, so D-2 (round per line item) is up for review
                     for arjun; T-3's PR waits on arjun's approval; T-4 leased by an agent.
  store-hours-api    VALIDATE: every task merged and green, manual AC-10 waits on sam.
  webhook-signing    DRAFT: the drafting agent holds the lease, no draft yet.
  inventory-sync-v3  SHIP: D-3 superseded D-2 because G-1 (meera); validated and deployed.
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

NOW = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
CLIENTS: dict = {}
ADO = "https://dev.azure.com/example/commerce/_workitems/edit/"


def at(days: float = 0, hours: float = 0, minutes: float = 0) -> datetime:
    """Set the service clock to `days/hours/minutes` ago."""
    t = NOW - timedelta(days=days, hours=hours, minutes=minutes)
    set_clock(t)
    return t


def day(days: float = 0) -> str:
    return (NOW - timedelta(days=days)).date().isoformat()


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
        raise SystemExit(f"{method} {path} → {r.status_code}: {r.text[:2000]}")
    return r.json()


def write(slug: str, ops: list, agent: str, person=RUNNER) -> dict:
    return call("POST", f"{P(slug)}/records", person, json={"ops": ops, "agent": agent})


def human_write(slug: str, ops: list, person: str) -> dict:
    return call("POST", f"{P(slug)}/records", person, json={"ops": ops})


IDS: dict = {}


def P(slug: str) -> str:
    """REST addresses an initiative by id; the seed names them by slug."""
    return f"/api/initiatives/{IDS[slug]}"


def start(slug: str, title: str, requirement: str, by: str, work_item: str | None = None, **people) -> None:
    body = {"title": title, "slug": slug, "requirement": requirement, **people}
    if work_item:
        body["work_item_url"] = ADO + work_item
    IDS[slug] = call("POST", "/api/initiatives", by, json=body)["initiative"]["id"]


def answer(slug: str, ref: str, person: str, choice: str | None, text: str = "") -> dict:
    body = {"answer": text}
    if choice:
        body["choice"] = choice
    return call("POST", f"{P(slug)}/gaps/{ref}/answer", person, json=body)


def rule(slug: str, ref: str, person: str, verdict: str, rationale: str) -> dict:
    return call("POST", f"{P(slug)}/decisions/{ref}/rule", person, json={"verdict": verdict, "rationale": rationale})


def approve(slug: str, target: str, role: str, person: str, at_sha: str | None = None, note: str | None = None) -> dict:
    body = {"target": target, "role": role}
    if at_sha:
        body["at_sha"] = at_sha
    if note:
        body["note"] = note
    return call("POST", f"{P(slug)}/approvals", person, json=body)


def claim(key: str, agent: str, ttl_min: int = 240) -> None:
    call("POST", "/api/leases/claim", (f"runner-sdk/{agent}", "agent"), json={"item_key": key, "ttl_min": ttl_min})


def ac(text: str, source: list, level: str = "integration", manual: bool = False, **extra) -> dict:
    fields = {"text": text, "level": level, "source": source, **extra}
    if manual:
        fields["manual"] = "yes"
    return {"type": "acceptance_criterion", "fields": fields}


def decision(title: str, question: str, level: str, domain: str = "engg", verdict: str | None = None, rationale: str = "", options=None, provisional=False, by="runner-sdk/draft-skill", on=None, **extra) -> dict:
    fields = {"question": question, "domain": domain, "level": level, **extra}
    if options:
        fields["options"] = [{"name": n, "consequences": c, "cost_risk": r} for n, c, r in options]
    if verdict:
        fields.update({"verdict": verdict, "rationale": rationale, "decided_by": by, "decided_on": on or day(0)})
    if provisional:
        fields["provisional"] = "yes"
    return {"type": "decision", "title": title, "fields": fields}


def task(title: str, goal: str, repo: str, implements: list, covers: list, template="python-service-v3", depends_on=None, rollback="Revert the PR; the change is behind a flag.") -> dict:
    fields = {"goal": goal, "repo": repo, "template": template, "implements": implements, "covers": covers, "rollback": rollback}
    if depends_on:
        fields["depends_on"] = depends_on
    return {"type": "task", "title": title, "fields": fields}


def catalog(**notes) -> dict:
    items = []
    for item in ("security_review", "rollback_plan", "observability", "data_migration_assessed", "test_strategy"):
        disposition, note = notes.get(item, ("addressed", ""))
        items.append({"item": item, "phase": "draft", "disposition": disposition, "note": note})
    return {"ref": "initiative", "fields": {"catalog": items}}


def pr(slug: str, ref: str, number: int, repo: str, sha: str, state: str = "open", agent="implement-task", **extra) -> None:
    write(slug, [{"ref": ref, "fields": {"pr_state": state, "pr_url": f"https://github.com/example/{repo}/pull/{number}", "pr_sha": sha, **extra}}], agent)


def tests(slug: str, ref: str, sha: str, rows: list, summary: str, level="integration") -> None:
    """A green run at `sha` covering `rows` = [(ac, test_id), …]."""
    write(
        slug,
        [
            {
                "type": "test_run",
                "title": f"{summary} @ {sha[:7]}",
                "fields": {
                    "summary": summary,
                    "level": level,
                    "result": "GREEN",
                    "at_sha": sha,
                    "run_url": f"https://ci.example.com/runs/{abs(hash((slug, ref, sha))) % 100000}",
                    "environment": "ci",
                    "task": [ref],
                    "run_on": (NOW - timedelta(hours=1)).isoformat(timespec="minutes"),
                    "covers": [{"ac": a, "result": "GREEN", "test_id": t} for a, t in rows],
                },
            }
        ],
        "write-tests",
    )


def ship(slug: str, ref: str, number: int, repo: str, sha: str, rows: list, engg: str, summary: str) -> None:
    """PR open → green tests → engg approval at the head → merged."""
    pr(slug, ref, number, repo, sha)
    tests(slug, ref, sha, rows, summary)
    approve(slug, ref, "engg", engg, at_sha=sha)
    write(slug, [{"ref": ref, "fields": {"pr_state": "merged"}}], "implement-task")
    settle_reviews(slug, "R-", "Merged at the tested head; the run still holds.")


def settle_reviews(slug: str, prefix: str, note: str, agent: str = "implement-task") -> None:
    """The agent re-reads the items on `prefix…` targets and says they hold (advice, written
    with reviewed: true); the person each item is routed to upholds it — upholding is human."""
    items = [i for i in call("GET", f"{P(slug)}/reviews") if i["target"].startswith(prefix)]
    targets = sorted({i["target"] for i in items})
    if targets:
        write(slug, [{"ref": t, "reviewed": True, "note": note} for t in targets], agent)
    for item in items:
        person = item["route_to"] or "priya"
        call("POST", f"{P(slug)}/reviews/{item['id']}/resolve", person, json={"resolution": "upheld", "note": f"Agreed: {note}"})


# ── global scope ────────────────────────────────────────────────────────────


def global_scope() -> None:
    at(days=30)
    call(
        "POST",
        "/api/global/records",
        "priya",
        json={
            "ops": [
                {"type": "standard", "title": "Idempotent delivery", "fields": {"rule": "Events reach the broker exactly once per state change: no dual-writes, every consumer dedupes by event_id.", "level": "MUST", "applies_to": "example/*", "owner": "platform", "state": "enforced"}},
                {"type": "standard", "title": "Retries with backoff and jitter", "fields": {"rule": "Outbound calls retry with exponential backoff and jitter, within a retry budget.", "level": "SHOULD", "applies_to": "example/*", "owner": "platform", "state": "active"}},
                {"type": "standard", "title": "Settlement rounding", "fields": {"rule": "Money is rounded per line item, half-even, in minor units.", "level": "SHOULD", "applies_to": "example/payouts-*", "owner": "finance", "state": "active"}},
            ]
        },
    )
    call(
        "POST",
        "/api/global/records",
        RUNNER,
        json={"agent": "retro-skill", "ops": [{"type": "learning", "fields": {"text": "Check for an existing platform CDC connector before designing an outbox.", "applies_to": "event publishing", "source": "inventory-sync-v3:G-1", "provenance": "inventory-sync-v3 delta sync deviation, answered by meera"}}]},
    )


# ── order-events: the step-8 moment ──────────────────────────────────────────

ORDER_REQ = """# Order events for downstream consumers

Notifications-svc polls the orders database every minute to find new and cancelled orders.
Emails go out late, and the polling query is the orders DB's top load.

**Done:** consumers receive `order.created` and `order.cancelled` within 5 seconds, exactly
once, and polling is switched off.
"""


def order_events() -> None:
    slug = "order-events"
    at(days=6)
    start(slug, "Order events for downstream consumers", ORDER_REQ, "priya", "4821", dri="priya", engg="arjun", product="meera", qa="sam")
    at(days=6, hours=-2)
    write(
        slug,
        [
            decision(  # 0 D-1 — MUST: only a person may rule it
                "Transactional outbox",
                "How do order events reach consumers?",
                "MUST",
                options=[
                    ("outbox", "Extra table and relay; exactly-once to the broker", "one table, one relay process"),
                    ("dual-write", "Simple; loses events on partial failure (breaks STD-1)", "lost events"),
                    ("CDC", "No app change; adds a Debezium dependency", "connector to run"),
                ],
            ),
            decision(  # 1 D-2 — provisional SHOULD
                "Event envelope with schema_version",
                "How are event schemas versioned?",
                "SHOULD",
                verdict="Envelope with schema_version, additive changes only",
                rationale="Follows the default menu-sync chose (D-55 there). A human answer later would supersede it.",
                provisional=True,
                on=day(6),
            ),
            {  # 2 G-1
                "type": "gap",
                "title": "Do cancelled orders emit events?",
                "fields": {
                    "question": "Do cancelled orders emit events?",
                    "kind": "unknown",
                    "domain": "product",
                    "level": "MUST",
                    "asked_by": "runner-sdk/draft-skill",
                    "why_now": "The event list in the HLD depends on it.",
                    "context": "The requirement names `order.created` and `order.cancelled`, but refunds after cancellation are a separate flow.",
                    "options": [
                        {"key": "yes", "label": "Yes, refunds out of scope", "consequence": "order.cancelled published; refunds stay out"},
                        {"key": "no", "label": "No, created only", "consequence": "notifications keeps polling for cancellations"},
                    ],
                    "recommendation": "yes",
                    "recommendation_why": "The requirement names order.cancelled.",
                    "blocks": ["draft"],
                },
            },
            ac("Given an order commits, when the relay runs, then order.created is published once", ["#0"]),  # 3 AC-1
            ac("Given an order write, then its event row is written in the same transaction", ["#0"], level="unit"),  # 4 AC-2
            ac("Given the broker is down, when it recovers, then every event arrives with none duplicated", ["#0"]),  # 5 AC-3
            ac("Only the notifications-svc role can read orders.events", ["#0"]),  # 6 AC-4
            ac("Given a duplicate event_id, then the consumer ignores it", ["#1"], level="unit"),  # 7 AC-5
            ac("The ops dashboard shows publish lag per topic", ["initiative"], level="e2e", manual=True),  # 8 AC-6
            {  # 9 draft rev 1
                "ref": "draft",
                "fields": {
                    "summary": "Order changes and an event row commit together (D-1); a relay publishes versioned envelopes (D-2) to orders.events.",
                    "problem": "Notifications-svc polls the orders database every minute to find new and cancelled orders. Emails go out late, and the polling query is the orders DB's top load. Done means consumers receive order.created and order.cancelled within 5 seconds, exactly once, and polling is switched off.",
                    "hld": "orders-service writes each order change and an event row in one transaction (D-1). A relay publishes event rows to the `orders.events` topic and marks them sent. Events use a versioned envelope (D-2). Notifications-svc consumes the topic and drops duplicates by event_id. Infra adds the topic, a read role for notifications-svc only, and a lag dashboard.\n\nRollback: stop the relay; the event table is additive.",
                    "lld": "- `order_events(id, order_id, type, payload, created_at, sent_at)`\n- Event delivery: a relay polls unsent rows every 200 ms in batches of 500, publishes with key = order_id, and sets `sent_at` after the broker acknowledges.\n- Envelope: event_id, type, schema_version, occurred_at, data.\n- Topic: orders.events, 12 partitions, key = order_id.",
                    "test_strategy": "Unit: envelope and dedupe logic. Integration: relay against a real broker, including a 10-minute outage. Manual: QA checks the lag dashboard in the test environment. Every criterion maps to at least one test named after it.",
                    "scope_in": ["order.created and order.cancelled", "the orders.events topic", "consumer dedupe", "lag dashboard"],
                    "scope_out": ["refund events", "backfilling historical orders", "other consumers"],
                    "decisions": ["#0", "#1"],
                    "criteria": ["#3", "#4", "#5", "#6", "#7", "#8"],
                },
            },
            catalog(
                security_review=("addressed", "AC-4: only notifications-svc reads the topic; payloads carry ids and states only."),
                rollback_plan=("addressed", "HLD: stop the relay; the event table is additive."),
                observability=("addressed", "AC-6: publish lag per topic on the ops dashboard."),
                data_migration_assessed=("not_applicable", "Additive table, no backfill."),
                test_strategy=("addressed", "See draft.test_strategy."),
            ),
        ],
        "draft-from-ticket",
    )
    # rev 2: the draft review agent finds AC-3 untestable; the drafting agent fixes it
    at(days=5, hours=20)
    write(slug, [{"type": "finding", "title": "AC-3 has no outage duration", "fields": {"summary": "AC-3 does not say how long the broker is down, so no test can prove it.", "severity": "major", "target": ["AC-3"], "at_rev": "1"}}], "review-draft")
    at(days=5, hours=19)
    write(
        slug,
        [
            {"ref": "AC-3", "fields": {"text": "Given the broker is down for 10 min, when it recovers, then every event arrives with none duplicated"}, "note": "F-1"},
            {"ref": "draft", "fields": {"test_strategy": "Unit: envelope and dedupe logic. Integration: relay against a real broker, including a 10-minute outage (AC-3). Manual: QA checks the lag dashboard in the test environment. Every criterion maps to at least one test named after it."}, "note": "rev 2 · F-1 fixed: AC-3 outage duration"},
        ],
        "draft-from-ticket",
    )
    # a major finding is closed by a human: arjun confirms the fix
    human_write(slug, [{"ref": "F-1", "fields": {"resolution": "fixed", "resolution_note": "AC-3 now says 10 minutes."}}], "arjun")
    # D-1 is a MUST: the DRI rules it (the write path refuses an agent's MUST verdict)
    at(days=5, hours=15)
    rule(slug, "D-1", "priya", "Transactional outbox", "STD-1 needs exactly-once to the broker; dual-write breaks it and CDC is not set up on orders. Menu sync (D-55) chose the same.")
    # rev 3: meera answers G-1; AC-7 follows from it
    at(days=5, hours=6)
    answer(slug, "G-1", "meera", "yes", "Yes — cancellations matter for notifications; refunds are out of scope.")
    at(days=5, hours=5)
    write(
        slug,
        [
            ac("Given an order is cancelled, then order.cancelled is published once", ["D-1"], because=["G-1"]),  # AC-7
            {"ref": "G-1", "fields": {"resolution": "AC-7 added; order.cancelled is in scope."}},
            {"ref": "draft", "fields": {"criteria": ["AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6", "#0"], "submitted_rev": "3"}, "note": "rev 3 · G-1 answered, AC-7 added"},
        ],
        "draft-from-ticket",
    )
    # review items the answer and the ruling put up (draft, D-1) — the agent re-read them
    for item in call("GET", f"{P(slug)}/reviews", "priya"):
        call("POST", f"{P(slug)}/reviews/{item['id']}/resolve", item["route_to"] or "priya", json={"resolution": "upheld", "note": "Re-read before approval: holds."})
    at(days=4, hours=22)
    approve(slug, "draft", "dri", "priya", note="Scope is right. Ship behind the flag.")

    at(days=4, hours=20)
    write(
        slug,
        [
            task("Outbox table and relay", "Write the event row in the order transaction and relay it to orders.events", "orders-service", ["D-1"], ["AC-2", "AC-3"]),
            task("Emit created and cancelled", "Publish order.created and order.cancelled envelopes", "orders-service", ["D-1", "D-2"], ["AC-1", "AC-7"], depends_on=["#0"]),
            task("Topic, IAM and lag dashboard", "Create orders.events, the notifications-svc read role and the lag dashboard", "infra-terraform", ["D-1"], ["AC-4", "AC-6"], template="terraform-module", rollback="terraform destroy of the new module; nothing else depends on it yet."),
            task("Consume and dedupe events", "Notifications-svc consumes orders.events and drops duplicate event_ids", "notifications-svc", ["D-2"], ["AC-5"], depends_on=["#1", "#2"]),
        ],
        "plan-to-tasks",
    )
    # T-3: PR #212 at a41c09e, tested, approved by arjun
    at(days=2)
    pr(slug, "T-3", 212, "infra-terraform", "a41c09e", ci_attempts="1", review_rounds="1")
    tests(slug, "T-3", "a41c09e", [("AC-4", "test_AC_4_topic_acl")], "infra-terraform plan + policy tests")
    at(days=1, hours=20)
    approve(slug, "T-3", "engg", "arjun", at_sha="a41c09e", note="Topic, role and dashboard as in the HLD.")
    # T-1: the implementing agent hits the DBA rule and raises a deviation, 2 hours ago
    at(hours=3)
    claim(f"task:{IDS[slug]}:T-1", "implement-task")
    at(hours=2)
    write(
        slug,
        [
            {
                "type": "gap",
                "title": "The outbox table can't be added to the orders schema in time",
                "fields": {
                    "question": "The outbox table can't be added to the orders schema in time. How should events be delivered instead?",
                    "kind": "deviation",
                    "domain": "engg",
                    "level": "MUST",
                    "asked_by": "runner-sdk/implement-task",
                    "why_now": "Implementing T-1 hit the orders schema ownership rule: T-1 cannot finish as D-1 is written.",
                    "context": "Approved decision D-1 needs an outbox table written in the same transaction as orders. The repo's rules say the orders schema is DBA-owned and new tables need a two-week change window.\n\n> \"New tables in the orders schema require DBA approval. Allow two weeks.\" — `orders-service/CLAUDE.md#schema-ownership`",
                    "options": [
                        {"key": "separate-schema", "label": "Outbox in a separate schema", "consequence": "No cross-schema transaction, so delivery is no longer exactly-once (breaks STD-1: the DRI has to approve an exception)."},
                        {"key": "cdc", "label": "CDC via Debezium on the orders table", "consequence": "No new table. Exactly-once from the binlog. Adds a connector to run and a lag to watch."},
                        {"key": "dual-write", "label": "Dual-write from the service", "consequence": "Fastest. Loses events on partial failure (breaks STD-1: the DRI has to approve an exception)."},
                    ],
                    "recommendation": "cdc",
                    "recommendation_why": "Keeps exactly-once without touching the DBA-owned schema; platform already runs Debezium.",
                    "blocks": ["D-1", "T-1"],
                    "proposed_change": "D-1 verdict: outbox → CDC via Debezium on the orders table. Add AC: CDC lag over 5 s for 2 min fires the alert. LLD event delivery section rewritten.",
                },
            }
        ],
        "implement-task",
    )


# ── menu-sync-retries: draft rev 2, waiting on meera ─────────────────────────


def menu_sync_retries() -> None:
    slug = "menu-sync-retries"
    at(days=1, hours=2)
    start(slug, "Menu sync retries", "# Menu sync retries\nMenu pushes to partners fail on timeouts and are never retried, so stores show stale menus until someone pushes again by hand.\n\n**Done:** failed pushes retry on their own and no store shows a menu more than 15 minutes old.", "priya", "4833", dri="priya", engg="arjun", product="meera")
    at(days=1)
    write(
        slug,
        [
            decision("Delayed queue in the menu-sync worker", "Where do retries run?", "SHOULD", verdict="Delayed queue in the menu-sync worker", rationale="Cites STD-2 retries with backoff and jitter; reuses the worker.", options=[("delayed queue", "Reuses the worker; backoff is a queue delay", "low"), ("cron re-push", "Simple; menus can be up to 15 minutes stale", "staleness"), ("partner-side", "Not under our control", "none")], on=day(1)),
            decision("Retry budget scope", "What does the retry budget cover?", "SHOULD", domain="product", options=[("per partner", "One flaky partner can't use up retries for everyone", "config per partner"), ("global", "Simpler to run", "one partner can starve the others")]),
            ac("Given a push times out, then it is retried with backoff at most 3 times within 15 minutes", ["#0"]),
            ac("Given the retry budget runs out, then the partner is flagged and on-call is alerted", ["#1"]),
            ac("Given two menu versions are queued, then the partner never receives the older one after the newer one", ["#0"], level="unit"),
            ac("Ops can see retry queue depth per partner", ["initiative"], level="e2e", manual=True),
            {
                "ref": "draft",
                "fields": {
                    "problem": "Menu pushes to partners fail on timeouts and are never retried, so stores show stale menus until someone pushes again by hand. Done means failed pushes retry on their own and no store shows a menu more than 15 minutes old.",
                    "hld": "Failed pushes go to a delayed queue in the menu-sync worker (D-1) with exponential backoff and jitter, as STD-2 requires. A retry budget (D-2) stops one partner from flooding the queue. When the budget runs out, the partner is flagged and on-call is alerted.",
                    "lld": "- `retry_queue(partner_id, menu_version, attempt, next_at)`\n- Backoff 30 s, 2 min, 8 min with ±20% jitter.\n- Each push carries menu_version; the partner adapter drops any version older than the last one acknowledged.\n- Budget counters live in Redis with a one-hour window.",
                    "test_strategy": "Integration: a fake partner that times out N times, checking retries, ordering and the alert. Unit: backoff schedule and version ordering. Manual: QA checks the queue-depth panel.",
                    "scope_in": ["retries for menu pushes", "the budget", "alerting", "a queue-depth panel"],
                    "scope_out": ["retries for order or inventory pushes", "partner-side changes"],
                    "decisions": ["#0", "#1"],
                    "criteria": ["#2", "#3", "#4", "#5"],
                },
            },
            catalog(
                security_review=("not_applicable", "No new access."),
                rollback_plan=("addressed", "Flag menu_retries."),
                observability=("addressed", "AC-2, AC-4."),
                data_migration_assessed=("not_applicable", ""),
                test_strategy=("addressed", ""),
            ),
        ],
        "draft-from-ticket",
    )
    at(hours=4)
    write(
        slug,
        [
            {
                "type": "gap",
                "title": "Is the retry budget per partner or global?",
                "fields": {
                    "question": "Is the retry budget per partner or global?",
                    "kind": "unknown",
                    "domain": "product",
                    "level": "MUST",
                    "asked_by": "runner-sdk/draft-from-ticket",
                    "why_now": "D-2 cannot be decided without it, and the draft cannot be approved with D-2 open.",
                    "context": "STD-2 requires a retry budget but doesn't say what it covers. Partners differ a lot in how often their APIs time out.",
                    "options": [
                        {"key": "per-partner", "label": "Per partner", "consequence": "One flaky partner can't use up retries for everyone. Needs a budget per partner in config."},
                        {"key": "global", "label": "Global", "consequence": "Simpler to run. One flaky partner can starve the others."},
                    ],
                    "recommendation": "per-partner",
                    "recommendation_why": "Partner timeouts are very uneven; a global budget lets one partner starve the rest.",
                    "blocks": ["D-2", "draft"],
                },
            },
            {"ref": "draft", "fields": {"hld": "Failed pushes go to a delayed queue in the menu-sync worker (D-1) with exponential backoff and jitter, as STD-2 requires. A retry budget (D-2, scope pending G-1) stops one partner from flooding the queue. When the budget runs out, the partner is flagged and on-call is alerted."}, "note": "rev 2 · G-1 raised: budget scope unclear"},
        ],
        "draft-from-ticket",
    )
    settle_reviews(slug, "AC-", "HLD wording only: the criteria hold.", "draft-from-ticket")


# ── loyalty-expiry: reopened by an unexplained AC-4 change ───────────────────


def loyalty_expiry() -> None:
    slug = "loyalty-expiry"
    at(days=9)
    start(slug, "Loyalty points expiry", "# Loyalty points expiry\nPoints should expire 365 days after they are earned, with a notice email 30 days before.", "priya", "4790", dri="priya", engg="nikhil", product="meera", qa="sam")
    at(days=8, hours=20)
    write(
        slug,
        [
            decision("Nightly expiry job, not on read", "When are points expired?", "SHOULD", verdict="Nightly expiry job, not on read", rationale="Balances stay cheap to read; one job writes the ledger entries.", on=day(9)),
            ac("Given points older than 365 days, when the nightly job runs, then an expiry ledger entry is written", ["#0"]),
            ac("Given the job reruns, then no point expires twice", ["#0"]),
            ac("Given points expire in 30 days, then the member gets one notice email", ["#0"]),
            ac("Points expire 365 days after earning", ["#0"], level="unit"),
            ac("The admin report lists expired points per day", ["#0"]),
            ac("Support can see a member's upcoming expiries", ["initiative"], level="e2e", manual=True),
            {"ref": "draft", "fields": {"problem": "Points never expire, which the partner contract requires.", "hld": "A nightly job (D-1) writes expiry ledger entries; a notice email goes out 30 days before.", "lld": "- `expiry_runs(day, status)` for idempotency\n- ledger entry type EXPIRY", "test_strategy": "Unit for the date rule; integration for the job and emails; manual check of the support view.", "decisions": ["#0"], "criteria": ["#1", "#2", "#3", "#4", "#5", "#6"], "submitted_rev": "1"}},
            catalog(data_migration_assessed=("not_applicable", "")),
        ],
        "draft-from-ticket",
    )
    at(days=8)
    approve(slug, "draft", "dri", "priya")
    at(days=7, hours=20)
    write(
        slug,
        [
            task("Expiry job and ledger entries", "Nightly job writing expiry ledger entries", "loyalty-svc", ["D-1"], ["AC-1", "AC-2"]),
            task("Expiry notice emails", "30-day notice emails", "loyalty-svc", ["D-1"], ["AC-3", "AC-4"]),
            task("Admin expiry report", "Expired points per day, and the support view", "loyalty-admin", ["D-1"], ["AC-5", "AC-6"], depends_on=["#1"]),
        ],
        "plan-to-tasks",
    )
    at(days=4)
    ship(slug, "T-1", 91, "loyalty-svc", "b77e2d10", [("AC-1", "test_AC_1_expiry_entry"), ("AC-2", "test_AC_2_idempotent_rerun")], "nikhil", "loyalty-svc suite")
    at(hours=6)
    pr(slug, "T-2", 95, "loyalty-svc", "c09a1f3e")
    # meera (product) reviews the PR and says AC-4 contradicts the contract; the implementing
    # agent edits AC-4 citing her finding (explained: a human raised it) — then nikhil rejects
    # the finding, so the change loses its reason: unexplained drift, the draft reopens and
    # GATE_PR blocks.
    at(hours=5)
    human_write(slug, [{"type": "finding", "title": "AC-4 contradicts the partner contract", "fields": {"summary": "The partner contract counts 365 days from the last purchase, not from earning.", "severity": "major", "target": ["AC-4", "T-2"], "at_sha": "c09a1f3e"}}], "meera")
    at(hours=4)
    write(slug, [{"ref": "AC-4", "fields": {"text": "Points expire 365 days after the last purchase"}, "because": ["F-1"], "note": "per F-1"}], "implement-task")
    at(minutes=40)
    human_write(slug, [{"ref": "F-1", "fields": {"resolution": "rejected", "resolution_note": "Wrong contract version: the signed one says 365 days after earning."}}], "nikhil")


# ── payouts-v2: a standard moved under D-2; T-3 waits on arjun ───────────────


def payouts_v2() -> None:
    slug = "payouts-v2"
    at(days=12)
    start(slug, "Payouts v2: refunds ledger", "# Payouts v2: refunds ledger\nRefunds must show in partner payouts as ledger entries, reconciled to the cent.", "nikhil", "4702", dri="nikhil", engg="arjun", product="meera", qa="sam")
    at(days=11, hours=20)
    write(
        slug,
        [
            decision("Refunds as negative ledger entries", "How are refunds represented in payouts?", "MUST", options=[("negative entries", "One ledger, sums just work", "migration of report queries"), ("separate table", "No change to existing entries", "two sources to reconcile")]),
            decision("Round per line item", "Where is rounding applied?", "MUST", options=[("per line", "Matches partner invoices", "sum of lines may differ from total by a cent"), ("per settlement", "Totals exact", "lines don't match invoices")]),
            ac("Given a refund, then a negative ledger entry with the refund amount is written", ["#0"]),
            ac("Given a settlement, then refunds reduce the payout total", ["#0"]),
            ac("Given a partial refund, then each refunded line is its own entry", ["#0"]),
            ac("Given the ledger API, when a payout is read, then refunds are listed with their order ids", ["#0"]),
            ac("Given amounts with fractions of a cent, then each line rounds half-even", ["#1"], level="unit"),
            ac("The settlement export carries one row per line", ["#1"]),
            ac("Finance can see refunds per partner per day", ["initiative"], level="e2e", manual=True),
            {"ref": "draft", "fields": {"problem": "Refunds are settled outside payouts, so partner statements never reconcile.", "hld": "Refunds become negative ledger entries (D-1), rounded per line (D-2).", "lld": "- ledger entry type REFUND, amount < 0\n- rounding: half-even per line", "test_strategy": "Ledger and API integration tests; finance checks the dashboard by hand.", "decisions": ["#0", "#1"], "criteria": ["#2", "#3", "#4", "#5", "#6", "#7", "#8"], "submitted_rev": "1"}},
            catalog(data_migration_assessed=("addressed", "Report queries migrated in T-1.")),
        ],
        "draft-from-ticket",
    )
    at(days=11, hours=10)
    rule(slug, "D-1", "arjun", "Refunds as negative ledger entries", "One ledger keeps payouts summable.")
    rule(slug, "D-2", "arjun", "Round per line item", "Matches partner invoices; STD-3.")
    for item in call("GET", f"{P(slug)}/reviews", "nikhil"):
        call("POST", f"{P(slug)}/reviews/{item['id']}/resolve", item["route_to"] or "nikhil", json={"resolution": "upheld", "note": "Holds."})
    at(days=11)
    approve(slug, "draft", "dri", "nikhil")
    at(days=10, hours=20)
    write(
        slug,
        [
            task("Ledger schema", "REFUND entry type and report query migration", "payouts-svc", ["D-1"], ["AC-1", "AC-2"]),
            task("Refund writer", "Write refund entries per line", "payouts-svc", ["D-1"], ["AC-3"]),
            task("Refunds ledger API", "Expose refunds on the payout API", "payouts-svc", ["D-1", "D-2"], ["AC-4", "AC-5"]),
            task("Settlement export", "One export row per line", "payouts-svc", ["D-2"], ["AC-6"]),
            task("Finance dashboard", "Refunds per partner per day", "finance-ui", ["D-2"], ["AC-7"], template="react-app", depends_on=["#3"]),
        ],
        "plan-to-tasks",
    )
    at(days=6)
    ship(slug, "T-1", 71, "payouts-svc", "11aa22bb", [("AC-1", "test_AC_1_refund_entry"), ("AC-2", "test_AC_2_payout_total")], "arjun", "payouts-svc suite")
    at(days=4)
    ship(slug, "T-2", 74, "payouts-svc", "33cc44dd", [("AC-3", "test_AC_3_per_line_entries")], "arjun", "payouts-svc suite")
    at(days=1, hours=3)
    pr(slug, "T-3", 77, "payouts-svc", "e19b0c4", ci_attempts="2", review_rounds="1")
    tests(slug, "T-3", "e19b0c4", [("AC-4", "test_AC_9_refund_negative_entry"), ("AC-5", "test_AC_10_ledger_balances")], "payouts-svc suite")
    write(slug, [{"type": "finding", "title": "Ledger entry comment is out of date", "fields": {"summary": "Ledger entry comment is out of date", "severity": "minor", "target": ["T-3"], "at_sha": "e19b0c4", "resolution": "acknowledged", "resolution_note": "Comment fixed in a follow-up."}}], "review-pr")
    at(minutes=22)
    claim(f"task:{IDS[slug]}:T-4", "implement-task")


def stale_standard() -> None:
    """Finance changes STD-3 (global). Standards live in the global scope and records cannot
    cite across scopes, so the change reaches payouts-v2 as a product gap; meera's answer
    puts D-2 (round per line item) up for review, routed to arjun (engg)."""
    at(hours=21)
    call("POST", "/api/global/records", "priya", json={"ops": [{"ref": "STD-3", "fields": {"rule": "Money is rounded once per settlement, half-even, in minor units."}, "note": "finance: round once per settlement"}]})
    at(hours=20, minutes=30)
    write(
        "payouts-v2",
        [{"type": "gap", "title": "STD-3 now rounds per settlement", "fields": {"question": "STD-3 settlement rounding changed to once per settlement. Do partner invoices still round per line?", "kind": "conflict", "domain": "product", "level": "SHOULD", "asked_by": "runner-sdk/standards-watch", "why_now": "D-2 chose per-line rounding to match partner invoices; STD-3 now says per settlement.", "context": "STD-3 now says round once per settlement, not per line. D-2 chose per-line rounding to match partner invoices.", "options": [{"key": "per-line", "label": "Invoices still round per line", "consequence": "D-2 holds; an exception to STD-3 is noted"}, {"key": "per-settlement", "label": "Invoices moved to per settlement", "consequence": "D-2 must be superseded"}], "recommendation": "per-line", "blocks": ["D-2"]}}],
        "standards-watch",
    )
    at(hours=20)
    answer("payouts-v2", "G-1", "meera", "per-line", "Partners still invoice per line; our statements must match them.")


# ── store-hours-api: validating, AC-10 needs sam ─────────────────────────────


def store_hours_api() -> None:
    slug = "store-hours-api"
    at(days=10)
    start(slug, "Store hours API", "# Store hours API\nPartners read store hours from us instead of their own copies.", "rahul", "4655", dri="rahul", engg="nikhil", qa="sam")
    at(days=9, hours=20)
    texts = [
        "Given a store, when its hours are read, then today's hours are returned",
        "Given a holiday override, then the override wins",
        "Given a store closed today, then closed is returned",
        "Given an unknown store, then 404",
        "Given a partner key, then only its stores are readable",
        "Given 1000 reads per second, then p99 stays under 50 ms",
        "Given hours change, then the cache is invalidated within 60 seconds",
        "Given the cache is cold, then reads fall through to the database",
        "Given the partner app, when hours change, then the sync job pushes them",
    ]
    write(
        slug,
        [
            decision("Hours from cache", "How are hours served?", "SHOULD", verdict="Hours served from cache with a 60-second TTL", rationale="Reads dominate; 60 s staleness is acceptable to partners.", on=day(10)),
            *[ac(t, ["#0"]) for t in texts],
            ac("Store hours show in the partner app within 5 minutes of a change", ["#0"], level="e2e", manual=True),
            {"ref": "draft", "fields": {"problem": "Partners keep their own copies of store hours, which drift.", "hld": "A read API over cached hours (D-1); a sync job pushes changes to the partner app.", "lld": "- cache key store:{id}:hours, TTL 60 s\n- invalidate on write", "test_strategy": "Integration for the API and cache; QA checks the partner app by hand (AC-10).", "decisions": ["#0"], "criteria": [f"#{i}" for i in range(1, 11)], "submitted_rev": "1"}},
            catalog(data_migration_assessed=("not_applicable", "")),
        ],
        "draft-from-ticket",
    )
    at(days=9)
    approve(slug, "draft", "dri", "rahul")
    at(days=8, hours=20)
    write(
        slug,
        [
            task("Hours model and API", "The read API", "stores-svc", ["D-1"], [f"AC-{i}" for i in range(1, 7)]),
            task("Cache invalidation", "Invalidate on write", "stores-svc", ["D-1"], ["AC-7", "AC-8"]),
            task("Partner app sync", "Push hour changes to the partner app", "partner-gw", ["D-1"], ["AC-9", "AC-10"]),
        ],
        "plan-to-tasks",
    )
    at(days=6)
    ship(slug, "T-1", 301, "stores-svc", "5e6f7a8b", [(f"AC-{i}", f"test_AC_{i}") for i in range(1, 7)], "nikhil", "stores-svc suite")
    at(days=5)
    ship(slug, "T-2", 305, "stores-svc", "6f7a8b9c", [("AC-7", "test_AC_7_invalidate"), ("AC-8", "test_AC_8_cold_cache")], "nikhil", "stores-svc suite")
    # A task is DONE only with a green run row for every covered AC — manual ones too — so
    # the e2e smoke run records AC-10; QA's signature is still what GATE_VALIDATED needs.
    at(hours=3)
    ship(slug, "T-3", 88, "partner-gw", "7a8b9c0d", [("AC-9", "test_AC_9_sync_push"), ("AC-10", "smoke_partner_app_hours")], "nikhil", "partner-gw suite + e2e smoke")


# ── webhook-signing: the drafting agent is on it ─────────────────────────────


def webhook_signing() -> None:
    slug = "webhook-signing"
    at(minutes=6)
    start(slug, "Partner webhook signing", "# Partner webhook signing\nPartners want to verify that webhooks come from us.", "rahul", None, dri="rahul", engg="nikhil")
    at(minutes=4)
    claim(f"draft:{IDS[slug]}", "draft-from-ticket", ttl_min=60)


# ── inventory-sync-v3: shipped ───────────────────────────────────────────────


def inventory_sync_v3() -> None:
    slug = "inventory-sync-v3"
    at(days=20)
    start(slug, "Inventory sync v3", "# Inventory sync v3\nPartner inventory must be no more than a minute stale.", "priya", "4511", dri="priya", engg="nikhil", product="meera", qa="sam")
    at(days=19, hours=20)
    write(
        slug,
        [
            decision("Full sync every 5 minutes", "How often is inventory synced?", "SHOULD", verdict="Full sync every 5 minutes", rationale="Simple and bounded.", on=day(20)),
            decision("Partner push over webhooks", "How do partners receive changes?", "SHOULD", verdict="Partner push over signed webhooks", rationale="Partners asked for push.", on=day(20)),
            ac("Given a stock change, then the partner sees it within a minute", ["#0"]),
            ac("Given a partner timeout, then the push retries with backoff", ["#1"]),
            ac("Given a full resync, then no partner receives a duplicate", ["#0"]),
            ac("Ops can see sync lag per partner", ["initiative"], level="e2e", manual=True),
            {"ref": "draft", "fields": {"problem": "Partner inventory is up to an hour stale.", "hld": "Sync (D-1) and push (D-2).", "lld": "- sync cursor per partner", "test_strategy": "Integration and a manual lag check.", "decisions": ["#0", "#1"], "criteria": ["#2", "#3", "#4", "#5"], "submitted_rev": "1"}},
            catalog(data_migration_assessed=("not_applicable", "")),
        ],
        "draft-from-ticket",
    )
    at(days=19)
    approve(slug, "draft", "dri", "priya")
    # mid-build: a full sync can't meet "within a minute"; meera picks delta sync
    at(days=16)
    write(slug, [{"type": "gap", "title": "Full sync can't meet one minute", "fields": {"question": "A full sync takes 4 minutes for large partners. Switch to delta sync every 30 seconds?", "kind": "deviation", "domain": "product", "level": "MUST", "asked_by": "runner-sdk/implement-task", "why_now": "AC-1 cannot pass with D-1.", "context": "Large partners have 200k SKUs; a full sync takes 4 minutes.", "options": [{"key": "delta", "label": "Delta sync every 30 s", "consequence": "D-1 superseded"}, {"key": "relax", "label": "Relax AC-1 to 5 minutes", "consequence": "AC-1 changes"}], "recommendation": "delta", "blocks": ["D-1"]}}], "implement-task")
    at(days=15, hours=20)
    answer("inventory-sync-v3", "G-1", "meera", "delta", "Delta sync — a minute is what partners were promised.")
    at(days=15, hours=18)
    write(slug, [decision("Delta sync every 30 seconds", "How often is inventory synced?", "SHOULD", verdict="Delta sync every 30 seconds", rationale="G-1: full sync is too slow for large partners.", by="runner-sdk/implement-task", on=day(16), supersedes=["D-1"], because=["G-1"]), {"ref": "G-1", "fields": {"resolution": "D-3 supersedes D-1."}}], "implement-task")
    for item in call("GET", f"{P(slug)}/reviews", "priya"):
        call("POST", f"{P(slug)}/reviews/{item['id']}/resolve", item["route_to"] or "priya", json={"resolution": "upheld", "note": "Holds under delta sync."})
    at(days=15)
    write(
        slug,
        [
            task("Delta endpoint", "Changed-since endpoint and cursor", "inventory-svc", ["D-3"], ["AC-1", "AC-3"]),
            task("Partner push", "Signed webhooks with retries", "partner-gw", ["D-2"], ["AC-2", "AC-4"]),
        ],
        "plan-to-tasks",
    )
    at(days=4)
    ship(slug, "T-1", 410, "inventory-svc", "8b9c0d1e", [("AC-1", "test_AC_1_one_minute"), ("AC-3", "test_AC_3_no_duplicates")], "nikhil", "inventory-svc suite")
    at(days=3)
    ship(slug, "T-2", 233, "partner-gw", "9c0d1e2f", [("AC-2", "test_AC_2_backoff"), ("AC-4", "smoke_sync_lag_panel")], "nikhil", "partner-gw suite + e2e smoke")
    at(days=2)
    call("POST", f"{P(slug)}/criteria/AC-4/sign", "sam", json={"at_sha": "9c0d1e2f"})
    at(days=1)
    for t, sha in (("T-1", "8b9c0d1e"), ("T-2", "9c0d1e2f")):
        call("POST", "/api/deploy-guard", ("github-actions", "agent"), json={"initiative_id": IDS[slug], "task": t, "sha": sha, "environment": "staging"})


def main() -> int:
    url = db_settings.url()
    if url.startswith("sqlite"):
        Path("var").mkdir(exist_ok=True)
    Base.metadata.create_all(engine_primary)  # no-op once `make migrate` has run
    if not os.environ.get("SEED_KEEP"):
        with engine_primary.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
    global_scope()
    inventory_sync_v3()
    payouts_v2()
    loyalty_expiry()
    store_hours_api()
    order_events()
    menu_sync_retries()
    stale_standard()
    webhook_signing()
    set_clock(None)
    print(f"seeded {url}")
    print("  order-events       BUILD · T-1 paused on G-2 (deviation, arjun) · T-3 approved at a41c09e")
    print("  menu-sync-retries  DRAFT rev 2 · G-1 open for meera")
    print("  loyalty-expiry     BUILD · draft REOPENED: AC-4 changed, its reason F-1 rejected")
    print("  payouts-v2         BUILD · STD-3 changed: D-2 up for review (arjun) · T-3 PR waits on arjun")
    print("  store-hours-api    VALIDATE · manual AC-10 waits on sam")
    print("  webhook-signing    DRAFT · draft-from-ticket holds the lease")
    print("  inventory-sync-v3  SHIP")
    print("  people: arjun (engg) · priya (dri) · meera (product) · sam (qa) · nikhil (engg, dri) · rahul (dri)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
