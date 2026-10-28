from app.blueprint.services.blueprint_loader import get_blueprint
from app.blueprint.services.record_validator import RecordValidator


def v():
    return RecordValidator(get_blueprint())


def test_required_fields_and_title():
    errors = v().validate("gap", "G-1", "", None, {"question": "Why?"})
    assert "title: required" in errors
    for name in ("kind", "domain", "asked_by", "why_now", "context"):
        assert f"{name}: required" in errors


def test_enum_max_and_one_line():
    errors = v().validate("decision", "D-1", "t", None, {"question": "q\nsecond", "domain": "ops", "level": "MUST", "verdict": "x" * 500})
    assert "question: one line only" in errors
    assert "domain: 'ops' not in product | design | engg" in errors
    assert any(e.startswith("verdict: exceeds 450 chars (500) — over by 50") for e in errors)


def test_refs_shape_targets_and_external():
    errors = v().validate(
        "decision", "D-2", "t", None,
        {"question": "q", "domain": "engg", "level": "SHOULD", "supersedes": ["AC-1", "D-1", "D-1"], "cites": ["external:https://adr.io/1", "STD-3"]},
    )
    assert any(e.startswith("supersedes[0]: 'AC-1' is not a decision ref") for e in errors)
    assert "supersedes: duplicate refs" in errors
    assert not any(e.startswith("cites") for e in errors)
    errors = v().validate("acceptance_criterion", "AC-1", "t", None, {"text": "x", "level": "unit", "source": ["external:https://x"]})
    assert any("external refs are not allowed here" in e for e in errors)


def test_batch_refs_pass_shape_checks():
    assert v().validate("acceptance_criterion", "AC-1", "t", None, {"text": "x", "level": "unit", "source": ["#0"]}) == []


def test_rows_columns_and_column_vocab():
    errors = v().validate(
        "initiative", "initiative", "t", None,
        {"catalog": [{"item": "a", "disposition": "maybe"}, {"item": "a"}, {"item": "b", "extra": "x"}]},
    )
    assert "catalog[0].disposition: 'maybe' not in addressed | not_applicable" in errors
    assert "catalog[1]: duplicate item 'a'" in errors
    assert any(e.startswith("catalog[2]: unknown column(s) extra") for e in errors)


def test_field_conditioned_rules_run_before_status_is_known():
    errors = v().validate("decision", "D-1", "t", None, {"question": "q", "domain": "engg", "level": "SHOULD", "provisional": "yes"})
    assert "verdict: required when provisional=yes" in errors
    assert v().rule_errors("decision", "DECIDED", {"verdict": "x"}) == [
        "decided_by: required when status=DECIDED",
        "decided_on: required when status=DECIDED",
        "rationale: required when status=DECIDED",
    ]


def test_unknown_field_and_date():
    errors = v().validate("decision", "D-1", "t", None, {"question": "q", "domain": "engg", "level": "SHOULD", "decided_on": "31/10/2026", "colour": "red"})
    assert "decided_on: expected YYYY-MM-DD" in errors
    assert any(e.startswith("colour: unknown field for decision") for e in errors)
