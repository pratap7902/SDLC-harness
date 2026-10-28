from dataclasses import asdict

from app.blueprint.schemas.blueprint import Blueprint, RecordType
from app.blueprint.services.blueprint_loader import get_blueprint


class BlueprintService:
    def __init__(self):
        self.bp: Blueprint = get_blueprint()

    def blueprint(self) -> dict:
        bp = self.bp
        return {
            "vocab": bp.vocab,
            "open": {name: sorted(values) for name, values in bp.open_statuses.items()},
            "answers": sorted(bp.answer_statuses),
            "pills": bp.pills,
            "types": [self.type_json(t) for t in bp.types.values()],
        }

    def type_json(self, t: RecordType) -> dict:
        lc = self.bp.lifecycle
        rule = lc.status_rules.get(t.key) if lc else None
        return {
            "key": t.key,
            "title": t.title,
            "plural": t.plural,
            "ref": {"kind": t.ref_kind, "value": t.ref_value},
            "scope": t.scope,
            "status_vocab": t.status_vocab,
            "statuses": self.bp.vocab.get(t.status_vocab, []),
            "status_rule": {"rule": rule.rule, "text": rule.text} if rule else None,
            "line": t.line,
            "narrated": t.narrated,
            "post_baseline_cause": t.post_baseline_cause,
            "propagates_to": list(t.propagates_to),
            "index": {"facets": list(t.index_facets), "columns": list(t.index_columns), "newest_first": t.index_newest_first},
            "fields": [
                {
                    "name": f.name,
                    "type": f.type,
                    "max": f.max,
                    "required": f.required,
                    "expect": f.expect,
                    "vocab": f.vocab,
                    "values": self.bp.vocab.get(f.vocab) if f.vocab else None,
                    "columns": list(f.columns),
                    "row_key": f.row_key,
                    "column_vocab": dict(f.column_vocab),
                    "help": f.help,
                    "material": f.material,
                    "actor": f.actor,
                    "targets": list(f.targets),
                    "link_kind": f.link_kind,
                }
                for f in t.fields.values()
            ],
            "rules": [
                {"when": {**({"status": list(r.statuses)} if r.statuses else {}), **{n: list(v) for n, v in r.fields}}, "require": list(r.require)}
                for r in t.rules
            ],
            "actor_rules": [{"when": {n: list(v) for n, v in r.fields}, "human": list(r.human)} for r in t.actor_rules],
        }

    def lifecycle(self) -> dict:
        lc = self.bp.lifecycle
        return {
            "phases": lc.phases,
            "roles": lc.roles,
            "status_rules": {k: {"rule": r.rule, "text": r.text, **r.args} for k, r in lc.status_rules.items()},
            "catalogs": {phase: [asdict(i) for i in items] for phase, items in lc.catalogs.items()},
            "gates": {
                key: {
                    "scope": g.scope,
                    "human": g.human,
                    "text": g.text,
                    "on_pass": g.on_pass,
                    "rules": [{"name": r.name, "args": r.args} for r in g.rules],
                }
                for key, g in lc.gates.items()
            },
            "deploy_guard": lc.deploy_guard,
            "routing": lc.routing,
            "handoff": lc.handoff,
        }
