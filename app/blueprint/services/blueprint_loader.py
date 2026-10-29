"""Loads and lints blueprint/*.yaml. `python -m app.blueprint.services.blueprint_loader`
(or `make check`) reports every problem at once."""

import functools
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from app.blueprint.schemas.blueprint import (
    AUTHOR_FIELD,
    ActorRule,
    Blueprint,
    CatalogItem,
    FieldSpec,
    Gate,
    GateRuleRef,
    Lifecycle,
    RecordType,
    Rule,
    StatusRule,
)
from config.settings import settings

FIELD_TYPES = {
    "string",
    "markdown",
    "bullets",
    "rows",
    "enum",
    "date",
    "narrative",
    "refs",
    "json",
}
FIELD_KEYS = {
    "type",
    "max",
    "max_items",
    "required",
    "expect",
    "vocab",
    "columns",
    "row_key",
    "material",
    "verbatim",
    "column_vocab",
    "help",
    "actor",
    "targets",
    "link_kind",
}
TYPE_KEYS = {
    "title",
    "plural",
    "line",
    "ref",
    "status",
    "fields",
    "rules",
    "narrated",
    "propagates_to",
    "propagates_on_create",
    "material_statuses",
    "index",
    "scope",
    "post_baseline_cause",
    "actor_rules",
}
REQUIRED_TYPES = (
    "initiative",
    "assignment",
    "draft",
    "decision",
    "gap",
    "acceptance_criterion",
    "task",
    "approval",
    "baseline",
)
RESERVED_LINK_KINDS = {"mentions", "relates", "because_op"}
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class BlueprintError(Exception):
    pass


