"""Markdown (the PR sticky comment) and compact text (MCP) renderings of a drift report."""

from app.initiatives.services.drift_service import DriftReport, clip


def _when(at: str) -> str:
    return (at or "")[5:16].replace("T", " ")


def _who(e) -> str:
    return f"{e.actor} ({e.actor_kind})" if e.actor_kind == "human" else e.actor


def markdown(report: DriftReport, base_url: str = "") -> str:
    if report.status == "NO_BASELINE":
        return "## Drift\nNo approved baseline yet — the draft has not passed GATE_DRAFT."
    b = report.baseline
    scope = f" — scope: {report.task}" if report.task else ""
    s = report.summary()
    lines = [
        f"## Drift since baseline {b['ref']} (approved by {b['approved_by']}, {(b['created_at'] or '')[:10]}, draft rev {b['draft_rev']}){scope}",
        f"**{s['changes']} changes · {s['explained']} explained · {s['unexplained']} unexplained** · digest `{report.digest[:8]}…`",
        "",
    ]
    if report.entries:
        lines += ["| when | who | change | because | |", "|---|---|---|---|---|"]
        for e in report.entries:
            because = ", ".join(e.because) or "—"
            mark = "✓" if e.explained else "**UNEXPLAINED**"
            lines.append(f"| {_when(e.at)} | {_who(e)} | {clip(e.summary, 180).replace('|', '/')} | {because} | {mark} |")
    else:
        lines.append("_No spec change since the baseline._")
    if report.unexplained:
        lines += ["", "### Unexplained"]
        for e in report.unexplained:
            lines.append(f"- {e.ref}: {e.summary} — " + "; ".join(x.why for x in e.explanation if not x.ok))
    if report.pending_gaps:
        lines += ["", "### Open gaps (not drift yet)"]
        lines += [f"- {p['ref']}: {clip(p['question'], 140)} (blocks {', '.join(p['blocks']) or '—'})" for p in report.pending_gaps]
    d = report.spec_diff
    parts = [f"draft.{k} (−{v['removed']} +{v['added']})" for k, v in (d.get("draft") or {}).items()]
    dec, crit = d.get("decisions") or {}, d.get("criteria") or {}
    if dec.get("superseded"):
        parts.append(f"decisions: {len(dec['superseded'])} superseded")
    if dec.get("added"):
        parts.append(f"decisions: +{len(dec['added'])}")
    if dec.get("changed"):
        parts.append(f"decisions: {len(dec['changed'])} changed")
    if crit.get("added"):
        parts.append(f"criteria: +{len(crit['added'])}")
    if crit.get("retired"):
        parts.append(f"criteria: −{len(crit['retired'])} retired")
    if crit.get("changed"):
        parts.append(f"criteria: {len(crit['changed'])} changed")
    lines += ["", "### Spec diff · " + (" · ".join(parts) if parts else "none")]
    for section, v in (d.get("draft") or {}).items():
        lines += [f"<details><summary>draft.{section}</summary>", "", "```diff", v["diff"], "```", "</details>"]
    for x in dec.get("superseded") or []:
        lines.append(f"- {x['old']} → {x['new']}: “{clip(x['old_verdict'], 100)}” → “{clip(x['new_verdict'], 100)}”")
    for x in crit.get("added") or []:
        lines.append(f"- {x['ref']} added ({x['level']}): {clip(x['text'], 160)}")
    if report.task and report.other_changes:
        link = f"{base_url}/i/{report.initiative}/drift" if base_url else f"/i/{report.initiative}/drift"
        lines += ["", f"Not in {report.task}'s scope: {report.other_changes} other change(s) (see {link})."]
    return "\n".join(lines)


def text(report: DriftReport) -> str:
    if report.status == "NO_BASELINE":
        return "NO_BASELINE — the draft has not been approved (GATE_DRAFT)."
    s = report.summary()
    b = report.baseline
    lines = [
        f"drift since {b['ref']} ({b['approved_by']}, draft rev {b['draft_rev']})"
        + (f" scope {report.task}" if report.task else "")
        + f": {s['changes']} changes, {s['explained']} explained, {s['unexplained']} UNEXPLAINED · digest {report.digest[:12]}"
    ]
    for e in report.entries:
        flag = "ok " if e.explained else "!! "
        because = f" because {', '.join(e.because)}" if e.because else ""
        lines.append(f"{flag}{_when(e.at)} {_who(e)} {e.kind} {clip(e.summary, 160)}{because}")
        if not e.explained:
            lines += [f"     - {x.why}" for x in e.explanation if not x.ok]
    for p in report.pending_gaps:
        lines.append(f".. pending {p['ref']} [{p['domain']}] {clip(p['question'], 120)} blocks {', '.join(p['blocks']) or '—'}")
    if report.task and report.other_changes:
        lines.append(f"({report.other_changes} other change(s) outside {report.task}'s scope)")
    return "\n".join(lines)
