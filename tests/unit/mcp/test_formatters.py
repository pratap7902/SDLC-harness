from app.blueprint.services.blueprint_loader import get_blueprint
from app.initiatives.schemas.write import OpResult, WriteResult
from app.mcp import formatters as fmt


def test_type_spec_flags_human_only_material_and_links():
    text = fmt.type_spec(get_blueprint(), get_blueprint().types["gap"])
    assert "answer: markdown, material, HUMAN-ONLY" in text
    assert "blocks: refs → decision | draft | task | acceptance_criterion (link blocks)" in text
    assert "status DERIVED OPEN | ANSWERED | WITHDRAWN" in text
    decision = fmt.type_spec(get_blueprint(), get_blueprint().types["decision"])
    assert "when level = MUST: HUMAN-ONLY verdict" in decision


def test_write_text_rejected_and_ok():
    bad = WriteResult(ok=False, batch_id="b", results=[OpResult(index=0, ref="D-1", errors=["verdict: human-only"])])
    assert fmt.write_text(bad).splitlines() == ["REJECTED — nothing was saved. Fix and resend the whole batch:", "op 0 D-1:", "  - verdict: human-only"]
    ok = WriteResult(
        ok=True,
        batch_id="b",
        results=[OpResult(index=0, ref="B-1", action="created", rev=1, status="CURRENT")],
        baseline="B-1",
        gates_changed=[{"gate": "GATE_DRAFT", "task": None, "before": "BLOCKED", "after": "PASSED"}],
        review_items=["D-2 ← G-1: status OPEN → ANSWERED (→ priya)"],
    )
    lines = fmt.write_text(ok).splitlines()
    assert lines[0] == "B-1 created rev 1 [CURRENT]"
    assert "gate GATE_DRAFT: BLOCKED → PASSED" in lines
    assert lines[-1] == "  D-2 ← G-1: status OPEN → ANSWERED (→ priya)"


def test_items_text_and_clip():
    assert fmt.clip("a  b\nc", 0) == "a b c"
    assert fmt.clip("abcdef", 4) == "abc…"
    out = fmt.items_text([{"key": "task:x:T-1", "kind": "task", "lane": "agent", "title": "t", "why": "w", "lease": {"holder": "r"}, "person": None}])
    assert out == "task:x:T-1 (task, agent) [held by r]: t — w"
