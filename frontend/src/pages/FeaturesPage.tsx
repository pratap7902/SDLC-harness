import { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import type { ActivityEntry, InboxItem, InitiativeRow, Worklist } from '../api';
import { all, api, useJson, useJsonAll } from '../lib/api';
import { PHASES, ago, due, nm, phaseLabel, phaseTone, plural, workItem } from '../lib/format';
import { usePersona } from '../lib/persona';
import { blocksText, isBlocking, isPrApproval, itemHref, itemLabel, itemTitle, sortWaiting, useAllWaiting } from '../lib/waiting';
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

function involves(f: InitiativeRow, persona: string, roles: { initiative: string }[], waiting: InboxItem[]): boolean {
  return f.dri === persona || f.engg === persona || roles.some((r) => r.initiative === f.slug) || waiting.some((w) => w.initiative === f.slug && w.person === persona);
}

export default function FeaturesPage() {
  const { persona, people } = usePersona();
  const navigate = useNavigate();
  const created = (useLocation().state as { created?: string } | null)?.created;
  const list = useJson<InitiativeRow[]>('/api/initiatives');
  const slugs = list.kind === 'ready' ? list.data.map((f) => f.slug) : null;
  const worklists = useJsonAll<Worklist>(slugs ? slugs.map((s) => api('initiatives', s, 'worklist')) : null);
  const activity = useJsonAll<ActivityEntry[]>(slugs ? slugs.map((s) => api('initiatives', s, 'activity') + '?limit=1') : null);
  const waiting = useAllWaiting();
  const [search, setSearch] = useState('');
  const [phase, setPhase] = useState('ALL');
  const [mine, setMine] = useState(false);

  const loaded = all(list, worklists, activity, waiting);
  const myRoles = people.find((p) => p.person === persona)?.roles || [];

  const view = useMemo(() => {
    if (loaded.kind !== 'ready') return null;
    const [features, wls, acts, items] = loaded.data;
    const sorted = sortWaiting(items, persona);
    const decisions = sorted.filter((i) => !isPrApproval(i));
    const approvals = sorted.filter((i) => isPrApproval(i) && i.person === persona);
    const agentsOn = new Map(features.map((f, i) => [f.slug, wls[i].items.filter((w) => w.lane === 'agent')]));
    const updated = new Map(features.map((f, i) => [f.slug, acts[i][0]?.at || f.created_at]));
    const counts: Record<string, number> = {};
    features.forEach((f) => (counts[f.phase] = (counts[f.phase] || 0) + 1));
    const q = search.trim().toLowerCase();
    const rows = features
      .filter((f) => phase === 'ALL' || f.phase === phase)
      .filter((f) => !mine || involves(f, persona, myRoles, items))
      .filter((f) => !q || [f.title, f.slug, f.work_item_url || '', workItem(f.work_item_url), nm(f.dri), nm(f.engg)].join(' ').toLowerCase().includes(q))
      .map((f) => {
        const next = sorted.find((i) => i.initiative === f.slug);
        const unexplained = f.drift?.unexplained || 0;
        const score = f.slug === created ? -1 : unexplained ? 0 : next?.person === persona ? 1 : next ? 2 : f.phase === 'SHIP' || f.phase === 'CLOSED' ? 4 : 3;
        return { f, next, score, agents: agentsOn.get(f.slug) || [], updated: updated.get(f.slug) || null };
      })
      .sort((a, b) => a.score - b.score || (b.updated || '').localeCompare(a.updated || ''));
    const extraPhases = Object.keys(counts).filter((p) => !PHASES.includes(p));
    return { features, decisions, approvals, rows, counts, agentsWorking: [...agentsOn.values()].filter((a) => a.length).length, phases: [...PHASES, ...extraPhases] };
  }, [loaded, persona, search, phase, mine, myRoles, created]);

  if (loaded.kind === 'error') return <LoadError what="the features" message={loaded.message} onRetry={list.reload} />;
  if (!view) return <Loading what="the features" />;
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
            {plural(view.features.length, 'feature')} · {plural(view.decisions.length, 'decision')} waiting · agents working on {view.agentsWorking}
          </p>
        </div>
        <Link to="/new" className="btn btn-primary btn-lg no-underline hover:text-white">
          Start feature
        </Link>
      </header>

      <Section id="dec-h" title={<>Decisions waiting <span className="small">· {view.decisions.length}</span></>} aside="Yours first, then whatever blocks work">
        {view.decisions.length === 0 ? (
          <Empty boxed>No decisions are waiting. Agents are working.</Empty>
        ) : (
          <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(320px,100%),1fr))]">
            {view.decisions.map((it) => (
              <DecisionCard key={it.key} it={it} persona={persona} />
            ))}
          </div>
        )}
        {view.approvals.length > 0 && (
          <div className="card flex flex-wrap items-center gap-x-[14px] gap-y-1.5 px-[14px] py-2.5 text-[13px]">
            <strong>PR approvals waiting on you</strong>
            {view.approvals.map((a) => (
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
              {view.rows.map(({ f, next, agents, updated }) => {
                const unexplained = f.drift?.unexplained || 0;
                const open = f.counts.open_gaps + f.counts.open_decisions;
                let progress: string;
                let sub = '';
                let subCls = 'text-ink-muted';
                if (f.phase === 'DRAFT' || f.phase === 'UNASSIGNED') progress = open ? `Draft · ${plural(open, 'open question')}` : agents.length ? 'Agent writing the draft' : 'Draft ready for review';
                else if (f.phase === 'PLAN') progress = 'Agent planning tasks';
                else if (f.phase === 'SHIP' || f.phase === 'CLOSED') progress = 'Shipped';
                else progress = `Tasks ${f.counts.tasks_done} of ${f.counts.tasks} done`;
                if (unexplained) {
                  sub = 'Gate 1 reopened';
                  subCls = 'text-bad font-semibold';
                } else if (f.counts.open_review_items) {
                  sub = plural(f.counts.open_review_items, 'review item') + ' open';
                  subCls = 'text-warn';
                }
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
                          <div className="small">
                            {next.kind === 'review_item' ? next.target : next.ref} · {itemLabel(next).toLowerCase()}
                          </div>
                        </>
                      ) : (
                        <>
                          <span className="small">Nobody</span>
                          <div className="small">{agents.length ? 'agents working' : 'nothing waiting'}</div>
                        </>
                      )}
                    </td>
                    <td>
                      <div>{progress}</div>
                      {sub && <div className={`text-xs ${subCls}`}>{sub}</div>}
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
                    <td className="small">{ago(updated)}</td>
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
