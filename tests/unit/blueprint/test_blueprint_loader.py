import shutil
from pathlib import Path

import pytest
import yaml

from app.blueprint.services.blueprint_loader import BlueprintError, BlueprintLoader

REAL = Path(__file__).resolve().parents[3] / "blueprint"


def copy(tmp_path) -> Path:
    for f in ("vocab.yaml", "objects.yaml", "lifecycle.yaml"):
        shutil.copy(REAL / f, tmp_path / f)
    return tmp_path


def edit(path: Path, fn) -> None:
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def problems(tmp_path) -> str:
    with pytest.raises(BlueprintError) as e:
        BlueprintLoader(tmp_path).load()
    return str(e.value)


def test_the_real_blueprint_loads():
    bp = BlueprintLoader(REAL).load()
    assert "decision" in bp.types and bp.lifecycle.gates["GATE_PR"].scope == "task"
    assert bp.type_of_ref("AC-12") == "acceptance_criterion"
    assert bp.type_of_ref("draft") == "draft"
    assert bp.type_of_ref("XX-1") is None
    assert bp.types["gap"].human_fields({}) == {"answer", "answered_by", "answered_on", "assigned_to", "assigned_role", "answered_for", "choice"}
    assert "verdict" in bp.types["decision"].human_fields({"level": "MUST"})
    assert "verdict" not in bp.types["decision"].human_fields({"level": "SHOULD"})
    assert bp.types["decision"].fields["supersedes"].link_kind == "supersedes"


def test_every_type_needs_a_status_rule(tmp_path):
    copy(tmp_path)
    edit(tmp_path / "lifecycle.yaml", lambda d: d["status_rules"].pop("gap"))
    assert "type 'gap' has no status rule" in problems(tmp_path)


def test_a_yaml_rule_needs_code_and_code_needs_yaml(tmp_path):
    copy(tmp_path)
    edit(tmp_path / "lifecycle.yaml", lambda d: d["gates"]["GATE_PR"]["all_of"].append("no_friday_deploys"))
    text = problems(tmp_path)
    assert "gate rule 'no_friday_deploys' has no implementation" in text

    copy(tmp_path)
    edit(tmp_path / "lifecycle.yaml", lambda d: d["gates"]["GATE_VALIDATED"]["all_of"].remove("no_blocker_finding_open"))
    assert "'no_blocker_finding_open' is implemented but no gate in lifecycle.yaml uses it" in problems(tmp_path)


def test_gate_roles_catalog_phases_and_link_targets_are_checked(tmp_path):
    copy(tmp_path)

    def broken(d):
        d["gates"]["GATE_DRAFT"]["human"] = "cto"
        d["catalogs"]["deploy"] = []

    edit(tmp_path / "lifecycle.yaml", broken)
    edit(tmp_path / "objects.yaml", lambda d: d["types"]["task"]["fields"]["implements"].update(targets=["adr"]))
    text = problems(tmp_path)
    assert "human 'cto' is not a role" in text
    assert "catalogs.deploy: not a phase" in text
    assert "target 'adr' is not a record type" in text


def test_unknown_field_keys_and_reserved_names(tmp_path):
    copy(tmp_path)

    def broken(d):
        d["types"]["gap"]["fields"]["status"] = {"type": "string"}
        d["types"]["gap"]["fields"]["question"]["maxx"] = 3

    edit(tmp_path / "objects.yaml", broken)
    text = problems(tmp_path)
    assert "gap.status: reserved name" in text
    assert "gap.question: unknown key 'maxx'" in text
