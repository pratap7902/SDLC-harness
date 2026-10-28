"""Gates over small graphs: each rule names exactly the refs that fail it."""

from types import SimpleNamespace

from tests.fixtures.graphs import graph, people, rec

CATALOG = [
    {"item": i, "disposition": "addressed"}
    for i in ("security_review", "rollback_plan", "observability", "data_migration_assessed", "test_strategy")
]


def rules(result):
    return {r.name: (r.passed, r.failing) for r in result.rules}


def spec(**over):
    records = {
        "initiative": rec("initiative", catalog=CATALOG),
        "draft": rec("draft", problem="p", hld="h", test_strategy="t"),
        "D-1": rec("D-1", question="q", verdict="v", level="SHOULD"),
        "D-2": rec("D-2", question="q", level="SHOULD"),
        "AC-1": rec("AC-1", text="a", level="unit", source=["D-1"]),
        "G-1": rec("G-1", question="q", blocks=["D-2"]),
    }
    records.update(over)
    return [r for r in records.values() if r is not None] + people(dri="chandra", engg="priya")


def test_gate_draft_names_what_blocks():
    g = graph(spec())
    result = g.gate("GATE_DRAFT")
    assert result.status == "BLOCKED"
    r = rules(result)
    assert r["no_open_decision_in_draft_scope"] == (False, ["D-2"])
    assert r["no_open_gap_blocking_draft"] == (False, ["G-1"])
    assert r["every_decision_covered_by_an_ac"] == (False, ["D-2"])
    assert r["catalog_addressed"] == (True, [])
    assert r["every_ac_has_source"] == (True, [])
    assert r["approval_by_role"][0] is False


def test_a_should_gap_and_a_provisional_should_decision_do_not_block_the_draft():
    g = graph(
        spec(
            **{
                "D-2": rec("D-2", question="q", verdict="v", provisional="yes", level="SHOULD"),
                "G-1": rec("G-1", question="q", blocks=["D-2"], level="SHOULD"),
                "AC-2": rec("AC-2", text="b", level="unit", source=["D-2"]),
            }
        )
    )
    r = rules(g.gate("GATE_DRAFT"))
    assert r["no_open_decision_in_draft_scope"] == (True, [])
    assert r["no_open_gap_blocking_draft"] == (True, [])
    assert r["every_decision_covered_by_an_ac"] == (True, [])


def test_catalog_and_open_review_items_on_the_spec():
    item = SimpleNamespace(target_ref="draft", cause_ref="initiative", status="open")
    g = graph(spec(initiative=rec("initiative", catalog=CATALOG[:2])), review_items=[item])
    r = rules(g.gate("GATE_DRAFT"))
    assert r["catalog_addressed"] == (False, ["observability", "data_migration_assessed", "test_strategy"])
    assert r["no_open_review_items_on_spec"] == (False, ["draft"])


def test_gate_pr_rules_for_a_task():
    task = rec("T-1", goal="g", repo="r", template="t", implements=["D-1"], covers=["AC-1"], pr_state="draft")
    finding = rec("F-1", summary="s", severity="blocker", target=["T-1"])
    g = graph(spec() + [task, finding])
    r = rules(g.gate("GATE_PR", task="T-1"))
    assert r["pr_state_in"] == (False, ["T-1"])
    assert r["no_blocker_finding_open_at_sha"] == (False, ["F-1"])
    assert r["every_covered_ac_has_a_test"] == (False, ["AC-1"])
    assert r["drift_explained_for_task"][0] is False  # no baseline yet


def test_gate_validated_with_a_manual_ac():
    acs = [
        rec("AC-1", text="a", level="unit", source=["D-1"]),
        rec("AC-2", text="m", level="manual", manual="yes", source=["D-1"]),
    ]
    run = rec("R-1", result="GREEN", at_sha="s", run_on="2026-10-30", covers=[{"ac": "AC-1", "result": "GREEN"}])
    g = graph([rec("D-1", verdict="v")] + acs + [run])
    r = rules(g.gate("GATE_VALIDATED"))
    assert r["every_ac_green"] == (True, [])
    assert r["manual_acs_signed_by"] == (False, ["AC-2"])
    signed = graph([rec("D-1", verdict="v"), acs[0], rec("AC-2", text="m", level="manual", manual="yes", source=["D-1"], signed_by="sam"), run])
    assert signed.gate("GATE_VALIDATED").status == "PASSED"


def test_the_latest_run_decides_green():
    acs = [rec("AC-1", text="a", level="unit", source=["D-1"])]
    old = rec("R-1", result="GREEN", run_on="2026-10-30", covers=[{"ac": "AC-1", "result": "GREEN"}])
    new = rec("R-2", result="RED", run_on="2026-10-31", covers=[{"ac": "AC-1", "result": "RED"}])
    g = graph([rec("D-1", verdict="v")] + acs + [old, new])
    assert rules(g.gate("GATE_VALIDATED"))["every_ac_green"] == (False, ["AC-1"])
