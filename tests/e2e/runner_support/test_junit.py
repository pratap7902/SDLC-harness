"""JUnit ingestion → a test_run bound to the sha, AC rows from test names; GATE_PR reads it."""

import pytest

from app.exceptions import ValidationException
from app.initiatives.services.junit_service import Case, ac_refs, covers_rows, parse_junit
from tests.fixtures.slice import SLUG, to_task

SHA = "abc1234def"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="orders" tests="6">
    <testcase classname="tests.test_outbox" name="test_AC_1_outbox_row_in_same_tx"/>
    <testcase classname="tests.test_outbox" name="test_ac2_relay_publishes_within_5s"/>
    <testcase classname="tests.test_outbox" name="test_AC-2 relay retries">
      <failure message="timeout">AssertionError</failure>
    </testcase>
    <testcase classname="tests.test_keys" name="testAc3PartitionKey"/>
    <testcase classname="tests.test_keys" name="test_AC_9_not_an_ac_here"/>
    <testcase classname="tests.test_misc" name="test_helper_tracks3"/>
    <testcase classname="tests.test_misc" name="test_AC_1_skipped"><skipped/></testcase>
  </testsuite>
</testsuites>"""


def test_ac_ref_forms():
    assert ac_refs("test_AC_3_rejects") == ["AC-3"]
    assert ac_refs("AC-3: rejects; also AC_4 and ac5") == ["AC-3", "AC-4", "AC-5"]
    assert ac_refs("testAc12Thing") == ["AC-12"]
    assert ac_refs("test_track3_and_vacuum") == []
    assert ac_refs("test_AC_03") == ["AC-3"]


def test_rows_take_the_worst_outcome_and_skip_skipped():
    cases = [Case("test_AC_1_a", "", "passed"), Case("test_AC_1_b", "", "failed"), Case("test_AC_2", "", "error"), Case("test_AC_3", "", "skipped"), Case("test_AC_7", "", "passed")]
    rows, unknown = covers_rows(cases, "https://ci.example.com/1", known={"AC-1", "AC-2", "AC-3"})
    assert [(r["ac"], r["result"]) for r in rows] == [("AC-1", "RED"), ("AC-2", "ERROR")]
    assert unknown == ["AC-7"]


def test_parse_refuses_dtds_and_garbage():
    with pytest.raises(ValidationException):
        parse_junit('<!DOCTYPE x [<!ENTITY a "b">]><testsuite><testcase name="x"/></testsuite>')
    with pytest.raises(ValidationException):
        parse_junit("<testsuite><testcase")
    with pytest.raises(ValidationException):
        parse_junit("<testsuite/>")


def post(api, xml=XML, sha=SHA, level="integration", task="T-1", who=None, run_url="https://ci.example.com/runs/42"):
    who = who or api.as_("ci-bot", "agent")
    return who.post(f"{api.base(SLUG)}/test-runs/junit", json={"task": task, "sha": sha, "level": level, "run_url": run_url, "junit_xml": xml})


def test_ingest_writes_a_test_run_bound_to_the_sha(api):
    to_task(api)
    out = api.ok(post(api), 201)
    assert out["ref"] == "R-1" and out["result"] == "RED" and out["failed"] == 1 and out["skipped"] == 1
    assert [(r["ac"], r["result"]) for r in out["covers"]] == [("AC-1", "GREEN"), ("AC-2", "RED"), ("AC-3", "GREEN")]
    assert out["unknown_acs"] == ["AC-9"]
    run = api.record(SLUG, "R-1")
    assert run["fields"]["at_sha"] == SHA and run["fields"]["task"] == ["T-1"] and run["status"] == "RED"
    assert run["created_by"] == "ci-bot/junit"
    # the same upload again is a replay, not R-2
    assert api.ok(post(api), 201)["ref"] == "R-1"
    assert len(api.get(f"{api.base(SLUG)}/records", type="test_run")) == 1


def test_gate_pr_counts_runs_only_at_the_pr_sha(api):
    to_task(api)
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_state": "open", "pr_url": "https://github.com/example/orders/pull/7", "pr_sha": SHA}}])
    green = XML.replace('<failure message="timeout">AssertionError</failure>', "")
    api.ok(post(api, xml=green, sha="0000000fff"), 201)  # another sha: does not count
    rule = lambda: next(r for r in api.get(f"{api.base(SLUG)}/tasks/T-1/gates")[0]["rules"] if r["name"] == "every_covered_ac_has_a_test")  # noqa: E731
    assert not rule()["passed"]
    api.ok(post(api, xml=green), 201)
    assert rule()["passed"], rule()


def test_red_ci_at_head_becomes_rework_for_the_agent_lane(api):
    to_task(api)
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_state": "open", "pr_url": "https://github.com/example/orders/pull/7", "pr_sha": SHA}}])
    api.ok(post(api), 201)
    items = api.ok(api.agent().get(f"{api.base(SLUG)}/next-work", params={"kind": "task"}))["items"]
    assert items and items[0]["rework"] == "ci" and items[0]["rework_refs"] == ["R-1"]
    # a new head sha answers it
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_sha": "fedcba9876"}}])
    items = api.ok(api.agent().get(f"{api.base(SLUG)}/next-work", params={"kind": "task"}))["items"]
    assert not [x for x in items if x.get("rework")]


def test_review_findings_at_head_become_rework(api):
    to_task(api)
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_state": "open", "pr_url": "https://github.com/example/orders/pull/7", "pr_sha": SHA}}])
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "relay drops events on restart", "severity": "blocker", "target": ["T-1"], "at_sha": SHA}}], who=api.as_("priya"))
    items = api.ok(api.agent().get(f"{api.base(SLUG)}/next-work", params={"kind": "task"}))["items"]
    assert items[0]["rework"] == "review" and items[0]["rework_refs"] == ["F-1"]


def test_ingest_validation(api):
    to_task(api)
    assert post(api, level="smoke").status_code == 422
    assert post(api, sha="not-a-sha").status_code == 422
    assert post(api, task="T-9").status_code == 404