class BlueprintLoader:
    def __init__(self, directory: Optional[Path] = None):
        self.dir = Path(directory or settings.blueprint.BLUEPRINT_DIR)
        self.problems: List[str] = []

    def load(self) -> Blueprint:
        v = self._yaml(self.dir / "vocab.yaml")
        vocab: Dict[str, List[str]] = v.get("vocab") or {}
        known = {s for values in vocab.values() for s in values}
        pills = {s: c for c, statuses in (v.get("pills") or {}).items() for s in statuses}
        open_statuses = {name: set(values) for name, values in (v.get("open") or {}).items()}
        for name, values in open_statuses.items():
            if name not in vocab:
                self.problems.append(f"vocab.yaml: open.{name}: no such vocabulary")
                continue
            for s in sorted(values - set(vocab[name])):
                self.problems.append(f"vocab.yaml: open.{name}: '{s}' is not in that vocabulary")
        answer_statuses = set(v.get("answers") or [])
        for s in sorted(answer_statuses - known):
            self.problems.append(f"vocab.yaml: answers: status '{s}' is in no vocabulary")

        types = self._types(vocab)
        for need in REQUIRED_TYPES:
            if need not in types:
                self.problems.append(f"objects.yaml: type '{need}' is required")
        lifecycle = self._lifecycle(vocab, types)
        if self.problems:
            raise BlueprintError("\n".join(self.problems))
        return Blueprint(
            vocab=vocab,
            open_statuses=open_statuses,
            answer_statuses=answer_statuses,
            pills=pills,
            types=types,
            lifecycle=lifecycle,
        )

    def _yaml(self, path: Path) -> dict:
        try:
            data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as e:
            raise BlueprintError(f"{path.name}: {e}") from e
        if not isinstance(data, dict):
            raise BlueprintError(f"{path.name}: expected a mapping at the top level")
        return data

    # ── objects.yaml ─────────────────────────────────────────────────────

    def _types(self, vocab: Dict[str, List[str]]) -> Dict[str, RecordType]:
        types: Dict[str, RecordType] = {}
        prefixes: Dict[str, str] = {}
        raw_types = self._yaml(self.dir / "objects.yaml").get("types") or {}
        for key, spec in raw_types.items():
            where = f"objects.yaml: {key}"
            if not KEY_RE.match(str(key)):
                self.problems.append(f"{where}: type key must be snake_case")
            for unknown in sorted(set(spec) - TYPE_KEYS):
                self.problems.append(f"{where}: unknown key '{unknown}'")
            ref = dict(spec.get("ref") or {})
            if len(ref) != 1 or next(iter(ref)) not in ("prefix", "singleton"):
                self.problems.append(f"{where}: ref must be {{prefix: X}} or {{singleton: name}}")
                continue
            ref_kind, ref_value = next(iter(ref.items()))
            if ref_kind == "prefix":
                if not re.match(r"^[A-Z]+$", str(ref_value)):
                    self.problems.append(f"{where}: prefix '{ref_value}' must be upper-case letters")
                if prefixes.setdefault(ref_value, key) != key:
                    self.problems.append(
                        f"{where}: prefix {ref_value} already used by {prefixes[ref_value]}"
                    )
            if spec.get("status") not in vocab:
                self.problems.append(f"{where}: status vocab '{spec.get('status')}' not in vocab.yaml")
            scope = spec.get("scope", "initiative")
            if scope not in ("initiative", "global"):
                self.problems.append(f"{where}: scope must be initiative or global")

            fields: Dict[str, FieldSpec] = {}
            link_kinds: Dict[str, str] = {}
            for name, fs in (spec.get("fields") or {}).items():
                if not isinstance(name, str):
                    self.problems.append(
                        f"{where}: field name {name!r} is not text — YAML reads on/off/yes/no as booleans; quote it"
                    )
                    continue
                if name in ("status", "title", "ref", "type"):
                    self.problems.append(f"{where}.{name}: reserved name (it is a record column)")
                fwhere = f"{where}.{name}"
                for unknown in sorted(str(k) for k in set(fs) - FIELD_KEYS):
                    self.problems.append(f"{fwhere}: unknown key '{unknown}'")
                ftype = fs.get("type")
                if ftype not in FIELD_TYPES:
                    self.problems.append(f"{fwhere}: type '{ftype}' not in {sorted(FIELD_TYPES)}")
                    continue
                if (ftype == "enum" or fs.get("vocab")) and fs.get("vocab") not in vocab:
                    self.problems.append(f"{fwhere}: enum vocab '{fs.get('vocab')}' not in vocab.yaml")
                if ftype == "rows" and not fs.get("columns"):
                    self.problems.append(f"{fwhere}: rows needs columns")
                if fs.get("row_key") and fs["row_key"] not in (fs.get("columns") or []):
                    self.problems.append(f"{fwhere}: row_key must be one of its columns")
                for column, vocab_name in (fs.get("column_vocab") or {}).items():
                    if column not in (fs.get("columns") or []) or vocab_name not in vocab:
                        self.problems.append(
                            f"{fwhere}: column_vocab {column}: {vocab_name} names an unknown column or vocabulary"
                        )
                if fs.get("actor") not in (None, "human"):
                    self.problems.append(f"{fwhere}: actor must be 'human' when set")
                targets = tuple(fs.get("targets") or ())
                link_kind = None
                if ftype == "refs":
                    if not targets:
                        self.problems.append(f"{fwhere}: refs needs targets")
                    for target in targets:
                        if target != "external" and target not in raw_types:
                            self.problems.append(f"{fwhere}: target '{target}' is not a record type")
                    link_kind = fs.get("link_kind") or name
                    if link_kind in RESERVED_LINK_KINDS:
                        self.problems.append(f"{fwhere}: link_kind '{link_kind}' is reserved")
                    if link_kinds.setdefault(link_kind, name) != name:
                        self.problems.append(
                            f"{fwhere}: link_kind '{link_kind}' already used by field {link_kinds[link_kind]}"
                        )
                elif targets or fs.get("link_kind"):
                    self.problems.append(f"{fwhere}: targets/link_kind only apply to refs fields")
                fields[name] = FieldSpec(
                    name=name,
                    type=ftype,
                    max=fs.get("max"),
                    max_items=fs.get("max_items"),
                    required=bool(fs.get("required")),
                    expect=bool(fs.get("expect")),
                    vocab=fs.get("vocab"),
                    columns=tuple(fs.get("columns") or ()),
                    row_key=fs.get("row_key"),
                    material=bool(fs.get("material")),
                    verbatim=bool(fs.get("verbatim")),
                    column_vocab=tuple((fs.get("column_vocab") or {}).items()),
                    help=(fs.get("help") or "").strip(),
                    actor=fs.get("actor"),
                    targets=targets,
                    link_kind=link_kind,
                )

            rules = []
            for r in spec.get("rules") or []:
                require = tuple(r.get("require") or ())
                for n in require:
                    if n not in fields:
                        self.problems.append(f"{where}: rule requires unknown field '{n}'")
                when = dict(r.get("when") or {})
                statuses = tuple(when.pop("status", ()))
                for s in statuses:
                    if s not in vocab.get(spec.get("status"), []):
                        self.problems.append(f"{where}: rule tests unknown status '{s}'")
                for n in when:
                    if n not in fields:
                        self.problems.append(f"{where}: rule tests unknown field '{n}'")
                rules.append(Rule(statuses, require, tuple((n, tuple(v)) for n, v in when.items())))

            actor_rules = []
            for r in spec.get("actor_rules") or []:
                when = dict(r.get("when") or {})
                human = tuple(r.get("human") or ())
                for n in list(when) + list(human):
                    if n not in fields and not (n == AUTHOR_FIELD and n in when):
                        self.problems.append(f"{where}: actor_rules names unknown field '{n}'")
                actor_rules.append(ActorRule(tuple((n, tuple(v)) for n, v in when.items()), human))

            line = spec.get("line")
            if line and line not in fields:
                self.problems.append(f"{where}: line field '{line}' is not a field")
            index = spec.get("index") or {}
            types[key] = RecordType(
                key=key,
                title=spec.get("title", key),
                plural=spec.get("plural", key),
                ref_kind=ref_kind,
                ref_value=str(ref_value),
                status_vocab=spec.get("status", ""),
                line=line,
                fields=fields,
                rules=tuple(rules),
                scope=scope,
                narrated=bool(spec.get("narrated")),
                propagates_to=tuple(spec.get("propagates_to") or ()),
                propagates_on_create=tuple(spec.get("propagates_on_create") or ()),
                material_statuses=tuple(spec.get("material_statuses") or ()),
                post_baseline_cause=bool(spec.get("post_baseline_cause")),
                actor_rules=tuple(actor_rules),
                index_facets=tuple(index.get("facets") or ()),
                index_columns=tuple(index.get("columns") or ()),
                index_newest_first=bool(index.get("newest_first")),
            )
        for t in types.values():
            for name in t.index_facets + t.index_columns:
                if name not in t.fields:
                    self.problems.append(f"objects.yaml: {t.key}: index names unknown field '{name}'")
            for target in t.propagates_to:
                if target not in types:
                    self.problems.append(f"objects.yaml: {t.key}: propagates_to '{target}' is not a record type")
            for s in t.propagates_on_create + t.material_statuses:
                if s not in vocab.get(t.status_vocab, []):
                    self.problems.append(f"objects.yaml: {t.key}: status '{s}' not in {t.status_vocab}")
        return types

    # ── lifecycle.yaml ───────────────────────────────────────────────────

    def _lifecycle(self, vocab, types: Dict[str, RecordType]) -> Optional[Lifecycle]:
        path = self.dir / "lifecycle.yaml"
        if not path.exists():
            self.problems.append("lifecycle.yaml: missing")
            return None
        raw = self._yaml(path)
        phases = list(raw.get("phases") or [])
        roles = list(raw.get("roles") or [])
        if roles != list(vocab.get("role", [])):
            self.problems.append("lifecycle.yaml: roles must equal vocab.role")

        status_rules: Dict[str, StatusRule] = {}
        for type_key, spec in (raw.get("status_rules") or {}).items():
            if type_key not in types:
                self.problems.append(f"lifecycle.yaml: status_rules.{type_key}: not a record type")
                continue
            spec = dict(spec or {})
            rule = spec.pop("rule", None)
            text = spec.pop("text", "")
            if not rule:
                self.problems.append(f"lifecycle.yaml: status_rules.{type_key}: needs a rule name")
                continue
            status_rules[type_key] = StatusRule(type_key, rule, text, spec)
        for type_key in types:
            if type_key not in status_rules:
                self.problems.append(f"lifecycle.yaml: type '{type_key}' has no status rule (every status is derived)")

        catalogs: Dict[str, List[CatalogItem]] = {}
        for phase, items in (raw.get("catalogs") or {}).items():
            if phase not in phases:
                self.problems.append(f"lifecycle.yaml: catalogs.{phase}: not a phase")
            catalogs[phase] = [
                CatalogItem(
                    item=i["item"], phase=phase, text=i.get("text", ""), derived=bool(i.get("derived"))
                )
                for i in items or []
            ]

        gates: Dict[str, Gate] = {}
        for key, g in (raw.get("gates") or {}).items():
            refs = []
            for entry in g.get("all_of") or []:
                if isinstance(entry, str):
                    refs.append(GateRuleRef(entry, {}))
                elif isinstance(entry, dict) and len(entry) == 1:
                    name, args = next(iter(entry.items()))
                    refs.append(GateRuleRef(name, dict(args or {})))
                else:
                    self.problems.append(f"lifecycle.yaml: gates.{key}: rule entry {entry!r} must be a name or {{name: args}}")
            human = g.get("human")
            if human and human not in roles:
                self.problems.append(f"lifecycle.yaml: gates.{key}: human '{human}' is not a role")
            if g.get("scope") not in ("initiative", "task"):
                self.problems.append(f"lifecycle.yaml: gates.{key}: scope must be initiative or task")
            for r in refs:
                if r.name == "approval_by_role" and r.args.get("role") not in roles:
                    self.problems.append(f"lifecycle.yaml: gates.{key}: approval role '{r.args.get('role')}' is not a role")
                if r.name == "catalog_addressed" and r.args.get("phase") not in phases:
                    self.problems.append(f"lifecycle.yaml: gates.{key}: catalog phase '{r.args.get('phase')}' is not a phase")
            gates[key] = Gate(
                key=key,
                scope=g.get("scope", "initiative"),
                text=g.get("text", ""),
                rules=tuple(refs),
                human=human,
                on_pass=g.get("on_pass"),
            )

        routing = raw.get("routing") or {}
        for domain, role in (routing.get("by_domain") or {}).items():
            if domain not in vocab.get("domain", []):
                self.problems.append(f"lifecycle.yaml: routing.by_domain: '{domain}' is not a domain")
            if role not in roles:
                self.problems.append(f"lifecycle.yaml: routing.by_domain.{domain}: '{role}' is not a role")
        for name in ("fallback", "escalate_to"):
            if routing.get(name) and routing[name] not in roles:
                self.problems.append(f"lifecycle.yaml: routing.{name}: '{routing[name]}' is not a role")

        lifecycle = Lifecycle(
            phases=phases,
            roles=roles,
            status_rules=status_rules,
            catalogs=catalogs,
            gates=gates,
            deploy_guard=raw.get("deploy_guard") or {},
            routing=routing,
            handoff={k: int(v) for k, v in (raw.get("handoff") or {}).items()},
        )
        self._lint_rule_code(lifecycle, vocab, types)
        return lifecycle

    def _lint_rule_code(self, lifecycle: Lifecycle, vocab, types) -> None:
        """Every YAML rule has an implementation and every implementation a YAML entry."""
        from app.initiatives.services.gate_rules import GATE_RULES
        from app.initiatives.services.status_rules import STATUS_RULES

        used_status = {r.rule for r in lifecycle.status_rules.values()}
        for r in lifecycle.status_rules.values():
            if r.rule not in STATUS_RULES:
                self.problems.append(f"lifecycle.yaml: status rule '{r.rule}' ({r.type}) has no implementation in status_rules.py")
            else:
                produces = STATUS_RULES[r.rule].produces
                vocab_name = types[r.type].status_vocab
                extra = [s for s in produces if s not in vocab.get(vocab_name, []) and s != "*"]
                if extra and "*" not in produces:
                    self.problems.append(f"lifecycle.yaml: status rule '{r.rule}' can produce {extra}, not in {vocab_name}")
        for name in sorted(set(STATUS_RULES) - used_status):
            self.problems.append(f"status_rules.py: '{name}' is implemented but no lifecycle.yaml status_rules entry uses it")

        used_gate = {r.name for g in lifecycle.gates.values() for r in g.rules}
        for name in sorted(used_gate - set(GATE_RULES)):
            self.problems.append(f"lifecycle.yaml: gate rule '{name}' has no implementation in gate_rules.py")
        for name in sorted(set(GATE_RULES) - used_gate):
            self.problems.append(f"gate_rules.py: '{name}' is implemented but no gate in lifecycle.yaml uses it")


@functools.lru_cache(maxsize=1)
def get_blueprint() -> Blueprint:
    return BlueprintLoader().load()


def main() -> int:
    try:
        bp = BlueprintLoader().load()
    except BlueprintError as e:
        print(e, file=sys.stderr)
        return 1
    lc = bp.lifecycle
    print(f"types ({len(bp.types)}): {', '.join(bp.types)}")
    print(f"phases: {' → '.join(lc.phases)}")
    for t in bp.types.values():
        rule = lc.status_rules[t.key]
        flags = [
            f"scope={t.scope}" if t.scope != "initiative" else "",
            "post_baseline_cause" if t.post_baseline_cause else "",
            f"human: {', '.join(sorted(f.name for f in t.fields.values() if f.actor == 'human'))}"
            if any(f.actor == "human" for f in t.fields.values())
            else "",
        ]
        print(f"  {t.key:<22} status={rule.rule:<18} {' · '.join(f for f in flags if f)}")
    for g in lc.gates.values():
        print(f"  gate {g.key:<16} {g.scope:<10} {len(g.rules)} rules" + (f" · human: {g.human}" if g.human else ""))
    print("blueprint OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
