import { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import type { InboxItem, OverviewRow } from '../api';
import { PHASES, ago, due, nm, phaseLabel, phaseTone, plural, workItem } from '../lib/format';
import { usePersona } from '../lib/persona';
import { blocksText, isBlocking, itemHref, itemLabel, itemTitle, useOverview } from '../lib/waiting';
import { Badge, Empty, Section } from '../components/ui';
import { LoadError, Loading } from '../components/state';

function actionLabel(it: InboxItem): string {
  switch (it.kind) {
    case 'gap':
      return 'Answer';
    case 'decision':
      return 'Rule';
    case 'approval':
      return it.target === 'draft' ? 'Review draft' : 'Open PR review';
    case 'review_item':
      return 'Does it still hold?';
    case 'manual_ac':
      return 'Sign';
  }
}

export function DecisionCard({ it, persona, compact = false }: { it: InboxItem; persona: string; compact?: boolean }) {
  const mine = it.person === persona;
  const blocking = isBlocking(it);
  const cls = mine ? 'border-2 border-human px-[15px] py-[13px]' : it.overdue && blocking ? 'border border-bad px-4 py-[14px]' : 'border border-line px-4 py-[14px]';
  return (
    <article className={`bg-white rounded-card flex flex-col gap-2 ${cls}`}>
      <div className="text-xs text-ink-muted flex flex-wrap gap-x-2.5 gap-y-1 items-center">
        <Badge tone={mine ? 'human' : it.overdue ? 'bad' : 'muted'}>
          {mine ? 'Yours' : nm(it.person)} · {itemLabel(it)}
        </Badge>
        <span>
          <span className="font-mono">{it.initiative}</span> · <span className="font-mono">{it.ref === 'draft' ? 'draft' : it.kind === 'review_item' ? it.target : it.ref}</span> ·{' '}
          <span className={it.overdue ? 'text-bad font-semibold' : ''}>{due(it.due_at)}</span>
        </span>
      </div>
      <h3>{itemTitle(it)}</h3>
      {!compact && <div className={`text-xs ${blocking ? 'text-bad font-semibold' : 'text-ink-muted'}`}>Blocks: {blocksText(it)}</div>}
      <div className="flex flex-wrap gap-2 items-center">
        {mine ? (
          <Link to={itemHref(it)} className="btn btn-primary no-underline hover:text-white">
            {actionLabel(it)}
          </Link>
        ) : (
          <>
            <span className="small">Waiting on {nm(it.person)}</span>
            <Link to={itemHref(it)} className="btn btn-link no-underline">
              Details
            </Link>
          </>
        )}
      </div>
    </article>
  );
}

function progressOf(f: OverviewRow): { text: string; sub: string; subCls: string } {
  const open = f.counts.open_gaps + f.counts.open_decisions;
  let text: string;
  if (f.phase === 'DRAFT' || f.phase === 'UNASSIGNED') {
    const rev = f.gate_draft.draft_rev ? `Draft rev ${f.gate_draft.draft_rev}` : 'Draft';
    text =
      f.gate_draft.state === 'drafting'
        ? `Agent writing ${rev.toLowerCase()}`
        : open
          ? `${rev} · ${plural(open, 'open question')}`
          : f.gate_draft.state === 'ready'
            ? `${rev} · ready for approval`
            : `${rev} · being revised`;
  } else if (f.phase === 'PLAN') text = 'Agent planning tasks';
  else if (f.phase === 'SHIP' || f.phase === 'CLOSED') text = 'Shipped';
  else if (f.phase === 'VALIDATE') text = `Validating · ${f.prs.done} of ${f.prs.total} tasks merged`;
  else text = `PRs ${f.prs.approved} of ${f.prs.total} approved`;
  if (f.gate_draft.state === 'reopened') return { text, sub: 'Gate 1 reopened', subCls: 'text-bad font-semibold' };
  if (f.prs.stale.length) return { text, sub: `${f.prs.stale.join(', ')} approval stale`, subCls: 'text-warn' };
  if (f.counts.open_review_items) return { text, sub: `${plural(f.counts.open_review_items, 'review item')} open`, subCls: 'text-warn' };
  return { text, sub: '', subCls: '' };
}

export default function FeaturesPage() {
  const { persona } = usePersona();
  const navigate = useNavigate();
  const created = (useLocation().state as { created?: string } | null)?.created;
  const overview = useOverview();
  const [search, setSearch] = useState('');
  const [phase, setPhase] = useState('ALL');
  const [mine, setMine] = useState(false);

  const view = useMemo(() => {
    if (overview.kind !== 'ready') return null;
    const o = overview.data;
    const features = o.initiatives;
    const counts: Record<string, number> = {};
    features.forEach((f) => (counts[f.phase] = (counts[f.phase] || 0) + 1));
    const q = search.trim().toLowerCase();
    const rows = features
      .filter((f) => phase === 'ALL' || f.phase === phase)
      .filter((f) => !mine || f.involved)
      .filter((f) => !q || [f.title, f.slug, f.work_item_url || '', workItem(f.work_item_url), ...Object.values(f.people).map(nm)].join(' ').toLowerCase().includes(q))
      .map((f) => {
        const unexplained = f.drift?.unexplained || 0;
        const score = f.slug === created ? -1 : unexplained ? 0 : f.next?.person === persona ? 1 : f.next ? 2 : f.phase === 'SHIP' || f.phase === 'CLOSED' ? 4 : 3;
        return { f, score };
      })
      .sort((a, b) => a.score - b.score || (b.f.updated_at || '').localeCompare(a.f.updated_at || ''));
    const extraPhases = Object.keys(counts).filter((p) => !PHASES.includes(p));
    return { o, features, rows, counts, phases: [...PHASES, ...extraPhases] };
  }, [overview, persona, search, phase, mine, created]);

  if (overview.kind === 'error') return <LoadError what="the features" message={overview.message} onRetry={overview.reload} />;
  if (!view) return <Loading what="the features" />;
  const { o } = view;
  const clear = () => {
    setSearch('');
    setPhase('ALL');
    setMine(false);
  };

  return (
    <>
      <header className="flex flex-wrap gap-3 items-center justify-between">
        <div className="flex flex-col gap-1">
          <h1>Features</h1>
          <p className="m-0 text-ink-muted">
            {plural(o.summary.features, 'feature')} · {plural(o.summary.decisions_waiting, 'decision')} waiting · agents working on {o.summary.agents_working}
          </p>
        </div>
        <Link to="/new" className="btn btn-primary btn-lg no-underline hover:text-white">
          Start feature
        </Link>
      </header>

      <Section id="dec-h" title={<>Decisions waiting <span className="small">· {o.decisions.length}</span></>} aside="Yours first, then whatever blocks work">
        {o.decisions.length === 0 ? (
          <Empty boxed>No decisions are waiting. Agents are working.</Empty>
        ) : (
          <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(320px,100%),1fr))]">
            {o.decisions.map((it) => (
              <DecisionCard key={it.key} it={it} persona={persona} />
            ))}
          </div>
        )}
        {o.my_pr_approvals.length > 0 && (
          <div className="card flex flex-wrap items-center gap-x-[14px] gap-y-1.5 px-[14px] py-2.5 text-[13px]">
            <strong>PR approvals waiting on you</strong>
            {o.my_pr_approvals.map((a) => (
              <Link key={a.key} to={itemHref(a)} className="font-semibold">
                {a.title}
              </Link>
            ))}
          </div>
        )}
      </Section>

      <Section id="all-h" title="All features" aside="Sorted by what needs attention">
        <div className="flex flex-wrap gap-2.5">
          <label htmlFor="search" className="sr-only">
            Search features
          </label>
          <input
            id="search"
            type="search"
            className="input flex-[1_1_260px] w-auto"
            placeholder="Search by name, slug, work item or person"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by phase">
            {['ALL', ...view.phases].map((p) => (
              <button key={p} type="button" aria-pressed={phase === p} className={`chip ${phase === p ? 'chip-on' : ''}`} onClick={() => setPhase(p)}>
                {p === 'ALL' ? 'All' : phaseLabel(p)} {p === 'ALL' ? view.features.length : view.counts[p] || 0}
              </button>
            ))}
            <button type="button" aria-pressed={mine} className={`chip ${mine ? 'chip-on' : ''}`} onClick={() => setMine(!mine)}>
              Mine
            </button>
          </div>
        </div>
        <div className="card tbl">
          <table className="min-w-[1000px]">
            <thead>
              <tr>
                <th scope="col">Feature</th>
                <th scope="col">Phase</th>
                <th scope="col">Next decision</th>
                <th scope="col">Progress</th>
                <th scope="col">Drift since approval</th>
                <th scope="col">DRI</th>
                <th scope="col">Updated</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map(({ f }) => {
                const unexplained = f.drift?.unexplained || 0;
                const next = f.next;
                const pr = progressOf(f);
                const working = f.agents.queued + f.agents.leased;
                return (
                  <tr key={f.slug} className={f.slug === created ? '[&>td]:bg-agent-row' : unexplained ? '[&>td]:bg-bad-row' : ''}>
                    <td>
                      <button type="button" className="bg-transparent border-0 p-0 font-semibold text-ink cursor-pointer text-left text-sm hover:text-agent hover:underline" onClick={() => navigate(`/i/${f.slug}`)}>
                        {f.title}
                      </button>
                      <div className="small">
                        <span className="font-mono">{f.slug}</span> ·{' '}
                        {f.work_item_url ? (
                          <a href={f.work_item_url} target="_blank" rel="noreferrer">
                            {workItem(f.work_item_url)}
                          </a>
                        ) : (
                          'no work item'
                        )}
                      </div>
                    </td>
                    <td>
                      <Badge tone={phaseTone(f.phase)}>{phaseLabel(f.phase)}</Badge>
                    </td>
                    <td>
                      {next ? (
                        <>
                          <span className={next.person === persona ? 'text-human font-bold' : ''}>{next.person === persona ? 'You' : nm(next.person)}</span>
                          <div className="small">{next.label}</div>
                        </>
                      ) : (
                        <>
                          <span className="small">Nobody</span>
                          <div className="small">{working ? (f.agents.leased ? `${f.agents.holders.map((h) => h.split('/').pop()).join(', ')} working` : 'agents working') : 'nothing waiting'}</div>
                        </>
                      )}
                    </td>
                    <td>
                      <div>{pr.text}</div>
                      {pr.sub && <div className={`text-xs ${pr.subCls}`}>{pr.sub}</div>}
                    </td>
                    <td>
                      {!f.baseline ? (
                        <div>Not approved yet</div>
                      ) : !f.drift || f.drift.changes === 0 ? (
                        <div>No changes</div>
                      ) : (
                        <>
                          <div>{plural(f.drift.changes, 'change')}</div>
                          <div className={`text-xs ${unexplained ? 'text-bad font-semibold' : 'text-ok'}`}>{unexplained ? `${unexplained} unexplained` : 'all explained'}</div>
                        </>
                      )}
                    </td>
                    <td>{nm(f.dri)}</td>
                    <td className="small">{ago(f.updated_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {view.rows.length === 0 && (
            <Empty>
              No features match.{' '}
              <button type="button" className="btn btn-link min-h-0" onClick={clear}>
                Clear filters
              </button>
            </Empty>
          )}
        </div>
      </Section>
    </>
  );
}
