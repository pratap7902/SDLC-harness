import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import type { ActivityEntry, ApprovalItem, DecisionItem, GapItem, Inbox, InboxItem, InitiativeRow, ManualAcItem, ReviewInboxItem, ReviewItem, WriteResult } from '../api';
import { api, errorText, postJson, useJson, useJsonAll, useRefresh } from '../lib/api';
import { ROLE_LABEL, ago, asText, due, nm, plural, shortSha, who } from '../lib/format';
import { Inline, Refs, refHref } from '../lib/links';
import { usePersona } from '../lib/persona';
import { useToast } from '../lib/toast';
import { blocksText, isBlocking, itemLabel, itemTitle } from '../lib/waiting';
import { Badge, Banner, Card, Empty, Field } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { LoadError, Loading } from '../components/state';

/** After a human write: say what the service did with it (what went up for review). */
function resultText(r: WriteResult): string {
  const parts: string[] = [];
  if (r.review_items.length) parts.push(`${plural(r.review_items.length, 'record')} put up for review: ${r.review_items.join('; ')}`);
  if (r.gates_changed.length) parts.push(`gates changed: ${r.gates_changed.join(', ')}`);
  if (r.baseline) parts.push(`baseline ${r.baseline} frozen`);
  return parts.join(' · ');
}

const OTHER = '__other__';

