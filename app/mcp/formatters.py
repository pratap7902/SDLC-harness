"""Compact plain-text renderings for MCP tool results. Agents pay per token for everything
a tool returns, so: one record per line, refs instead of links, no JSON punctuation, and
nothing the caller did not ask for."""

from typing import List, Optional

import yaml

from app.blueprint.schemas.blueprint import Blueprint, RecordType
from app.initiatives.models.record import Record
from app.initiatives.models.record_revision import RecordRevision
from app.initiatives.schemas.write import WriteResult
from app.initiatives.services.record_graph import RecordGraph


class _BlockDumper(yaml.SafeDumper):
    pass


def _str_representer(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_BlockDumper.add_representer(str, _str_representer)


def to_yaml(data) -> str:
    return yaml.dump(data, Dumper=_BlockDumper, sort_keys=False, allow_unicode=True, width=10000).rstrip()


def clip(text, width: int) -> str:
    text = " ".join(str(text or "").split())
    if width and len(text) > width:
        return text[: width - 1].rstrip() + "…"
    return text


def record_line(bp: Blueprint, r: Record, width: int = 140) -> str:
    spec = bp.types[r.type]
    out = f"{r.ref} [{r.status}] {r.title}"
    text = (r.fields or {}).get(spec.line) if spec.line else None
    if text and text != r.title:
        out += f" — {clip(text, width)}"
    return out


# ── blueprint ────────────────────────────────────────────────────────────


def _limits(f) -> str:
    out = ""
    if f.max:
        out += f", each item max {f.max} chars" if f.type == "bullets" else f", max {f.max} chars"
    if f.max_items:
        out += f", max {f.max_items} items"
    return out


def type_spec(bp: Blueprint, t: RecordType) -> str:
    ref = f"{t.ref_value}-n (minted: omit ref, give type)" if t.ref_kind == "prefix" else f"'{t.ref_value}'"
    rule = bp.lifecycle.status_rules.get(t.key) if bp.lifecycle else None
    lines = [f"{t.key} · ref {ref} · status DERIVED {' | '.join(bp.vocab[t.status_vocab])}"]
    if rule:
        lines.append(f"  status rule: {rule.text}")
    flags = []
    if t.scope == "global":
        flags.append("global scope: write to initiative '_global'")
    if t.post_baseline_cause:
        flags.append("after a baseline, a material edit needs `because`")
    if flags:
        lines.append("  " + " · ".join(flags))
    handle = f'"type": "{t.key}"' if t.ref_kind == "prefix" else f'"ref": "{t.ref_value}"'
    lines.append(f'  op: {{{handle}, "title": "…", "fields": {{…}}, "because": ["G-1"], "note": "…", "base_rev": n}}')
    for f in t.fields.values():
        kind = f.type + _limits(f)
        if f.vocab:
            kind += f" {' | '.join(bp.vocab[f.vocab])}"
        if f.columns:
            kind += f" [{', '.join(f.columns)}]"
        if f.targets:
            kind += f" → {' | '.join(f.targets)} (link {f.link_kind})"
        for column, vocab in f.column_vocab:
            kind += f" · {column} ∈ {' | '.join(bp.vocab[vocab])}"
        if f.material:
            kind += ", material"
        if f.actor == "human":
            kind += ", HUMAN-ONLY"
        flag = "*" if f.required else ("+" if f.expect else "")
        lines.append(f"  {f.name}{flag}: {kind}" + (f" — {f.help}" if f.help else ""))
    for r in t.rules:
        cond = ([f"status {'/'.join(r.statuses)}"] if r.statuses else []) + [f"{n} = {'/'.join(v)}" for n, v in r.fields]
        lines.append(f"  when {' and '.join(cond)}: needs {', '.join(r.require)}")
    for r in t.actor_rules:
        cond = [f"{n} = {'/'.join(v)}" for n, v in r.fields]
        lines.append(f"  when {' and '.join(cond)}: HUMAN-ONLY {', '.join(r.human)}")
    return "\n".join(lines)


def blueprint_text(bp: Blueprint, type_key: Optional[str]) -> str:
    if type_key:
        return type_spec(bp, bp.types[type_key])
    out = ["* required · + expected · statuses are derived, never written", ""]
    out += [type_spec(bp, t) for t in bp.types.values()]
    lc = bp.lifecycle
    out.append("")
    out.append("gates:")
    for g in lc.gates.values():
        names = ", ".join(r.name for r in g.rules)
        out.append(f"  {g.key} ({g.scope}{', human ' + g.human if g.human else ''}): {names}")
    return "\n".join(out)


# ── records ──────────────────────────────────────────────────────────────


def records_text(bp: Blueprint, records: List[Record], width: int = 140) -> str:
    if not records:
        return "no records match"
    return "\n".join(record_line(bp, r, width) for r in records)


def record_full(bp: Blueprint, r: Record, g: RecordGraph, history: Optional[List[RecordRevision]] = None) -> str:
    lines = [f"{r.ref} [{r.status}] rev {r.head_rev} {r.type} · {r.title}"]
    outs = g.edges_out(r.ref)
    ins = g.edges_in(r.ref)
    if outs:
        lines.append("links out: " + ", ".join(f"{e['kind']} {e['to']}" for e in outs))
    if ins:
        lines.append("links in: " + ", ".join(f"{e['from']} {e['kind']}" for e in ins))
    stale = g.stale_slots(r)
    if stale:
        lines.append(f"STALE: {', '.join(stale)}")
    for item in g.open_review_items:
        if item.target_ref == r.ref:
            lines.append(f"UP FOR REVIEW #{item.id} because {item.cause_ref} — {item.what_moved}")
    if r.fields:
        lines.append(to_yaml(bp.ordered_fields(r.type, r.fields)))
    if history:
        lines.append("history:")
        for rev in history:
            note = f" — {rev.note}" if rev.note else ""
            because = f" because {', '.join(rev.cause_refs)}" if rev.cause_refs else ""
            lines.append(f"  rev {rev.rev} {rev.created_at:%Y-%m-%d %H:%M} {rev.actor} ({rev.actor_kind}) [{rev.status}]{because}{note}")
    return "\n".join(lines)


def write_text(result: WriteResult) -> str:
    lines = []
    if result.replayed:
        lines.append(f"(batch {result.batch_id} replayed — already applied)")
    if not result.ok:
        lines.append("REJECTED — nothing was saved. Fix and resend the whole batch:")
    for r in result.results:
        if r.errors:
            lines.append(f"op {r.index} {r.ref or '(unminted)'}:")
            lines += [f"  - {e}" for e in r.errors]
        elif result.ok:
            lines.append(f"{r.ref} {r.action} rev {r.rev} [{r.status}]")
            lines += [f"  WARNING {w}" for w in r.warnings]
    if result.baseline:
        lines.append(f"BASELINE {result.baseline} created — from now on every spec change needs `because`")
    for g in result.gates_changed:
        lines.append(f"gate {g['gate']}{' ' + g['task'] if g['task'] else ''}: {g['before']} → {g['after']}")
    if result.review_items:
        lines.append(f"PUT UP FOR REVIEW by this write ({len(result.review_items)}) — revise each, or `reviewed: true` + a note:")
        lines += [f"  {d}" for d in result.review_items[:40]]
    if result.stale:
        lines.append("now STALE (rewrite these narratives): " + ", ".join(result.stale))
    return "\n".join(lines)


def state_text(state: dict) -> str:
    i = state["initiative"]
    lines = [f"{i['slug']} — {i['title']} · phase {state['phase']}"]
    people = ", ".join(f"{a['role']} {a['person']}" for a in state["assignments"] if a["status"] == "ACTIVE")
    lines.append(f"people: {people or 'none'}")
    for g in state["gates"]:
        failing = ", ".join(g["failing_rules"])
        lines.append(f"{g['gate']}: {g['status']}" + (f" — failing {failing}" if failing and g["status"] != "PASSED" else ""))
    for t in state["tasks"]:
        lines.append(
            f"  {t['ref']} [{t['status']}] {t['title']} · GATE_PR {t['gate_pr']['status']}"
            + (f" (failing {', '.join(t['gate_pr']['failing_rules'])})" if t["gate_pr"]["failing_rules"] else "")
        )
    counts = " · ".join(f"{k}: " + ", ".join(f"{s} {n}" for s, n in v.items()) for k, v in state["counts"].items() if k not in ("assignment", "initiative"))
    lines.append(counts)
    if state["baseline"]:
        d = state["drift"] or {}
        lines.append(f"baseline {state['baseline']['ref']} · drift {d.get('changes', 0)} changes, {d.get('unexplained', 0)} UNEXPLAINED, {d.get('pending_gaps', 0)} pending gaps")
    if state["stuck"]:
        lines.append(f"STUCK: {', '.join(state['stuck'])}")
    if state["stale"]:
        lines.append(f"stale narratives: {', '.join(state['stale'])}")
    missing = [c["item"] for phase in state["catalog"].values() for c in phase if c["disposition"] == "UNASSESSED"]
    if missing:
        lines.append(f"catalog unassessed: {', '.join(missing)}")
    return "\n".join(lines)


def gate_text(result) -> str:
    lines = [f"{result.gate}{' ' + result.target if result.target else ''}: {result.status}" + (f" ({result.note})" if result.note else "")]
    for r in result.rules:
        mark = "ok" if r.passed else "!!"
        lines.append(f"  {mark} {r.name}" + (f" — {', '.join(r.failing)}" if r.failing else "") + (f" · {r.detail}" if r.detail else ""))
    return "\n".join(lines)


def items_text(items: List[dict]) -> str:
    if not items:
        return "nothing to do"
    lines = []
    for x in items:
        lease = f" [held by {x['lease']['holder']}]" if x.get("lease") else ""
        person = f" → {x['person']}" if x.get("person") else ""
        lines.append(f"{x['key']} ({x['kind']}, {x['lane']}){person}{lease}: {clip(x.get('title'), 100)} — {clip(x.get('why'), 160)}")
        ctx = x.get("context") or {}
        rec = ctx.get("record")
        if rec:
            lines.append(f"    {rec['ref']} [{rec['status']}] rev {rec['rev']}")
        for ref, c in (ctx.get("cites") or {}).items():
            lines.append(f"    cites {ref} [{c['status']}] {clip(c.get('line') or c['title'], 100)}")
        for item in ctx.get("review_items") or []:
            lines.append(f"    up for review #{item['id']} ← {item['cause']}: {clip(item['what_moved'], 120)}")
        if ctx.get("drift"):
            d = ctx["drift"]
            lines.append(f"    drift: {d['changes']} changes, {d['unexplained']} unexplained")
        missing = [c["item"] for c in ctx.get("catalog") or [] if c["disposition"] == "UNASSESSED"]
        if missing:
            lines.append(f"    catalog unassessed: {', '.join(missing)}")
    return "\n".join(lines)


def inbox_text(inbox: dict) -> str:
    lines = [f"inbox {inbox['person']}: {inbox['count']} items, {inbox['overdue']} overdue"]
    for x in inbox["items"]:
        flag = "OVERDUE " if x["overdue"] else ""
        lines.append(f"{flag}{x['initiative']} {x['kind']} {x['ref']}: {clip(x.get('title') or x.get('question'), 140)} (age {x['age_hours']}h / sla {x['sla_hours']}h)")
    return "\n".join(lines)


def activity_text(feed: List[dict]) -> str:
    if not feed:
        return "no activity"
    return "\n".join(
        f"{(x['at'] or '')[:16]} {x['actor'] or '—'}{' (' + x['actor_kind'] + ')' if x.get('actor_kind') else ''} "
        f"{x['action']} {x['ref']}" + (f" rev {x['rev']}" if x.get("rev") else "") + (f" because {', '.join(x['because'])}" if x["because"] else "")
        + (f" — {clip(x['note'], 100)}" if x.get("note") else "")
        for x in feed
    )
