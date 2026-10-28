from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WriteOp:
    """One record upsert. `ref` omitted = mint the next ref for `type` (or the singleton).
    `fields` merges into the record; a null value removes that field; lists replace whole.
    `#<n>` anywhere a ref goes (refs fields, link) = the ref op n of this batch produced.
    `status` is refused: every status is derived."""

    ref: Optional[str] = None
    type: Optional[str] = None
    title: Optional[str] = None
    fields: Dict[str, Any] = field(default_factory=dict)
    link: List[str] = field(default_factory=list)
    unlink: List[str] = field(default_factory=list)
    note: str = ""
    base_rev: Optional[int] = None
    because: List[str] = field(default_factory=list)
    # "I re-read this against what changed and it still stands": closes its open review
    # items as `upheld` without changing a value. Needs a note.
    reviewed: bool = False
    status: Optional[str] = None  # refused — present only so the error can say why

    def canonical(self) -> dict:
        return asdict(self)


@dataclass
class OpResult:
    index: int
    ref: Optional[str]
    type: Optional[str] = None
    action: str = "error"  # created | updated | unchanged | noted | reviewed | error | not saved
    rev: Optional[int] = None
    status: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class WriteResult:
    ok: bool
    batch_id: str
    results: List[OpResult]
    minted: Dict[str, str] = field(default_factory=dict)  # "#0" → "D-1"
    review_items: List[str] = field(default_factory=list)  # "<target> ← <cause>: <what moved>"
    stale: List[str] = field(default_factory=list)
    gates_changed: List[Dict[str, Any]] = field(default_factory=list)
    baseline: Optional[str] = None
    replayed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WriteResult":
        data = dict(data)
        data["results"] = [OpResult(**r) for r in data.get("results") or []]
        return cls(**data)
