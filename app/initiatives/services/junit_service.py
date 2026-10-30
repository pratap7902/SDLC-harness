"""JUnit ingestion: CI (or the runner) posts a JUnit XML report for one task at one commit;
the service turns it into ONE `test_run` record bound to that sha, with a `covers` row per
acceptance criterion the test names mention (`AC-3`, `AC_3`, `test_AC_3_…`, `testAc3…`).

That record is what GATE_PR (`every_covered_ac_has_a_test`), GATE_VALIDATED (`every_ac_green`)
and the deploy guard read — evidence counts only at the sha it ran on. It goes through
`RecordService.write` as the caller (an agent / CI token), so it is idempotent by batch_id
(derived from task + sha + run_url + the report's digest: a CI retry of the same upload is a
replay, never a second run)."""

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.utils.actor import Actor
from app.core.utils.time import utcnow
from app.exceptions import NotFoundException, ValidationException
from app.initiatives.services.record_service import RecordService, parse_op
from app.initiatives.services.status_rules import LIVE_AC

MAX_XML_BYTES = 5_000_000
# AC-3 · AC_3 · AC 3 · ac3 (as a word or between _/-/./non-letters): test_AC_3_rejects…,
# testAc3Rejects (camelCase), "AC-3: rejects". Not "track3" ("ac" inside a word).
AC_RE = re.compile(r"(?:(?<![A-Za-z])[Aa][Cc]|(?<=[a-z])A[Cc])[-_ ]?(\d+)(?!\d)")
LEVELS = ("unit", "integration", "e2e")


@dataclass
class Case:
    name: str
    classname: str
    outcome: str  # passed | failed | error | skipped

    @property
    def test_id(self) -> str:
        return f"{self.classname}::{self.name}" if self.classname else self.name


@dataclass
class Parsed:
    cases: List[Case] = field(default_factory=list)

    def count(self, outcome: str) -> int:
        return sum(1 for c in self.cases if c.outcome == outcome)


def parse_junit(xml_text: str) -> Parsed:
    if not xml_text or not xml_text.strip():
        raise ValidationException(message="junit_xml: empty")
    if len(xml_text.encode()) > MAX_XML_BYTES:
        raise ValidationException(message=f"junit_xml: larger than {MAX_XML_BYTES} bytes")
    head = xml_text[:4096].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in xml_text.upper():
        raise ValidationException(message="junit_xml: DTDs and entities are not accepted")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValidationException(message=f"junit_xml: not well-formed XML — {e}") from e
    out = Parsed()
    for case in root.iter("testcase"):
        tags = {child.tag for child in case}
        outcome = "error" if "error" in tags else "failed" if "failure" in tags else "skipped" if "skipped" in tags else "passed"
        out.cases.append(Case(name=case.get("name") or "", classname=case.get("classname") or "", outcome=outcome))
    if not out.cases:
        raise ValidationException(message="junit_xml: no <testcase> elements")
    return out


def ac_refs(name: str) -> List[str]:
    """AC refs a test name mentions, in order, without duplicates."""
    seen: List[str] = []
    for m in AC_RE.finditer(name or ""):
        ref = f"AC-{int(m.group(1))}"
        if ref not in seen:
            seen.append(ref)
    return seen


def covers_rows(cases: List[Case], run_url: str, known: Optional[set] = None) -> tuple:
    """(rows, unknown refs). Per AC: ERROR if any of its tests errored, else RED if any
    failed, else GREEN; skipped tests count for nothing (an AC with only skipped tests gets no
    row — it stays untested)."""
    by_ac: Dict[str, List[Case]] = {}
    unknown: List[str] = []
    for c in cases:
        if c.outcome == "skipped":
            continue
        for ref in ac_refs(c.name):
            if known is not None and ref not in known:
                if ref not in unknown:
                    unknown.append(ref)
                continue
            by_ac.setdefault(ref, []).append(c)
    rows = []
    for ref in sorted(by_ac, key=lambda r: int(r.split("-")[1])):
        outcomes = {c.outcome for c in by_ac[ref]}
        result = "ERROR" if "error" in outcomes else "RED" if "failed" in outcomes else "GREEN"
        ids = ", ".join(c.test_id for c in by_ac[ref])
        rows.append({"ac": ref, "result": result, "test_id": ids[:300], "evidence": run_url})
    return rows, unknown


class JunitService:
    def __init__(self, records: RecordService):
        self.records = records

    def ingest(
        self,
        initiative_id: int,
        task: str,
        sha: str,
        level: str,
        run_url: str,
        junit_xml: str,
        actor: Actor,
        environment: Optional[str] = None,
    ) -> dict:
        if level not in LEVELS:
            raise ValidationException(message=f"level: one of {', '.join(LEVELS)}")
        sha = (sha or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
            raise ValidationException(message="sha: the commit the tests ran on (7–64 hex chars)")
        if not (run_url or "").strip():
            raise ValidationException(message="run_url: the CI run that produced the report")
        initiative = self.records.initiative(initiative_id)
        g = self.records.graph(initiative)
        t = g.get(task)
        if t is None or t.type != "task":
            raise NotFoundException(message=f"No task '{task}' in initiative {initiative_id}")
        parsed = parse_junit(junit_xml)
        known = {a.ref for a in g.of_type("acceptance_criterion") if a.status in LIVE_AC}
        rows, unknown = covers_rows(parsed.cases, run_url, known)
        failed, errored, skipped = parsed.count("failed"), parsed.count("error"), parsed.count("skipped")
        result = "ERROR" if errored else "RED" if failed else "GREEN"
        summary = (
            f"JUnit {level}: {len(parsed.cases)} tests, {failed} failed, {errored} errors, {skipped} skipped"
            f" · {', '.join(r['ac'] for r in rows) or 'no AC named'}"
        )[:300]
        fields = {
            "summary": summary,
            "level": level,
            "result": result,
            "at_sha": sha,
            "run_url": run_url[:300],
            "task": [task],
            "covers": rows,
            "run_on": utcnow().replace(microsecond=0).isoformat(),
        }
        if environment:
            fields["environment"] = environment[:120]
        digest = hashlib.sha256(junit_xml.encode()).hexdigest()[:16]
        batch_id = "junit:" + hashlib.sha256(f"{initiative.id}|{task}|{sha}|{run_url}|{digest}".encode()).hexdigest()[:40]
        op = parse_op({"type": "test_run", "title": f"{level} tests for {task} @ {sha[:7]}", "fields": fields})
        # run_on differs between a first upload and a replay: keep the batch's ops stable by
        # reusing the stored result when this batch already exists.
        prior = self.records.batches.get(batch_id)
        if prior is not None and prior.initiative_id == initiative.id and prior.actor == actor.name:
            written = prior.result
        else:
            res = self.records.write(initiative.id, [op], actor, batch_id)
            if not res.ok:
                raise ValidationException(message="test_run rejected — nothing was saved", error_data=res.to_dict())
            written = res.to_dict()
        ref = (written.get("results") or [{}])[0].get("ref")
        not_covered = [ac for ac in g.f(t, "covers") or [] if ac not in {r["ac"] for r in rows}]
        return {
            "ref": ref,
            "result": result,
            "at_sha": sha,
            "tests": len(parsed.cases),
            "failed": failed,
            "errors": errored,
            "skipped": skipped,
            "covers": rows,
            "unknown_acs": unknown,
            "task_acs_without_tests": not_covered,
            "batch_id": batch_id,
        }
