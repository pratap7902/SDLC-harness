"""Table-driven: small graphs in, derived statuses out."""

import pytest

from tests.fixtures.graphs import graph, people, rec


def status(records, ref, **kw):
    g = graph(records, **kw)
    return g.get(ref).status


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({}, "OPEN"),
        ({"verdict": "outbox"}, "DECIDED"),
        ({"verdict": "outbox", "provisional": "yes"}, "PROVISIONAL"),
    ],
)
def test_decision_status(fields, expected):
    assert status([rec("D-1", question="q", **fields)], "D-1") == expected


def test_a_superseded_decision():
    records = [rec("D-1", verdict="a"), rec("D-2", verdict="b", supersedes=["D-1"])]
    g = graph(records)
    assert (g.get("D-1").status, g.get("D-2").status) == ("SUPERSEDED", "DECIDED")


@pytest.mark.parametrize(
    "fields, expected",
    [({}, "OPEN"), ({"answer": "yes"}, "ANSWERED"), ({"answer": "yes", "withdrawn_because": "moot"}, "WITHDRAWN")],
)
def test_gap_status(fields, expected):
    assert status([rec("G-1", **fields)], "G-1") == expected


def test_ac_status_follows_the_baseline():
    baseline = rec("B-1", label="B-1", members=[{"ref": "AC-1", "type": "acceptance_criterion", "rev": "1"}])
    acs = [rec("AC-1", text="a"), rec("AC-2", text="b"), rec("AC-3", text="c", retired_because="dropped")]
    assert status(acs[:1], "AC-1") == "PROPOSED"
    g = graph([baseline] + acs)
    assert [g.get(r).status for r in ("AC-1", "AC-2", "AC-3")] == ["APPROVED", "ADDED_AFTER_BASELINE", "RETIRED"]


def test_finding_test_run_deploy_assignment_baseline():
    g = graph(
        [
            rec("F-1", severity="minor"),
            rec("F-2", resolution="rejected"),
            rec("R-1", result="RED"),
            rec("DEP-1", result="DEPLOYED"),
            rec("A-1", person="a", role="dri", scope=["initiative"]),
            rec("A-2", person="b", role="dri", scope=["initiative"]),
            rec("B-1", label="x"),
            rec("B-2", label="y"),
        ]
    )
    assert [g.get(r).status for r in ("F-1", "F-2", "R-1", "DEP-1", "A-1", "A-2", "B-1", "B-2")] == [
        "OPEN", "REJECTED", "RED", "DEPLOYED", "REPLACED", "ACTIVE", "SUPERSEDED", "CURRENT",
    ]


def task(ref="T-1", **fields):
    base = {"goal": "g", "repo": "r", "template": "t", "implements": ["D-1"], "covers": ["AC-1"]}
    return rec(ref, **{**base, **fields})


def green_run(sha="s1", ac="AC-1"):
    return rec("R-1", result="GREEN", at_sha=sha, covers=[{"ac": ac, "result": "GREEN"}])


@pytest.mark.parametrize(
    "extra, task_fields, leases, expected",
    [
        ([], {}, (), "READY"),
        ([], {}, ("task:t:T-1",), "IN_PROGRESS"),
        ([], {}, ("task:other-initiative:T-1",), "READY"),
        ([], {"pr_state": "draft"}, (), "IN_PROGRESS"),
        ([], {"pr_state": "open", "pr_sha": "s1", "pr_url": "u"}, (), "IN_REVIEW"),
        ([green_run()], {"pr_state": "merged", "pr_sha": "s1", "pr_url": "u"}, (), "DONE"),
        # merged, but no green run at the PR's sha: not DONE
        ([green_run("other")], {"pr_state": "merged", "pr_sha": "s1", "pr_url": "u"}, (), "READY"),
        ([], {"ci_attempts": "3"}, (), "STUCK"),
        ([], {"review_rounds": "4", "pr_state": "open", "pr_sha": "s", "pr_url": "u"}, (), "STUCK"),
        ([rec("G-1", blocks=["T-1"])], {}, (), "BLOCKED"),
        ([rec("G-1", blocks=["T-1"], level="SHOULD")], {}, (), "READY"),
        ([task("T-2")], {"depends_on": ["T-2"]}, (), "BLOCKED"),
    ],
)
def test_task_status(extra, task_fields, leases, expected):
    records = [rec("D-1", verdict="v", level="SHOULD"), rec("AC-1", text="a"), task(**task_fields)] + extra
    assert status(records, "T-1", leases=leases) == expected


def test_an_open_must_decision_blocks_the_task_that_implements_it():
    records = [rec("D-1", level="MUST"), rec("AC-1", text="a"), task()]
    assert status(records, "T-1") == "BLOCKED"


def test_initiative_phase_needs_people_first():
    assert status([rec("initiative")], "initiative") == "UNASSIGNED"
    assert status([rec("initiative")] + people(dri="a", engg="b"), "initiative") == "DRAFT"
    assert status([rec("initiative", closed_because="cancelled")], "initiative") == "CLOSED"


def test_draft_status_before_a_baseline():
    assert status([rec("draft", problem="p")], "draft") == "DRAFTING"
    assert status([rec("draft", problem="p", submitted_rev="2")], "draft") == "IN_REVIEW"


def test_standards_and_learnings_read_their_own_field():
    assert status([rec("STD-1", state="enforced")], "STD-1") == "ENFORCED"
    assert status([rec("L-1")], "L-1") == "DRAFT"
