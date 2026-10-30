import datetime as dt
import difflib
import re
from typing import Any, Dict, List, Optional

from app.blueprint.schemas.blueprint import EXTERNAL_PREFIX, KB_CITATION_RE, Blueprint, FieldSpec

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEXT_TYPES = ("string", "markdown", "narrative", "enum", "date")
TITLE_MAX = 300
BATCH_REF_RE = re.compile(r"^#\d+$")


class RecordValidator:
    """Checks one record (its full, merged state) against its blueprint type. Returns every
    problem as `field: what is wrong`, so a writer can fix them in one pass.

    `refs` items are checked for SHAPE here (a ref of a target type, or `external:<url>`);
    whether the record exists in scope is the write path's job."""

    def __init__(self, blueprint: Blueprint):
        self.bp = blueprint

    def validate(
        self,
        type_key: str,
        ref: str,
        title: str,
        status: Optional[str],
        fields: Dict[str, Any],
        rules: bool = True,
    ) -> List[str]:
        """`status` None: not derived yet, so status-conditioned rules are skipped."""
        t = self.bp.types[type_key]
        errors: List[str] = []
        if not title or not title.strip():
            errors.append("title: required")
        elif len(title) > TITLE_MAX:
            errors.append(f"title: exceeds {TITLE_MAX} chars ({len(title)})")

        for name, value in fields.items():
            spec = t.fields.get(name)
            if spec is None:
                errors.append(f"{name}: unknown field for {type_key}; valid: {', '.join(t.fields)}")
                continue
            errors.extend(self._value(spec, value))

        required = {f.name for f in t.fields.values() if f.required}
        because = {}
        if rules:
            for rule in t.rules:
                if rule.statuses and status is None:
                    continue
                if rule.applies(status, fields):
                    required |= set(rule.require)
                    for name in rule.require:
                        because[name] = " and ".join(
                            ([f"status={status}"] if rule.statuses else [])
                            + [f"{n}={fields.get(n)}" for n, _ in rule.fields]
                        )
        for name in sorted(required):
            if _empty(fields.get(name)):
                why = "" if t.fields[name].required else f" when {because.get(name, '')}"
                errors.append(f"{name}: required{why}")
        return errors

    def rule_errors(self, type_key: str, status: str, fields: Dict[str, Any]) -> List[str]:
        """Only the status-conditioned rules — run once the status has been derived."""
        t = self.bp.types[type_key]
        errors = []
        for rule in t.rules:
            if not rule.statuses or not rule.applies(status, fields):
                continue
            for name in rule.require:
                if _empty(fields.get(name)):
                    errors.append(f"{name}: required when status={status}")
        return errors

    def _value(self, f: FieldSpec, value: Any) -> List[str]:
        n = f.name
        if f.type in TEXT_TYPES:
            if not isinstance(value, str):
                return [f"{n}: expected text, got {type(value).__name__}"]
            out = []
            if f.type == "string" and "\n" in value.strip():
                out.append(f"{n}: one line only")
            if f.max and len(value) > f.max:
                out.append(_too_long(n, value, f.max))
            if f.type == "enum" and value not in self.bp.vocab[f.vocab]:
                out.append(f"{n}: '{value}' not in {' | '.join(self.bp.vocab[f.vocab])}")
            if f.type == "date" and not _is_date(value):
                out.append(f"{n}: expected YYYY-MM-DD")
            return out
        if f.type == "bullets":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                return [f"{n}: expected a list of strings"]
            out = []
            if f.max_items and len(value) > f.max_items:
                out.append(f"{n}: at most {f.max_items} items ({len(value)})")
            if f.max:
                out += [_too_long(f"{n}[{i}]", v, f.max) for i, v in enumerate(value) if len(v) > f.max]
            return out
        if f.type == "refs":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                return [f"{n}: expected a list of refs, e.g. [\"D-1\"]"]
            out = []
            for i, item in enumerate(value):
                if BATCH_REF_RE.match(item):
                    continue  # resolved by the write path before the existence check
                if item.startswith(EXTERNAL_PREFIX):
                    if "external" not in f.targets:
                        out.append(f"{n}[{i}]: external refs are not allowed here; name a {' | '.join(f.targets)}")
                    elif item.startswith("kb:") and not KB_CITATION_RE.match(item):
                        out.append(f"{n}[{i}]: '{item}' is not a citation — kb:<source>/<doc-id>[#anchor], as kb_search returns")
                    continue
                type_key = self.bp.type_of_ref(item)
                if type_key is None or type_key not in f.targets:
                    allowed = " | ".join(self._shape(t) for t in f.targets)
                    out.append(f"{n}[{i}]: '{item}' is not a {' or '.join(f.targets)} ref — expected {allowed}")
            if len(set(value)) != len(value):
                out.append(f"{n}: duplicate refs")
            return out
        if f.type == "json":
            if not isinstance(value, (dict, list)):
                return [f"{n}: expected a JSON object"]
            return []
        if f.type == "rows":
            if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
                return [f"{n}: expected a list of objects with keys {', '.join(f.columns)}"]
            out = []
            vocab = dict(f.column_vocab)
            seen = set()
            for i, row in enumerate(value):
                if f.row_key:
                    key = row.get(f.row_key)
                    if not key:
                        out.append(f"{n}[{i}]: '{f.row_key}' is required")
                    elif key in seen:
                        out.append(f"{n}[{i}]: duplicate {f.row_key} '{key}'")
                    seen.add(key)
                for column, vocab_name in vocab.items():
                    if column in row and row[column] not in self.bp.vocab[vocab_name]:
                        out.append(
                            f"{n}[{i}].{column}: '{row[column]}' not in {' | '.join(self.bp.vocab[vocab_name])}"
                        )
                extra = sorted(set(row) - set(f.columns))
                if extra:
                    out.append(f"{n}[{i}]: unknown column(s) {', '.join(extra)}; valid: {', '.join(f.columns)}")
                out += [f"{n}[{i}].{k}: expected text" for k, v in row.items() if not isinstance(v, str)]
            return out
        return []

    def _shape(self, type_key: str) -> str:
        if type_key == "external":
            return "external:<url> | kb:<source>/<doc-id>[#anchor]"
        t = self.bp.types[type_key]
        return f"{t.ref_value}-n" if t.ref_kind == "prefix" else f"'{t.ref_value}'"


def _too_long(name: str, value: str, limit: int) -> str:
    """Says where the limit falls, so the writer can cut without guessing."""
    kept = value[max(0, limit - 30) : limit].replace("\n", " ")
    return (
        f"{name}: exceeds {limit} chars ({len(value)}) — over by {len(value) - limit}; "
        f'the limit falls right after "…{kept}"'
    )


def nearest_status(status: str, allowed) -> str:
    close = difflib.get_close_matches(status.upper(), list(allowed), n=1, cutoff=0.75)
    return close[0] if close else ""


def _is_date(value: str) -> bool:
    if not DATE_RE.match(value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
