import { Link, useParams } from 'react-router-dom';
import type { DeployGuard, DraftPage, InboxItem, InitiativeState, TaskRow, Worklist } from '../api';
import { all, api, useJson, useJsonAll } from '../lib/api';
import { ROLE_SHORT, asList, asText, due, nm, phaseLabel, phaseTone, plural, prNumber, ruleText, shortSha, who, workItem } from '../lib/format';
import { Refs } from '../lib/links';
import { usePersona } from '../lib/persona';
import { blocksText, itemHref, itemLabel, itemTitle, sortWaiting, useAllWaiting } from '../lib/waiting';
import { Badge, CardHead, Empty, Kv, PersonChip, StatusBadge, toneText } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';
import type { Tone } from '../lib/format';

interface LogLine {
  ref: string;
  text: string;
  sub: string;
  badge: string;
  tone: Tone;
  struck: boolean;
  order: number;
}

function logLines(draft: DraftPage, waiting: InboxItem[], baselineMembers: string[]): LogLine[] {
  const waitingOn = (ref: string) => waiting.find((w) => w.ref === ref)?.person;
  const lines: LogLine[] = [];
  for (const g of draft.gaps) {
    const f = g.fields;
    const open = g.status === 'OPEN';
    lines.push({
      ref: g.ref,
      text: asText(f.question) || g.title,
      sub: open
        ? `Raised by ${who(asText(f.asked_by) || g.created_by)}${waitingOn(g.ref) ? ` · waiting on ${nm(waitingOn(g.ref))}` : ''}`
        : g.status === 'ANSWERED'
          ? `Answered by ${nm(asText(f.answered_by))}: ${asText(f.answer)}`
          : asText(f.withdrawn_because) || g.status,
      badge: g.status,
      tone: open ? 'human' : 'muted',
      struck: false,
      order: open ? 0 : 3,
    });
  }
  for (const d of draft.decisions) {
    const f = d.fields;
    const level = asText(f.level);
    const because = asList(f.because);
    let sub = '';
    if (d.status === 'SUPERSEDED') sub = `Superseded by ${(d.superseded_by || []).join(', ') || 'a newer decision'}. Kept for history.`;
    else if (d.status === 'OPEN') sub = waitingOn(d.ref) ? `Not decided · waiting on ${nm(waitingOn(d.ref))}` : 'Not decided yet';
    else if (d.status === 'PROVISIONAL') sub = 'Provisional default. Work continues on it; a human answer would supersede it.';
    else {
      const parts = [`Decided by ${who(asText(f.decided_by) || d.updated_by)}`];
      if (baselineMembers.includes(d.ref)) parts.push('approved in the baseline');
      if (asList(f.supersedes).length) parts.push(`replaced ${asList(f.supersedes).join(', ')}`);
      if (because.length) parts.push(`because ${because.join(', ')}`);
      if (asList(f.cites).length) parts.push(`cites ${asList(f.cites).join(', ')}`);
      sub = parts.join(' · ');
    }
    lines.push({
      ref: d.ref,
      text: asText(f.verdict) || asText(f.question) || d.title,
      sub,
      badge: level ? `${d.status} · ${level}` : d.status,
      tone: d.status === 'OPEN' ? 'human' : d.status === 'SUPERSEDED' ? 'muted' : d.status === 'PROVISIONAL' ? 'warn' : 'ok',
      struck: d.status === 'SUPERSEDED',
      order: d.status === 'OPEN' ? 1 : d.status === 'SUPERSEDED' ? 4 : 2,
    });
  }
  const num = (r: string) => Number(r.split('-')[1] || 0);
  return lines.sort((a, b) => a.order - b.order || num(b.ref) - num(a.ref));
}

