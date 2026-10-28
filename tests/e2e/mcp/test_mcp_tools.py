"""The MCP tools call the same services as REST and answer in compact text."""

from types import SimpleNamespace

import pytest

from app.mcp import server
from tests.fixtures.slice import SLUG, draft_batch, task_op


def ctx(person="runner-sdk"):
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={"x-actor": person})))


@pytest.fixture
def started(client):
    server.create_initiative(title="Order events outbox", requirement="# Order events", dri="chandra", engg="priya", ctx=ctx(), slug=SLUG, product="maya")
    return SLUG


def test_create_write_and_read(started):
    out = server.write(SLUG, draft_batch(), ctx(), batch_id="m-1", agent="draft-skill")
    assert out.splitlines()[0] == "D-1 created rev 1 [DECIDED]"
    again = server.write(SLUG, draft_batch(), ctx(), batch_id="m-1", agent="draft-skill")
    assert again.startswith("(batch m-1 replayed")
    state = server.get_state(SLUG)
    assert "GATE_DRAFT: BLOCKED — failing no_open_gap_blocking_draft, approval_by_role" in state
    full = server.read_record(SLUG, ["G-1"], history=True)
    assert "links out: blocks D-2" in full and "(agent)" in full
    assert "D-1 [DECIDED]" in server.search_records(SLUG, type="decision")


def test_a_rejected_write_explains_every_error(started):
    with pytest.raises(ValueError) as e:
        server.write(SLUG, '[{"ref": "draft", "status": "APPROVED"}]', ctx())
    assert "REJECTED — nothing was saved" in str(e.value) and "status: derived" in str(e.value)
    with pytest.raises(ValueError) as e:
        server.write(SLUG, [{"type": "gap", "fields": {"answer": "x"}}], ctx())
    assert "answer: human-only" in str(e.value)


def test_no_human_only_tools():
    names = set(server.mcp._tool_manager._tools)
    assert not names & {"answer_gap", "approve", "rule_decision", "sign_manual_ac", "promote_learning"}
    assert {"next_work", "claim", "drift_report", "deploy_guard", "gate_status", "inbox"} <= names


def test_work_loop_and_reports(started, api):
    server.write(SLUG, draft_batch(), ctx())
    api.answer(SLUG, "G-1", choice="yes", person="maya")
    server.write(SLUG, [{"ref": "D-2", "reviewed": True, "note": "holds"}], ctx())
    api.approve(SLUG, "draft", "dri", "chandra")
    server.write(SLUG, [task_op()], ctx())
    work = server.next_work(ctx(), initiative=SLUG, kind="task")
    assert work.startswith(f"task:{SLUG}:T-1 (task, agent)")
    assert "cites D-1 [DECIDED]" in work
    assert server.claim(f"task:{SLUG}:T-1", ctx()).startswith(f"claimed task:{SLUG}:T-1 until")
    assert server.next_work(ctx("other"), initiative=SLUG, kind="task") == "nothing to do"
    assert server.release(f"task:{SLUG}:T-1", ctx()) == f"released task:{SLUG}:T-1"
    assert server.drift_report(SLUG, task="T-1").startswith("drift since B-1 (chandra, draft rev 1) scope T-1: 0 changes")
    assert "## Drift since baseline B-1" in server.drift_report(SLUG, format="markdown")
    gates = server.gate_status(SLUG, gate="GATE_PR")
    assert gates.startswith("GATE_PR T-1: BLOCKED") and "!! pr_state_in — T-1" in gates
    assert server.deploy_guard(SLUG, "T-1", "abc", "staging", ctx()).startswith("NO-GO")
    assert server.inbox("priya").startswith("inbox priya:")
    assert f"task:{SLUG}:T-1 (task, agent)" in server.worklist(SLUG)
    assert "created D-1" in server.activity(SLUG, ref="D-1")
    assert "decision · ref D-n" in server.blueprint("decision")
