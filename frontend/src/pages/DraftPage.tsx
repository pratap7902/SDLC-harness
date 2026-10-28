import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { DraftPage as Draft, InitiativeState, RecordJson, Revision, WriteResult } from '../api';
import { all, api, errorText, postJson, useJson, useRefresh } from '../lib/api';
import { asList, asText, dateTime, nm, plural, ruleText, who } from '../lib/format';
import { Inline, Refs } from '../lib/links';
import { usePersona } from '../lib/persona';
import { useToast } from '../lib/toast';
import { useAllWaiting } from '../lib/waiting';
import { Badge, Banner, Card, CardHead, Check, Empty, Field, StatusBadge, Tabs } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';

type Tab = 'hld' | 'lld' | 'test' | 'scope';

/** An option is "chosen" when the verdict names it and names no other option. */
function chosenOption(d: RecordJson): string | null {
  const verdict = asText(d.fields.verdict).toLowerCase();
  if (!verdict) return null;
  const names = ((d.fields.options as { name: string }[] | undefined) || []).map((o) => o.name);
  const hits = names.filter((n) => verdict.includes(n.toLowerCase()));
  return hits.length === 1 ? hits[0] : null;
}

function DecisionBlock({ d, slug }: { d: RecordJson; slug: string }) {
  const f = d.fields;
  const options = (f.options as { name: string; consequences?: string; cost_risk?: string }[] | undefined) || [];
  const chosen = chosenOption(d);
  const superseded = d.status === 'SUPERSEDED';
  return (
    <article className={`flex flex-col gap-2 border border-line rounded-item px-4 py-[14px] ${superseded ? 'opacity-70' : ''}`}>
      <div className="flex flex-wrap gap-2 items-center">
        <Link to={`/i/${slug}/r/${d.ref}`} className={`font-mono font-semibold ${superseded ? 'line-through text-ink-muted' : 'text-ink'}`}>
          {d.ref}
        </Link>
        <strong>{asText(f.question) || d.title}</strong>
        <StatusBadge status={d.status} pill={d.status === 'OPEN' ? 'red' : d.pill} />
        <Badge tone="muted">
          {asText(f.level) || '—'} · {asText(f.domain) || '—'}
        </Badge>
      </div>
      <div className="text-[15px]">
        <strong>Verdict:</strong> {asText(f.verdict) ? <Inline text={asText(f.verdict)} slug={slug} /> : <span className="text-human font-semibold">Not decided yet</span>}
      </div>
      {options.length > 0 && (
        <div className="tbl">
          <table className="min-w-[460px]">
            <tbody>
              {options.map((o) => (
                <tr key={o.name}>
                  <td className="font-semibold w-40 !pl-0">
                    {o.name} {chosen === o.name && <span className="text-ok text-xs">chosen</span>}
                  </td>
                  <td className={chosen === o.name ? '' : 'text-ink-muted'}>
                    {o.consequences}
                    {o.cost_risk && <span className="small"> · {o.cost_risk}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <span className="small">
        {superseded && <>Superseded by <Refs slug={slug} refs={d.superseded_by || []} />. </>}
        {asText(f.rationale) && <Inline text={asText(f.rationale)} slug={slug} />}
        {asList(f.cites).length > 0 && <> · cites {asList(f.cites).join(', ')}</>}
        {(d.sourced_acs || []).length > 0 && <> · criteria <Refs slug={slug} refs={d.sourced_acs || []} /></>}
      </span>
    </article>
  );
}

function sectionText(draft: RecordJson | null, tab: Tab): string {
  const f = draft?.fields || {};
  if (tab === 'hld') return asText(f.hld);
  if (tab === 'lld') return asText(f.lld);
  if (tab === 'test') return asText(f.test_strategy);
  return '';
}

export default function DraftPage() {
  const { slug = '' } = useParams();
  const { persona } = usePersona();
  const { bump } = useRefresh();
  const say = useToast();
  const page = useJson<Draft>(api('initiatives', slug, 'draft'));
  const state = useJson<InitiativeState>(api('initiatives', slug));
  const history = useJson<Revision[]>(api('initiatives', slug, 'records', 'draft', 'history'));
  const findings = useJson<RecordJson[]>(`${api('initiatives', slug, 'records')}?type=finding`);
  const waiting = useAllWaiting();
  const [tab, setTab] = useState<Tab>('hld');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const loaded = all(page, state, findings, waiting);
  if (loaded.kind === 'error') return <LoadError what={`the draft of ${slug}`} message={loaded.message} onRetry={page.reload} />;
  if (loaded.kind === 'loading') return <Loading what="the draft" />;
  const [d, s, fs, items] = loaded.data;
  const draft = d.draft;
  const rev = draft?.rev ?? 0;
  const approved = d.gate.status === 'PASSED';
  const reopened = draft?.status === 'REOPENED';
  const rules = d.gate.rules.filter((r) => r.name !== 'approval_by_role');
  const ready = rules.every((r) => r.passed);
  const isDri = persona === d.approver;
  const openGaps = d.gaps.filter((g) => g.status === 'OPEN');
  const openDecs = d.decisions.filter((x) => x.status === 'OPEN');
  const live = d.decisions.filter((x) => x.status !== 'SUPERSEDED');
  const draftFindings = fs.filter((f) => asList(f.fields.target).includes('draft'));
  const scopeIn = asList(draft?.fields.scope_in);
  const scopeOut = asList(draft?.fields.scope_out);
  const drift = s.drift;

  const act = async (kind: 'approve' | 'changes') => {
    setBusy(true);
    setError('');
    try {
      if (kind === 'approve') {
        const r = await postJson<WriteResult>(api('initiatives', slug, 'approvals'), { target: 'draft', role: 'dri', note: note.trim() || undefined });
        say(`Approved. Baseline ${r.baseline || 'B-n'} is frozen; from here every spec change needs a recorded reason.`);
      } else {
        await postJson<WriteResult>(api('initiatives', slug, 'records'), {
          ops: [{ type: 'finding', title: `Changes requested on draft rev ${rev}`, fields: { summary: note.trim().slice(0, 400), details: note.trim(), severity: 'major', target: ['draft'], at_rev: String(rev) } }],
        });
        say('Changes requested: recorded as a finding on the draft for the drafting agent. You review the next revision here.');
      }
      setNote('');
      bump();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const headline = approved ? `Draft rev ${rev} · approved` : reopened ? `Draft rev ${rev} · reopened` : ready ? `Draft rev ${rev} is ready for approval` : `Draft rev ${rev} · waiting on open questions`;
  const open = openGaps.length + openDecs.length;
  const hint = approved
    ? 'Changes from here on need a recorded reason and show in each PR’s drift report.'
    : !isDri
      ? `Only the DRI (${nm(d.approver)}) can approve or request changes. Switch “Viewing as” to act.`
      : !ready
        ? 'Resolve the open items above first.'
        : `Approving freezes this spec as a baseline. Later changes need a recorded reason.`;

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Features', href: '/' }, { label: slug, href: `/i/${slug}`, mono: true }, { label: 'Draft' }]}
        title={headline}
        badge={
          <Badge tone="human" big>
            Touchpoint 1 · draft review
          </Badge>
        }
      >
        <p className="m-0 font-semibold">
          {plural(live.length, 'decision')} and {plural(d.criteria.filter((c) => c.status !== 'RETIRED').length, 'acceptance criterion', 'acceptance criteria')}.{' '}
          {open ? `${plural(open, 'question is', 'questions are')} still open.` : 'No questions are open.'}
        </p>
      </PageHeader>
      {!draft && <Banner tone="warn">No draft yet: the drafting agent has not written one for this feature.</Banner>}
      {approved && s.baseline && (
        <Banner tone="ok">
          Approved by {nm(s.baseline.approved_by)} as baseline {s.baseline.ref}.{' '}
          {drift && drift.changes ? (
            <>
              {plural(drift.changes, 'spec change')} since, {drift.unexplained ? `${drift.unexplained} unexplained` : 'all explained'}. <Link to={`/i/${slug}/drift`}>See the drift report</Link>
            </>
          ) : (
            'No spec changes since.'
          )}
        </Banner>
      )}
      {reopened && <Banner tone="bad">The draft is reopened: the spec moved since the baseline without a human reason. See the drift report.</Banner>}

      <div className="flex flex-wrap gap-[22px] items-start">
        <div className="flex-[999_1_560px] min-w-0 flex flex-col gap-[22px]">
          <Card className="px-[18px] py-4 flex flex-col gap-[14px]" aria-labelledby="ddec-h">
            <div className="flex flex-wrap gap-3 items-center justify-between">
              <h2 id="ddec-h" className="text-[17px]">
                Decisions you are approving
              </h2>
              <span className="small">The HLD and LLD below describe these</span>
            </div>
            {d.decisions.length === 0 && <Empty>No decisions yet.</Empty>}
            {[...live, ...d.decisions.filter((x) => x.status === 'SUPERSEDED')].map((x) => (
              <DecisionBlock key={x.ref} d={x} slug={slug} />
            ))}
          </Card>

          {d.gaps.length > 0 && (
            <Card aria-labelledby="dgap-h">
              <CardHead id="dgap-h" title="Questions" aside={openGaps.length ? `${openGaps.length} open` : 'all answered'} />
              <ul className="m-0 p-0 list-none">
                {d.gaps.map((g) => {
                  const w = items.find((i) => i.initiative === slug && i.ref === g.ref);
                  return (
                    <li key={g.ref} className="flex flex-wrap gap-x-[14px] gap-y-1.5 px-[18px] py-3 items-baseline border-t border-line-soft first:border-t-0">
                      <Link to={`/i/${slug}/r/${g.ref}`} className="font-mono font-semibold text-[13px] text-ink">
                        {g.ref}
                      </Link>
                      <span className="flex-[1_1_300px] min-w-0">
                        <strong>{asText(g.fields.question)}</strong>
                        <span className="small block">
                          {g.status === 'OPEN' ? (
                            <>
                              Waiting on {nm(w?.person)}
                              {w && (
                                <>
                                  {' · '}
                                  <Link to={`/inbox/${w.person}?item=${encodeURIComponent(w.key)}`}>answer in the inbox</Link>
                                </>
                              )}
                            </>
                          ) : (
                            <>
                              Answered by {nm(asText(g.fields.answered_by))}: <Inline text={asText(g.fields.answer)} slug={slug} />
                            </>
                          )}
                        </span>
                      </span>
                      <StatusBadge status={g.status} pill={g.pill} />
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}

          <Card className="px-[18px] py-4 flex flex-col gap-2.5" aria-labelledby="dprob-h">
            <h2 id="dprob-h" className="text-[17px]">
              Problem
            </h2>
            {asText(draft?.fields.problem) ? <Markdown text={asText(draft?.fields.problem)} slug={slug} /> : <span className="small">Not written yet.</span>}
          </Card>

          <Card className="px-[18px] py-4 flex flex-col gap-3">
            <Tabs<Tab>
              label="Design"
              value={tab}
              onChange={setTab}
              tabs={[
                ['hld', 'HLD'],
                ['lld', 'LLD'],
                ['test', 'Test strategy'],
                ['scope', 'Scope'],
              ]}
            />
            {tab === 'scope' ? (
              <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] text-[14px]">
                <div>
                  <span className="eyebrow">In</span>
                  {scopeIn.length ? (
                    <ul className="m-0 mt-1 pl-5 list-disc">
                      {scopeIn.map((x) => (
                        <li key={x}>
                          <Inline text={x} slug={slug} />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="small m-0">Not written yet.</p>
                  )}
                </div>
                <div>
                  <span className="eyebrow">Out</span>
                  {scopeOut.length ? (
                    <ul className="m-0 mt-1 pl-5 list-disc">
                      {scopeOut.map((x) => (
                        <li key={x}>
                          <Inline text={x} slug={slug} />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="small m-0">Not written yet.</p>
                  )}
                </div>
              </div>
            ) : sectionText(draft, tab) ? (
              <Markdown text={sectionText(draft, tab)} slug={slug} />
            ) : (
              <p className="small m-0">Not written yet.</p>
            )}
          </Card>

          <Card aria-labelledby="dac-h">
            <CardHead id="dac-h" title="Acceptance criteria" aside={`${d.criteria.length} · these become the tests`} />
            {d.criteria.length === 0 ? (
              <Empty>No acceptance criteria yet.</Empty>
            ) : (
              <div className="tbl">
                <table className="min-w-[640px]">
                  <thead>
                    <tr>
                      <th scope="col">Ref</th>
                      <th scope="col">Given / when / then</th>
                      <th scope="col">Level</th>
                      <th scope="col">Source</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.criteria.map((c) => {
                      const manual = asText(c.fields.manual) === 'yes';
                      return (
                        <tr key={c.ref} className={c.status === 'RETIRED' ? 'text-ink-muted' : ''}>
                          <td className="font-mono whitespace-nowrap">
                            <Link to={`/i/${slug}/r/${c.ref}`}>{c.ref}</Link>
                          </td>
                          <td className={c.status === 'RETIRED' ? 'line-through' : ''}>
                            <Inline text={asText(c.fields.text)} slug={slug} />
                          </td>
                          <td className={manual ? 'text-human font-semibold' : ''}>{manual ? `${asText(c.fields.level) || 'manual'} · QA` : asText(c.fields.level)}</td>
                          <td className="text-xs">
                            <Refs slug={slug} refs={asList(c.fields.source)} />
                          </td>
                          <td>
                            <StatusBadge status={c.status} pill={c.pill} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <aside className="flex-[1_1_300px] min-w-0 flex flex-col gap-[22px]">
          <Card className="px-[18px] py-4 flex flex-col gap-2.5" aria-labelledby="dready-h">
            <h2 id="dready-h" className="text-[17px]">
              {approved ? 'Approved' : ready ? 'Ready to approve' : 'Not ready yet'}
            </h2>
            <ul className="m-0 p-0 list-none flex flex-col gap-1.5 text-[13px]">
              {rules.map((r) => (
                <Check key={r.name} ok={r.passed}>
                  {ruleText(r.name, r.passed)}
                  {!r.passed && r.failing.length > 0 && (
                    <>
                      : <Refs slug={slug} refs={r.failing.filter((x) => /^[A-Z]+-\d+$/.test(x))} empty="" />
                      {r.failing.filter((x) => !/^[A-Z]+-\d+$/.test(x)).length > 0 && <span className="small"> {r.failing.filter((x) => !/^[A-Z]+-\d+$/.test(x)).join(', ').replace(/_/g, ' ')}</span>}
                    </>
                  )}
                </Check>
              ))}
            </ul>
            {!approved && draft && (
              <>
                <Field label="Note" htmlFor="dnote" optional="required to request changes">
                  <textarea id="dnote" className="input" value={note} disabled={!isDri} onChange={(e) => setNote(e.target.value)} />
                </Field>
                {error && <Banner tone="bad" role="alert">{error}</Banner>}
                <button type="button" className="btn btn-primary btn-lg" disabled={!(d.can_approve && isDri) || busy} onClick={() => act('approve')}>
                  Approve rev {rev} and freeze baseline
                </button>
                <button type="button" className="btn btn-lg" disabled={!isDri || !note.trim() || busy} onClick={() => act('changes')}>
                  Request changes
                </button>
              </>
            )}
            <span className="small">{hint}</span>
          </Card>

          <Card className="px-[18px] py-4 flex flex-col gap-2" aria-labelledby="dcat-h">
            <h2 id="dcat-h" className="text-[17px]">
              Catalog
            </h2>
            {d.catalog.length === 0 && <span className="small">Nothing in the draft-phase catalog.</span>}
            {d.catalog.map((c) => (
              <div key={c.item} className="flex justify-between gap-2 text-[13px]" title={c.note || c.text}>
                <span>{c.item.replace(/_/g, ' ').replace(/^./, (x) => x.toUpperCase())}</span>
                <span className={`text-right ${c.disposition === 'addressed' ? 'text-ok' : c.disposition === 'not_applicable' ? 'text-ink-muted' : 'text-bad font-semibold'}`}>
                  {c.disposition === 'UNASSESSED' ? 'not assessed' : c.disposition.replace('_', ' ')}
                </span>
              </div>
            ))}
          </Card>

          <Card className="px-[18px] py-4 flex flex-col gap-1.5" aria-labelledby="dhist-h">
            <h2 id="dhist-h" className="text-[17px]">
              History
            </h2>
            {history.kind === 'error' && <span className="small text-bad">Could not load the history: {history.message}</span>}
            {history.kind === 'loading' && <span className="small">Loading…</span>}
            {history.kind === 'ready' &&
              [
                ...history.data.map((h) => ({ at: h.at, text: `rev ${h.rev} · ${who(h.actor)} ${h.rev === 1 ? 'wrote the draft' : 'revised it'}${h.because.length ? ` because ${h.because.join(', ')}` : ''}${h.note ? ` (${h.note})` : ''}` })),
                ...draftFindings.map((f) => ({ at: f.created_at, text: `${f.ref} · ${who(f.created_by)} requested changes: ${asText(f.fields.summary)} (${f.status.toLowerCase()})` })),
                ...d.approvals.map((a) => ({ at: a.created_at, text: `${a.ref} · approved by ${nm(a.created_by)} at rev ${asText(a.fields.approved_rev)}${asText(a.fields.note) ? `: “${asText(a.fields.note)}”` : ''} (${a.status.toLowerCase()})` })),
                ...d.baselines.map((b) => ({ at: b.created_at, text: `${b.ref} frozen · ${b.label}` })),
              ]
                .sort((a, b) => a.at.localeCompare(b.at))
                .map((h, n) => (
                  <span key={n} className="small">
                    <span className="font-mono">{dateTime(h.at)}</span> · {h.text}
                  </span>
                ))}
          </Card>
        </aside>
      </div>
    </>
  );
}
