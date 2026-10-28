"""In-memory shape of blueprint/*.yaml. Built once by BlueprintLoader."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

PREFIXED_REF_RE = re.compile(r"^([A-Z]+)-(\d+)$")
EXTERNAL_PREFIX = "external:"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    max: Optional[int] = None
    max_items: Optional[int] = None
    required: bool = False
    expect: bool = False
    vocab: Optional[str] = None
    columns: Tuple[str, ...] = ()
    row_key: Optional[str] = None
    column_vocab: Tuple[Tuple[str, str], ...] = ()
    help: str = ""
    # A change to this field can invalidate what rests on the record (a decision's verdict).
    material: bool = False
    # Quoted word for word (a conversation): text search may skip it.
    verbatim: bool = False
    # `human` → only an actor of kind human may write it ("agents ask, humans answer").
    actor: Optional[str] = None
    # `refs` fields: the record types (or `external`) each item may name.
    targets: Tuple[str, ...] = ()
    # `refs` fields: the kind of the typed link each item becomes (default: field name).
    link_kind: Optional[str] = None


@dataclass(frozen=True)
class Rule:
    statuses: Tuple[str, ...]  # empty = any status
    require: Tuple[str, ...]
    fields: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()

    def applies(self, status: Optional[str], values: dict) -> bool:
        return (not self.statuses or status in self.statuses) and all(
            values.get(name) in allowed for name, allowed in self.fields
        )


@dataclass(frozen=True)
class ActorRule:
    """`when: {escalated: [yes]}, human: [verdict]` — conditional human-only fields."""

    fields: Tuple[Tuple[str, Tuple[str, ...]], ...]
    human: Tuple[str, ...]

    def applies(self, values: dict) -> bool:
        return all(values.get(name) in allowed for name, allowed in self.fields)


@dataclass(frozen=True)
class RecordType:
    key: str
    title: str
    plural: str
    ref_kind: str  # prefix | singleton
    ref_value: str
    status_vocab: str
    line: Optional[str]
    fields: Dict[str, FieldSpec]
    rules: Tuple[Rule, ...]
    scope: str = "initiative"  # initiative | global
    narrated: bool = False
    propagates_to: Tuple[str, ...] = ()
    propagates_on_create: Tuple[str, ...] = ()
    material_statuses: Tuple[str, ...] = ()
    post_baseline_cause: bool = False
    actor_rules: Tuple[ActorRule, ...] = ()
    index_facets: Tuple[str, ...] = ()
    index_columns: Tuple[str, ...] = ()
    index_newest_first: bool = False

    def human_fields(self, values: dict) -> set:
        """Fields only a human may write, given the record's (merged) values."""
        out = {f.name for f in self.fields.values() if f.actor == "human"}
        for rule in self.actor_rules:
            if rule.applies(values):
                out |= set(rule.human)
        return out

    def refs_fields(self) -> List[FieldSpec]:
        return [f for f in self.fields.values() if f.type == "refs"]


@dataclass(frozen=True)
class StatusRule:
    type: str
    rule: str
    text: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogItem:
    item: str
    phase: str
    text: str
    derived: bool = False


@dataclass(frozen=True)
class GateRuleRef:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Gate:
    key: str
    scope: str  # initiative | task
    text: str
    rules: Tuple[GateRuleRef, ...]
    human: Optional[str] = None
    on_pass: Optional[str] = None


@dataclass
class Lifecycle:
    phases: List[str]
    roles: List[str]
    status_rules: Dict[str, StatusRule]
    catalogs: Dict[str, List[CatalogItem]]
    gates: Dict[str, Gate]
    deploy_guard: Dict[str, Any]
    routing: Dict[str, Any]
    handoff: Dict[str, int]

    def sla_hours(self, kind: str) -> int:
        return int((self.routing.get("sla_hours") or {}).get(kind, 24))


@dataclass
class Blueprint:
    vocab: Dict[str, List[str]]
    open_statuses: Dict[str, set]
    answer_statuses: set
    pills: Dict[str, str]
    types: Dict[str, RecordType]
    lifecycle: Optional[Lifecycle] = None

    def pill(self, status: str) -> str:
        return self.pills.get(status, "grey")

    def prefixes(self) -> Dict[str, str]:
        return {
            t.ref_value: t.key for t in self.types.values() if t.ref_kind == "prefix"
        }

    def singletons(self) -> Dict[str, str]:
        return {
            t.ref_value: t.key for t in self.types.values() if t.ref_kind == "singleton"
        }

    def type_of_ref(self, ref: str) -> Optional[str]:
        """The record type a ref belongs to, from its shape alone."""
        if ref in self.singletons():
            return self.singletons()[ref]
        m = PREFIXED_REF_RE.match(ref or "")
        if m and m.group(1) in self.prefixes():
            return self.prefixes()[m.group(1)]
        return None

    def is_open(self, type_key: str, status: str) -> bool:
        return status in self.open_for(type_key)

    def open_for(self, type_key: str) -> set:
        return self.open_statuses.get(self.types[type_key].status_vocab, set())

    def ordered_fields(self, type_key: str, fields: dict) -> dict:
        """Stored fields in blueprint order — MySQL's JSON type does not keep key order."""
        spec = self.types[type_key].fields
        return {name: fields[name] for name in spec if name in (fields or {})}

    def spec_types(self) -> List[str]:
        """Types whose post-baseline edits must be explained (the spec)."""
        return [t.key for t in self.types.values() if t.post_baseline_cause]