function taskNow(t: TaskRow): string {
  const f = t.fields;
  const pr = asText(f.pr_url) ? `PR ${prNumber(asText(f.pr_url))}` : '';
  if (t.gate_pr.status === 'PASSED') return `${pr} approved at ${shortSha(asText(f.pr_sha))}`.trim();
  if (t.status === 'DONE') return 'merged';
  const failing = t.gate_pr.failing_rules.filter((r) => r !== 'approval_by_role');
  if (asText(f.pr_state) === 'open' && !failing.length) return `${pr} waits on the engineering review`;
  if (failing.length) return `${pr ? pr + ' · ' : ''}${failing.map((r) => ruleText(r, false)).join('; ')}`;
  return t.status === 'READY' ? 'ready for an agent' : t.line || '';
}

export default function FeaturePage() {
  const { slug = '' } = useParams();
  const { persona } = usePersona();
  const state = useJson<InitiativeState>(api('initiatives', slug));
  const draft = useJson<DraftPage>(api('initiatives', slug, 'draft'));
  const worklist = useJson<Worklist>(api('initiatives', slug, 'worklist'));
  const waiting = useAllWaiting();
  const tasks = state.kind === 'ready' ? state.data.tasks.filter((t) => asText(t.fields.pr_sha)) : null;
  const guards = useJsonAll<DeployGuard>(
    tasks ? tasks.map((t) => `/api/deploy-guard?${new URLSearchParams({ initiative: slug, task: t.ref, sha: asText(t.fields.pr_sha), environment: 'staging' })}`) : null,
  );
  const loaded = all(state, draft, worklist, waiting);
  if (loaded.kind === 'error') return <LoadError what={`the feature ${slug}`} message={loaded.message} onRetry={state.reload} />;
  if (loaded.kind === 'loading') return <Loading what="the feature" />;
  const [s, d, wl, allItems] = loaded.data;
  const i = s.initiative;
  const items = sortWaiting(allItems.filter((w) => w.initiative === slug), persona);
  const needs = items.filter((w) => w.person === persona);
  const others = items.filter((w) => w.person !== persona);
  const agents = wl.items.filter((w) => w.lane === 'agent');
  const members = s.baseline && Array.isArray(s.baseline.members) ? s.baseline.members : [];
  const log = logLines(d, allItems, members);
  const people = s.assignments.filter((a) => a.status === 'ACTIVE');
  const gDraft = s.gates.find((g) => g.gate === 'GATE_DRAFT');
  const gValid = s.gates.find((g) => g.gate === 'GATE_VALIDATED');
  const liveAcs = d.criteria.filter((c) => c.status !== 'RETIRED').length;
  const notGreen = gValid?.rules.find((r) => r.name === 'every_ac_green')?.failing.length ?? 0;
  const approved = s.tasks.filter((t) => t.gate_pr.status === 'PASSED').length;
  const draftStatus = d.draft?.status || '';
  const g1: [string, Tone] = !gDraft
    ? ['—', 'muted']
    : gDraft.status === 'PASSED'
      ? ['Approved', 'ok']
      : draftStatus === 'REOPENED'
        ? ['Reopened', 'bad']
        : gDraft.failing_rules.length === 1 && gDraft.failing_rules[0] === 'approval_by_role'
          ? ['Ready for the DRI', 'warn']
          : [`Waiting · ${plural(gDraft.failing_rules.filter((r) => r !== 'approval_by_role').length, 'rule')} open`, 'warn'];
  const drift = s.drift;
  const driftLine = !s.baseline
    ? 'Not approved yet'
    : !drift || !drift.changes
      ? 'No spec changes since approval'
      : `${plural(drift.changes, 'spec change')} since approval, ${drift.unexplained ? `${drift.unexplained} unexplained` : 'all explained'}`;

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Features', href: '/' }, { label: slug, mono: true }]}
        title={i.title}
        aside={
          <Badge tone={phaseTone(s.phase)} big>
            Phase: {phaseLabel(s.phase)}
          </Badge>
        }
      >
        <div className="flex flex-wrap items-center gap-x-[18px] gap-y-2">
          <span className="small">
            Work item{' '}
            {i.work_item_url ? (
              <a href={i.work_item_url} target="_blank" rel="noreferrer" className="font-semibold">
                {workItem(i.work_item_url)}
              </a>
            ) : (
              <strong className="text-ink">none</strong>
            )}
          </span>
          {people.map((a) => (
            <PersonChip key={a.ref} handle={a.person} role={ROLE_SHORT[a.role] || a.role} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
          <Link to={`/i/${slug}/draft`}>
            {s.baseline ? `Spec ${s.baseline.ref} · draft rev ${d.draft?.rev ?? '—'}` : `Draft${d.draft ? ` rev ${d.draft.rev}` : ''} · review`}
          </Link>
          <Link to={`/i/${slug}/drift`}>Drift report</Link>
          <Link to={`/i/${slug}/reviews`}>Review queue{s.open.review_items ? ` (${s.open.review_items})` : ''}</Link>
          <Link to={`/i/${slug}/activity`}>Activity</Link>
        </div>
      </PageHeader>

      <section className="card px-[18px] py-4 flex flex-col gap-2.5 border-2 border-human" aria-labelledby="need-h">
        <div className="flex flex-wrap gap-3 items-center justify-between">
          <h2 id="need-h" className="text-human">
            Needs your decision
          </h2>
          {needs.length > 0 && (
            <span className="small">
              {plural(needs.length, 'item')} · {needs[0].kind === 'review_item' ? needs[0].target : needs[0].ref} blocks {blocksText(needs[0])}
            </span>
          )}
        </div>
        {needs.length === 0 && <p className="m-0 text-ink-muted text-[13px]">Nothing here needs you, {nm(persona)}, right now.</p>}
        {needs.map((w) => (
          <div key={w.key} className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2.5 pt-2.5 border-t border-line-soft">
            <div className="flex-[1_1_300px] min-w-0 flex flex-col gap-0.5">
              <span className="small">
                {itemLabel(w)} · <span className={w.overdue ? 'text-bad font-semibold' : ''}>{due(w.due_at)}</span>
              </span>
              <strong className="text-[15px]">{itemTitle(w)}</strong>
            </div>
            <Link to={itemHref(w)} className="btn btn-primary no-underline hover:text-white">
              {w.kind === 'gap' ? 'Answer' : w.kind === 'decision' ? 'Rule' : w.kind === 'approval' ? (w.target === 'draft' ? 'Review draft' : 'Open PR review') : w.kind === 'manual_ac' ? 'Sign' : 'Open'}
            </Link>
          </div>
        ))}
        {others.length > 0 && (
          <div className="small pt-2 border-t border-line-soft">
            Waiting on others:{' '}
            {others.map((w, n) => (
              <span key={w.key}>
                {n > 0 && ', '}
                <Link to={itemHref(w)}>
                  {nm(w.person)} ({w.kind === 'review_item' ? w.target : w.ref})
                </Link>
              </span>
            ))}
          </div>
        )}
      </section>

      <div className="flex flex-wrap gap-[22px] items-start">
        <section className="card flex-[999_1_560px] min-w-0" aria-labelledby="log-h">
          <CardHead id="log-h" title="Decisions" aside={driftLine} />
          {log.length === 0 ? (
            <Empty>The agent is still writing the draft. Decisions will appear here.</Empty>
          ) : (
            <ol className="m-0 p-0 list-none">
              {log.map((l) => (
                <li key={l.ref} className="flex flex-wrap gap-x-[14px] gap-y-1.5 px-[18px] py-3 items-baseline border-t border-line-soft first:border-t-0">
                  <Link to={`/i/${slug}/r/${l.ref}`} className={`font-mono font-semibold text-[13px] basis-11 shrink-0 ${l.struck ? 'line-through text-ink-muted' : 'text-ink'}`}>
                    {l.ref}
                  </Link>
                  <span className="flex-[1_1_300px] min-w-0">
                    <strong className={l.struck ? 'line-through text-ink-muted' : ''}>{l.text}</strong>
                    <span className="small block">{l.sub}</span>
                  </span>
                  <Badge tone={l.tone}>{l.badge}</Badge>
                </li>
              ))}
            </ol>
          )}
        </section>
        <aside className="flex-[1_1_300px] min-w-0 flex flex-col gap-[22px]">
          <section className="card px-[18px] py-4 flex flex-col gap-2" aria-labelledby="gates-h">
            <h2 id="gates-h" className="text-[17px]">
              Gates
            </h2>
            <Kv k="Gate 1 · draft" v={g1[0]} vClass={toneText(g1[1])} />
            <Kv k="PR reviews" v={s.tasks.length ? `${approved} of ${s.tasks.length} approved` : '—'} />
            <Kv
              k="Gate 3 · criteria green"
              v={!liveAcs ? '—' : gValid?.status === 'PASSED' ? `${liveAcs} of ${liveAcs} green` : `${Math.max(0, liveAcs - notGreen)} of ${liveAcs} green`}
              vClass={gValid?.status === 'PASSED' ? 'text-ok' : ''}
            />
            {guards.kind === 'error' ? (
              <Kv k="Deploy to staging" v="could not check" vClass="text-bad" />
            ) : guards.kind === 'loading' ? (
              <Kv k="Deploy to staging" v="checking…" vClass="text-ink-muted" />
            ) : guards.data.length === 0 ? (
              <Kv k="Deploy to staging" v="—" />
            ) : (
              guards.data.map((g) => <Kv key={g.task} k={`Deploy ${g.task} to staging`} v={g.decision} vClass={g.decision === 'GO' ? 'text-ok' : 'text-bad'} />)
            )}
          </section>
          <section className="card px-[18px] py-4 flex flex-col gap-2" aria-labelledby="ag-h">
            <h2 id="ag-h" className="text-[17px]">
              Agents working
            </h2>
            {agents.length === 0 && <span className="small">No agent work is queued on this right now.</span>}
            {agents.map((a) => (
              <div key={a.key} className="flex flex-col text-[13px]">
                <span>
                  <span className="font-mono text-agent font-semibold">{a.lease ? who(String(a.lease.holder)) : a.kind}</span> on {a.ref || a.kind}
                  <span className="small"> · {a.lease ? 'claimed' : 'queued'}</span>
                </span>
                <span className="small">{a.why}</span>
              </div>
            ))}
          </section>
        </aside>
      </div>

      <section className="card" aria-labelledby="tasks-h">
        <CardHead
          id="tasks-h"
          title="Tasks"
          aside={s.tasks.length ? `${plural(s.tasks.length, 'task')} · ${plural(new Set(s.tasks.map((t) => asText(t.fields.repo))).size, 'repo')}` : undefined}
        />
        {s.tasks.length === 0 ? (
          <Empty>Tasks appear after the draft is approved and planned.</Empty>
        ) : (
          <div className="tbl">
            <table className="min-w-[820px]">
              <thead>
                <tr>
                  <th scope="col">Task</th>
                  <th scope="col">Repo</th>
                  <th scope="col">Implements</th>
                  <th scope="col">Covers</th>
                  <th scope="col">Status</th>
                  <th scope="col">Now</th>
                </tr>
              </thead>
              <tbody>
                {s.tasks.map((t) => (
                  <tr key={t.ref}>
                    <td>
                      <span className="font-mono font-semibold">{t.ref}</span> {t.title}
                    </td>
                    <td className="font-mono text-xs">{asText(t.fields.repo)}</td>
                    <td className="text-xs">
                      <Refs slug={slug} refs={asList(t.fields.implements)} />
                    </td>
                    <td className="text-xs">
                      <Refs slug={slug} refs={asList(t.fields.covers)} />
                    </td>
                    <td>
                      <StatusBadge status={t.status} pill={t.pill} />
                    </td>
                    <td>
                      <span className="small">{taskNow(t)}</span>{' '}
                      <Link to={`/i/${slug}/t/${t.ref}`} className="text-xs font-semibold whitespace-nowrap">
                        {asText(t.fields.pr_url) ? 'Open PR review' : 'Details'}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {i.spec_snapshot?.requirement && (
        <details className="card px-[18px] py-4">
          <summary className="cursor-pointer font-semibold">Requirement (pinned {i.snapshot_hash.slice(0, 8)})</summary>
          <div className="mt-3">
            <Markdown text={i.spec_snapshot.requirement} slug={slug} />
          </div>
        </details>
      )}
    </>
  );
}

