"""deploy_guard(initiative, task, sha, environment) → GO | NO-GO with reasons. CI/CD asks
before every deploy; POST records the ask as a `deploy` row. Same code path for REST and
MCP."""

from typing import Annotated, List, Union

from fastapi import Depends

from app.core.utils.actor import Actor
from app.exceptions import ValidationException
from app.initiatives.schemas.write import WriteOp
from app.initiatives.services.record_service import RecordService


class DeployGuard:
    def __init__(self, records: Annotated[RecordService, Depends()]):
        self.records = records

    def check(self, slug: Union[int, str], task: str, sha: str, environment: str) -> dict:
        if environment not in self.records.bp.vocab["environment"]:
            raise ValidationException(message=f"environment: one of {' | '.join(self.records.bp.vocab['environment'])}")
        g = self.records.graph(self.records.initiative(slug))
        t = g.get(task)
        if t is None or t.type != "task":
            raise ValidationException(message=f"{task} is not a task of {g.initiative.slug}")
        checks: List[dict] = []
        gate_pr = g.gate("GATE_PR", task=task)
        checks.append({"name": "GATE_PR", "passed": gate_pr.status == "PASSED", "detail": ", ".join(gate_pr.failing_rules) or "passed"})
        pr_sha = g.f(t, "pr_sha")
        checks.append({"name": "sha_matches_pr", "passed": pr_sha == sha, "detail": f"PR head {pr_sha or '—'}, deploying {sha}"})
        approvals = [a for a in g.of_type("approval") if task in (g.f(a, "target") or []) and a.status == "CURRENT"]
        approved_at = {g.f(a, "at_sha") for a in approvals}
        checks.append({"name": "approved_at_sha", "passed": sha in approved_at, "detail": f"engg approved at {', '.join(sorted(x for x in approved_at if x)) or 'nothing current'}"})
        gate_v = g.gate("GATE_VALIDATED", scope_task=task, sha=sha)  # runs at THIS sha only
        checks.append({"name": "GATE_VALIDATED", "passed": gate_v.status == "PASSED", "detail": ", ".join(f"{r.name} ({', '.join(r.failing)})" for r in gate_v.rules if not r.passed) or "passed"})
        open_decisions = [d for d in g.f(t, "implements") or [] if g.get(d) is not None and g.get(d).status in ("OPEN", "PROVISIONAL")]
        checks.append({"name": "no_open_or_provisional_decision", "passed": not open_decisions, "detail": ", ".join(open_decisions) or "none"})
        go = all(c["passed"] for c in checks)
        drift = g.drift(task=task)
        return {
            "decision": "GO" if go else "NO-GO",
            "initiative_id": g.initiative.id,
            "initiative": g.initiative.slug,
            "task": task,
            "sha": sha,
            "environment": environment,
            "reasons": [f"{c['name']}: {c['detail']}" for c in checks if not c["passed"]],
            "checks": checks,
            "drift": {**drift.summary(), "digest": drift.digest, "status": drift.status},
        }

    def record(self, slug: Union[int, str], task: str, sha: str, environment: str, actor: Actor) -> dict:
        verdict = self.check(slug, task, sha, environment)
        text = f"{verdict['decision']}" + ("" if verdict["decision"] == "GO" else ": " + "; ".join(verdict["reasons"]))
        result = self.records.write(
            slug,
            [
                WriteOp(
                    type="deploy",
                    title=f"{environment} {task} @ {sha[:10]}",
                    fields={
                        "environment": environment,
                        "at_sha": sha,
                        "task": [task],
                        "guard_result": text[:2000],
                        "result": "PENDING" if verdict["decision"] == "GO" else "FAILED",
                    },
                    note=f"deploy_guard {verdict['decision']}",
                )
            ],
            actor,
        )
        if not result.ok:
            raise ValidationException(message="deploy record rejected", error_data=result.to_dict())
        verdict["deploy"] = result.results[0].ref
        return verdict
