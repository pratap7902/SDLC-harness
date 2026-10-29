"""The MCP tools call the same services as REST and answer in compact text."""

from types import SimpleNamespace

import pytest

from app.mcp import server
from tests.fixtures.slice import SLUG, draft_batch, task_op


def ctx(person="runner-sdk"):
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={"x-actor": person})))


@pytest.fixture
def started(client, api):
    out = server.create_initiative(title="Order events outbox", requirement="# Order events", dri="chandra", engg="priya", ctx=ctx(), slug=SLUG, product="maya")
    iid = api.id(SLUG)
    assert out.startswith(f"{iid} · {SLUG} — ")
    return iid


def test_create_write_and_read(started):
    iid = started
    out = server.write(iid, draft_batch(), ctx(), batch_id="m-1", agent="draft-skill")
    assert out.splitlines()[0] == "D-1 created rev 1 [DECIDED]"
    again = server.write(iid, draft_batch(), ctx(), batch_id="m-1", agent="draft-skill")
    assert again.startswith("(batch m-1 replayed")
    state = server.get_state(iid)
    assert "GATE_DRAFT: BLOCKED — failing no_open_gap_blocking_draft, approval_by_role" in state
    full = server.read_record(iid, ["G-1"], history=True)
    assert "links out: blocks D-2" in full and "(agent)" in full
    assert "D-1 [DECIDED]" in server.search_records(iid, type="decision")


def test_a_rejected_write_explains_every_error(started):
    iid = started
    with pytest.raises(ValueError) as e:
        server.write(iid, '[{"ref": "draft", "status": "APPROVED"}]', ctx())
    assert "REJECTED — nothing was saved" in str(e.value) and "status: derived" in str(e.value)
    with pytest.raises(ValueError) as e:
        server.write(iid, [{"type": "gap", "fields": {"answer": "x"}}], ctx())
    assert "answer: human-only" in str(e.value)


def test_no_human_only_tools():
    names = set(server.mcp._tool_manager._tools)
    assert not names & {"answer_gap", "approve", "rule_decision", "sign_manual_ac", "promote_learning"}
    assert {"next_work", "claim", "drift_report", "deploy_guard", "gate_status", "inbox"} <= names


def test_work_loop_and_reports(started, api):
    iid = started
    server.write(iid, draft_batch(), ctx())
    api.answer(SLUG, "G-1", choice="yes", person="maya")
    server.write(iid, [{"ref": "D-2", "reviewed": True, "note": "holds"}], ctx())
    (item,) = api.get(f"/api/initiatives/{iid}/reviews")  # advice: a human upholds
    api.ok(api.as_("priya").post(f"/api/initiatives/{iid}/reviews/{item['id']}/resolve", json={"resolution": "upheld", "note": "holds"}))
    api.approve(SLUG, "draft", "dri", "chandra")
    server.write(iid, [task_op()], ctx())
    work = server.next_work(ctx(), initiative_id=iid, kind="task")
    assert work.startswith(f"task:{iid}:T-1 (task, agent)")
    assert "cites D-1 [DECIDED]" in work
    assert server.claim(f"task:{iid}:T-1", ctx()).startswith(f"claimed task:{iid}:T-1 until")
    assert server.next_work(ctx("other"), initiative_id=iid, kind="task") == "nothing to do"
    assert server.release(f"task:{iid}:T-1", ctx()) == f"released task:{iid}:T-1"
    assert server.drift_report(iid, task="T-1").startswith("drift since B-1 (chandra, draft rev 1) scope T-1: 0 changes")
    assert "## Drift since baseline B-1" in server.drift_report(iid, format="markdown")
    gates = server.gate_status(iid, gate="GATE_PR")
    assert gates.startswith("GATE_PR T-1: BLOCKED") and "!! pr_state_in — T-1" in gates
    assert server.deploy_guard(iid, "T-1", "abc", "staging", ctx()).startswith("NO-GO")
    assert server.inbox("priya").startswith("inbox priya:")
    assert f"task:{iid}:T-1 (task, agent)" in server.worklist(iid)
    assert "created D-1" in server.activity(iid, ref="D-1")
    assert "decision · ref D-n" in server.blueprint("decision")
