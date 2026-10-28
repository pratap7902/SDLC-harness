import type { Lifecycle } from '../api';
import { useJson } from '../lib/api';
import { ROLE_LABEL } from '../lib/format';
import { Badge, Card, CardHead } from '../components/ui';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';

function ruleName(r: unknown): string {
  if (typeof r === 'string') return r;
  if (r && typeof r === 'object') {
    const [k, v] = Object.entries(r as Record<string, unknown>)[0] || ['', ''];
    return `${k} ${JSON.stringify(v)}`;
  }
  return String(r);
}

/** The lifecycle the service enforces: phases, how each status is derived, the gates and
 * their rules, routing and SLAs, and the per-phase catalogs (blueprint/lifecycle.yaml). */
export default function BlueprintPage() {
  const lc = useJson<Lifecycle>('/api/blueprint/lifecycle');
  if (lc.kind === 'error') return <LoadError what="the blueprint" message={lc.message} onRetry={lc.reload} />;
  if (lc.kind === 'loading') return <Loading what="the blueprint" />;
  const b = lc.data;
  return (
    <>
      <PageHeader title="Blueprint">
        <p className="m-0 text-ink-muted">What the service enforces, read from blueprint/lifecycle.yaml. Engineers change it there; `make check` lints it.</p>
        <div className="flex flex-wrap gap-1.5">
          {b.phases.map((p, i) => (
            <Badge key={p} tone="agent">
              {i + 1}. {p}
            </Badge>
          ))}
        </div>
      </PageHeader>
      <Card>
        <CardHead title="Gates" />
        <div className="px-[18px] py-3 flex flex-col gap-3">
          {Object.entries(b.gates).map(([k, g]) => (
            <div key={k} className="flex flex-col gap-1">
              <div className="flex flex-wrap gap-2 items-center">
                <strong className="font-mono">{k}</strong>
                <Badge tone="muted">{g.scope}</Badge>
                {g.human && <Badge tone="human">human: {ROLE_LABEL[g.human] || g.human}</Badge>}
              </div>
              <span className="text-[13px]">{g.text}</span>
              <span className="small font-mono">{(Array.isArray(g.rules) ? g.rules : (g.all_of as unknown[]) || []).map(ruleName).join(' · ')}</span>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <CardHead title="Routing and SLAs" />
        <div className="px-[18px] py-3 text-[13px] flex flex-col gap-1">
          <span>By domain: {Object.entries(b.routing.by_domain).map(([d, r]) => `${d} → ${ROLE_LABEL[r] || r}`).join(' · ')}</span>
          <span>Gates: {Object.entries(b.routing.gates).map(([g, r]) => `${g} → ${ROLE_LABEL[r] || r}`).join(' · ')}</span>
          <span>Fallback: {ROLE_LABEL[b.routing.fallback] || b.routing.fallback} · escalate to {ROLE_LABEL[b.routing.escalate_to] || b.routing.escalate_to}</span>
          <span>SLA hours: {Object.entries(b.routing.sla_hours).map(([k, h]) => `${k} ${h} h`).join(' · ')}</span>
        </div>
      </Card>
      <Card>
        <CardHead title="Derived statuses" />
        <div className="tbl">
          <table>
            <tbody>
              {Object.entries(b.status_rules).map(([t, r]) => (
                <tr key={t}>
                  <td className="font-mono font-semibold w-44">{t}</td>
                  <td>{r.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card>
        <CardHead title="Catalogs" />
        <div className="px-[18px] py-3 flex flex-col gap-2 text-[13px]">
          {Object.entries(b.catalogs).map(([phase, items]) => (
            <div key={phase}>
              <span className="eyebrow">{phase}</span>
              {items.length === 0 ? (
                <div className="small">none</div>
              ) : (
                items.map((i) => (
                  <div key={i.item}>
                    <span className="font-mono">{i.item}</span> — {i.text}
                    {i.derived && <span className="small"> (derived)</span>}
                  </div>
                ))
              )}
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