function GapForm({ it, canAct, onDone }: { it: GapItem; canAct: boolean; onDone: (msg: string) => void }) {
  const [pick, setPick] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const options = it.options || [];
  const chosen = options.find((o) => o.key === pick);
  const proposed = asText(it.record.fields.proposed_change);
  const needsText = pick === OTHER || options.length === 0;
  const ready = needsText ? reason.trim().length > 0 : !!pick;
  const send = async () => {
    setBusy(true);
    setError('');
    try {
      const body = needsText ? { answer: reason.trim() } : { choice: pick, answer: reason.trim() ? `${chosen?.label}: ${reason.trim()}` : '' };
      const r = await postJson<WriteResult>(`${api('initiatives', it.initiative, 'gaps', it.ref, 'answer')}`, body);
      const extra = resultText(r);
      onDone(`${it.ref} answered${chosen ? `: ${chosen.label}` : ''}. ${extra || 'The agent picks it up from here.'}`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {options.length > 0 && (
        <fieldset className="border-0 p-0 m-0 flex flex-col gap-2.5">
          <legend className="eyebrow mb-2">Options</legend>
          {[...options, { key: OTHER, label: 'Something else', consequence: 'None of these fit. Type the answer below; the agent follows it or asks a follow-up.' }].map((o) => {
            const on = pick === o.key;
            return (
              <label
                key={o.key}
                htmlFor={`opt-${o.key}`}
                className={`flex gap-2.5 rounded-item cursor-pointer items-start ${on ? 'border-2 border-agent bg-agent-soft px-[13px] py-[11px]' : 'border border-line px-[14px] py-3 hover:border-line-hover'}`}
              >
                <input type="radio" id={`opt-${o.key}`} name={`opt-${it.key}`} checked={on} disabled={!canAct} onChange={() => setPick(o.key)} className="mt-[3px]" />
                <span className="flex flex-col gap-0.5">
                  <span>
                    <strong>{o.label}</strong> {it.recommendation === o.key && <Badge tone="agent">recommended</Badge>}
                  </span>
                  {o.consequence && (
                    <span className="small text-[13px]">
                      <Inline text={o.consequence} slug={it.initiative} />
                    </span>
                  )}
                </span>
              </label>
            );
          })}
          {it.recommendation_why && (
            <p className="m-0 small text-[13px]">
              <span className="font-semibold text-agent">Why the agent recommends {options.find((o) => o.key === it.recommendation)?.label || it.recommendation}:</span>{' '}
              <Inline text={it.recommendation_why} slug={it.initiative} />
            </p>
          )}
        </fieldset>
      )}
      {pick && (
        <div className="flex flex-col gap-1.5 px-[14px] py-3 bg-page rounded-item text-[13px]">
          <strong>If you pick this:</strong>
          <ul className="m-0 pl-[18px] list-disc">
            {chosen?.consequence && (
              <li>
                <Inline text={chosen.consequence} slug={it.initiative} />
              </li>
            )}
            {pick === OTHER && <li>Your text becomes the answer, word for word.</li>}
            {it.blocks.length > 0 && (
              <li>
                {it.level === 'SHOULD' ? 'Settles' : 'Unblocks'} <Refs slug={it.initiative} refs={it.blocks} />
              </li>
            )}
            {proposed && (
              <li>
                The agent proposed this spec change: <Inline text={proposed} slug={it.initiative} />
              </li>
            )}
            <li>Records that rest on this gap go up for review, routed to whoever owns them.</li>
          </ul>
          <span className="small">Your answer is recorded with your name. After the draft is approved, it shows as the reason in the drift report at PR review.</span>
        </div>
      )}
      <Field label={needsText ? 'Answer' : 'Why'} htmlFor="reason" required={needsText} optional={needsText ? undefined : 'optional · shown as the reason in the drift report'}>
        <textarea id="reason" className="input" placeholder={needsText ? 'Your answer' : 'One line is enough'} value={reason} disabled={!canAct} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {error && <Banner tone="bad" role="alert">{error}</Banner>}
      <div className="flex flex-wrap gap-3 items-center">
        <button type="button" className="btn btn-primary btn-lg" disabled={!canAct || !ready || busy} onClick={send}>
          {busy ? 'Answering…' : `Answer ${it.ref}`}
        </button>
        <span className="small">{!canAct ? '' : ready ? 'Recorded as a human answer: agents cannot write it.' : needsText ? 'Type an answer.' : 'Pick an option to answer.'}</span>
      </div>
    </>
  );
}

function DecisionForm({ it, canAct, onDone }: { it: DecisionItem; canAct: boolean; onDone: (msg: string) => void }) {
  const [verdict, setVerdict] = useState(it.provisional_verdict || '');
  const [rationale, setRationale] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const send = async () => {
    setBusy(true);
    setError('');
    try {
      const r = await postJson<WriteResult>(api('initiatives', it.initiative, 'decisions', it.ref, 'rule'), { verdict: verdict.trim(), rationale: rationale.trim() });
      onDone(`${it.ref} ruled: ${verdict.trim()}. ${resultText(r)}`.trim());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {it.options.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="eyebrow">Options</span>
          <div className="tbl border border-line rounded-item">
            <table className="min-w-[460px]">
              <tbody>
                {it.options.map((o) => (
                  <tr key={o.name}>
                    <td className="font-semibold w-40">{o.name}</td>
                    <td>
                      {o.consequences}
                      {o.cost_risk && <div className="small">Cost / risk: {o.cost_risk}</div>}
                    </td>
                    <td className="w-24">
                      <button type="button" className="btn btn-link min-h-0 text-xs" disabled={!canAct} onClick={() => setVerdict(o.consequences ? `${o.name}: ${o.consequences}` : o.name)}>
                        Use this
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {it.provisional_verdict && <p className="m-0 text-[13px]">Work continues on the provisional verdict: <strong>{it.provisional_verdict}</strong></p>}
      <Field label="Verdict" htmlFor="verdict" required>
        <input id="verdict" className="input" value={verdict} disabled={!canAct} onChange={(e) => setVerdict(e.target.value)} placeholder="What is decided" />
      </Field>
      <Field label="Rationale" htmlFor="rationale" required hint="Why — cite the gap or standard that settles it (refs like G-1 link up).">
        <textarea id="rationale" className="input" value={rationale} disabled={!canAct} onChange={(e) => setRationale(e.target.value)} />
      </Field>
      {error && <Banner tone="bad" role="alert">{error}</Banner>}
      <div className="flex flex-wrap gap-3 items-center">
        <button type="button" className="btn btn-primary btn-lg" disabled={!canAct || busy || !verdict.trim() || !rationale.trim()} onClick={send}>
          {busy ? 'Ruling…' : `Rule ${it.ref}`}
        </button>
        <span className="small">{canAct && (!verdict.trim() || !rationale.trim()) ? 'A verdict and a rationale are both required.' : ''}</span>
      </div>
    </>
  );
}

function ReviewForm({ it, canAct, onDone }: { it: ReviewInboxItem; canAct: boolean; onDone: (msg: string) => void }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const send = async (resolution: 'upheld' | 'revised') => {
    setBusy(true);
    setError('');
    try {
      await postJson<ReviewItem>(api('initiatives', it.initiative, 'reviews', it.review_item_id, 'resolve'), { resolution, note: note.trim() });
      onDone(resolution === 'upheld' ? `Upheld: ${it.target} still holds. The ripple stops here.` : `Marked revised: ${it.target} was changed to fit ${it.cause}.`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Field label="Note" htmlFor="rnote" required hint="Why it still holds, or what was changed.">
        <textarea id="rnote" className="input" value={note} disabled={!canAct} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {error && <Banner tone="bad" role="alert">{error}</Banner>}
      <div className="flex flex-wrap gap-3 items-center">
        <button type="button" className="btn btn-primary btn-lg" disabled={!canAct || busy || !note.trim()} onClick={() => send('upheld')}>
          Still holds
        </button>
        <button type="button" className="btn btn-lg" disabled={!canAct || busy || !note.trim()} onClick={() => send('revised')}>
          Revised it
        </button>
        {canAct && !note.trim() && <span className="small">A note is required either way.</span>}
      </div>
    </>
  );
}

function SignForm({ it, canAct, onDone }: { it: ManualAcItem; canAct: boolean; onDone: (msg: string) => void }) {
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const send = async () => {
    setBusy(true);
    setError('');
    try {
      await postJson<WriteResult>(api('initiatives', it.initiative, 'criteria', it.ref, 'sign'), { at_sha: it.at_sha || '' });
      onDone(`${it.ref} signed at ${shortSha(it.at_sha)}.`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <label htmlFor="signck" className="flex gap-2.5 border border-line rounded-item px-[14px] py-3 cursor-pointer text-[13px] items-start">
        <input type="checkbox" id="signck" className="mt-[3px]" checked={checked} disabled={!canAct} onChange={(e) => setChecked(e.target.checked)} />
        <span>I checked this in the test environment at {it.at_sha ? <span className="font-mono">{shortSha(it.at_sha)}</span> : 'the PR head'} and it behaves as written.</span>
      </label>
      {error && <Banner tone="bad" role="alert">{error}</Banner>}
      <div className="flex flex-wrap gap-3 items-center">
        <button type="button" className="btn btn-primary btn-lg" disabled={!canAct || !checked || busy} onClick={send}>
          {busy ? 'Signing…' : `Sign ${it.ref}`}
        </button>
      </div>
    </>
  );
}

function ApprovalPanel({ it }: { it: ApprovalItem }) {
  const href = it.target === 'draft' ? `/i/${it.initiative}/draft` : `/i/${it.initiative}/t/${it.target}`;
  return (
    <div className="flex flex-col gap-3">
      {it.drift && (
        <p className="m-0 text-[13px]">
          Drift for {it.target}: {it.drift.changes ? `${plural(it.drift.changes, 'change')}, ${it.drift.unexplained ? `${it.drift.unexplained} unexplained` : 'all explained'}` : 'no spec changes since approval'}.
          {it.stale_approvals && it.stale_approvals.length > 0 && <strong className="text-warn"> Your earlier approval ({it.stale_approvals.join(', ')}) went stale.</strong>}
        </p>
      )}
      <div>
        <Link to={href} className="btn btn-primary btn-lg no-underline hover:text-white">
          {it.target === 'draft' ? 'Review the draft' : 'Open PR review'}
        </Link>
      </div>
    </div>
  );
}

function Detail({ it, canAct, onDone }: { it: InboxItem; canAct: boolean; onDone: (msg: string) => void }) {
  const slug = it.initiative;
  const ref = it.kind === 'review_item' ? it.target : it.ref;
  const tone = it.kind === 'approval' ? 'agent' : 'human';
  return (
    <Card as="article" className="flex-[999_1_560px] flex flex-col gap-4 px-[22px] py-5">
      <div className="text-xs text-ink-muted flex flex-wrap gap-x-2.5 gap-y-1 items-center">
        <Link to={refHref(slug, ref)} className="font-mono font-semibold text-ink">
          {ref}
        </Link>
        <Badge tone={tone}>{itemLabel(it)}</Badge>
        <span>
          <Link to={`/i/${slug}`}>{it.initiative_title}</Link> · <span className={it.overdue ? 'text-bad font-semibold' : ''}>{due(it.due_at)}</span>
          {it.route.role && ` · routed to ${ROLE_LABEL[it.route.role] || it.route.role}${it.route.fallback ? ' (fallback: nobody holds the role)' : ''}`}
        </span>
      </div>
      <h2 className="text-[22px] leading-[1.3]">{itemTitle(it)}</h2>
      <div className="flex flex-col gap-1.5">
        <span className="eyebrow">Why this came up</span>
        {it.kind === 'gap' && (
          <>
            {it.context && <Markdown text={it.context} slug={slug} />}
            {asText(it.record.fields.why_now) && (
              <blockquote className="m-0 px-3 py-2 bg-page rounded-md text-[13px] text-ink-soft">
                <Inline text={asText(it.record.fields.why_now)} slug={slug} /> · <span className="font-mono">{who(asText(it.record.fields.asked_by) || it.record.created_by)}</span>
              </blockquote>
            )}
          </>
        )}
        {it.kind === 'decision' && (
          <p className="m-0 max-w-[76ch]">
            {it.title}. {it.level === 'MUST' ? 'A MUST decision: only a person may rule it, and work that implements it waits.' : 'Escalated to a person.'}
          </p>
        )}
        {it.kind === 'review_item' && (
          <p className="m-0 max-w-[76ch]">
            <Link to={refHref(slug, it.cause)} className="font-mono">
              {it.cause}
            </Link>{' '}
            changed ({it.what_moved}). <Link to={refHref(slug, it.target)} className="font-mono">{it.target}</Link> rests on it — say whether it still holds.
          </p>
        )}
        {it.kind === 'approval' && (
          <p className="m-0 max-w-[76ch]">{it.target === 'draft' ? 'The draft passes every precondition; the DRI approves it once, and that becomes the spec the build is checked against.' : 'The PR is open and every check but your approval passes. Review the drift, not the whole feature.'}</p>
        )}
        {it.kind === 'manual_ac' && (
          <p className="m-0 max-w-[76ch]">
            This criterion needs a person: <Inline text={it.text} slug={slug} />
          </p>
        )}
        <span className={`text-[13px] ${isBlocking(it) ? 'text-bad font-semibold' : 'small'}`}>Blocks: {blocksText(it)}</span>
      </div>
      {it.kind === 'gap' && <GapForm key={it.key} it={it} canAct={canAct} onDone={onDone} />}
      {it.kind === 'decision' && <DecisionForm key={it.key} it={it} canAct={canAct} onDone={onDone} />}
      {it.kind === 'review_item' && <ReviewForm key={it.key} it={it} canAct={canAct} onDone={onDone} />}
      {it.kind === 'manual_ac' && <SignForm key={it.key} it={it} canAct={canAct} onDone={onDone} />}
      {it.kind === 'approval' && <ApprovalPanel it={it} />}
    </Card>
  );
}

/** What this person did lately, from each initiative's activity feed (actor filter). */
function RecentlyResolved({ person }: { person: string }) {
  const list = useJson<InitiativeRow[]>('/api/initiatives');
  const slugs = list.kind === 'ready' ? list.data.map((f) => f.slug) : null;
  const feeds = useJsonAll<ActivityEntry[]>(slugs ? slugs.map((s) => `${api('initiatives', s, 'activity')}?${new URLSearchParams({ actor: person, limit: '10' })}`) : null);
  if (list.kind === 'error' || feeds.kind === 'error') return <span className="small text-bad">Could not load recent activity.</span>;
  if (feeds.kind !== 'ready' || !slugs) return null;
  const rows = feeds.data
    .flatMap((f, i) => f.map((e) => ({ ...e, slug: slugs[i] })))
    .filter((e) => e.kind === 'revision' && e.actor_kind === 'human' && e.type !== 'initiative' && e.type !== 'assignment')
    .sort((a, b) => b.at.localeCompare(a.at))
    .slice(0, 5);
  if (!rows.length) return null;
  return (
    <div className="flex flex-col gap-1.5 mt-3">
      <span className="eyebrow">Recently resolved</span>
      {rows.map((e) => (
        <div key={`${e.slug}:${e.ref}:${e.rev}`} className="small">
          <span className="text-ok" aria-hidden="true">
            ✓
          </span>{' '}
          <Link to={refHref(e.slug, e.ref)} className="font-mono">
            {e.ref}
          </Link>{' '}
          · {e.title} · <em>{e.status.toLowerCase()}</em> · {ago(e.at)}
        </div>
      ))}
    </div>
  );
}

export default function InboxPage() {
  const { person = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { persona, setPersona } = usePersona();
  const { bump } = useRefresh();
  const say = useToast();
  const inbox = useJson<Inbox>(api('inbox', person));
  const selKey = params.get('item');
  const items = inbox.kind === 'ready' ? inbox.data.items : [];
  const sel = items.find((i) => i.key === selKey) || items[0] || null;
  const canAct = persona === person;

  // A stale ?item= (already resolved) falls back to the first item quietly.
  useEffect(() => {
    if (inbox.kind === 'ready' && selKey && !items.some((i) => i.key === selKey)) setParams({}, { replace: true });
  }, [inbox.kind, selKey, items, setParams]);

  if (inbox.kind === 'error') return <LoadError what={`${nm(person)}'s inbox`} message={inbox.message} onRetry={inbox.reload} />;
  if (inbox.kind === 'loading') return <Loading what="the inbox" />;
  const data = inbox.data;
  const onDone = (msg: string) => {
    say(msg);
    setParams({}, { replace: true });
    bump();
  };

  return (
    <>
      <header className="flex flex-col gap-1">
        <h1>{canAct ? 'Your inbox' : `${nm(person)}'s inbox`}</h1>
        <p className="m-0 font-semibold">
          {data.count ? `${data.count} waiting${data.overdue ? ` · ${data.overdue} overdue` : ''} · sorted by what they block` : canAct ? 'Nothing is waiting on you' : `Nothing is waiting on ${nm(person)}`}
        </p>
        <p className="m-0 text-ink-muted">Questions and reviews routed by role. Other work keeps moving while you decide.</p>
      </header>
      {!canAct && (
        <Banner tone="human">
          You're viewing as {nm(persona)}. Only {nm(person)} answers these — answers are recorded under the name of whoever sends them.{' '}
          <button type="button" className="btn btn-link min-h-0 text-human underline" onClick={() => setPersona(person)}>
            Switch to {nm(person)}
          </button>
        </Banner>
      )}
      <div className="flex flex-wrap gap-[22px] items-start">
        <section className="flex-[1_1_300px] min-w-0 flex flex-col gap-2" aria-label="Items">
          {data.items.map((it) => {
            const on = sel?.key === it.key;
            return (
              <button
                key={it.key}
                type="button"
                aria-current={on}
                onClick={() => setParams({ item: it.key })}
                className={`flex flex-col gap-1 bg-white rounded-item text-left cursor-pointer w-full ${on ? 'border-2 border-ink px-[13px] py-[11px]' : 'border border-line px-[14px] py-3 hover:border-line-hover'}`}
              >
                <span className="flex justify-between gap-2 text-xs">
                  <span className="font-mono font-semibold">
                    {it.kind === 'review_item' ? it.target : it.ref} · {itemLabel(it)}
                  </span>
                  <span className={`font-semibold ${it.overdue ? 'text-bad' : 'text-warn'}`}>{due(it.due_at)}</span>
                </span>
                <span className="font-semibold">{itemTitle(it)}</span>
                <span className="small">
                  {it.initiative} · blocks {blocksText(it)}
                </span>
              </button>
            );
          })}
          {data.items.length === 0 && <Empty boxed>{canAct ? "You're clear. Nothing is waiting on you." : `${nm(person)} is clear.`}</Empty>}
          <RecentlyResolved person={person} />
        </section>
        {sel && <Detail key={sel.key} it={sel} canAct={canAct} onDone={onDone} />}
      </div>
    </>
  );
}
