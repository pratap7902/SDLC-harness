import { useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import type { DeployGuard, TaskPage as Page, WriteResult } from '../api';
import { api, errorText, postJson, useJson, useRefresh } from '../lib/api';
import { asList, asText, nm, plural, prNumber, ruleText, shortSha, who } from '../lib/format';
import { Inline, Refs, FeatureName } from '../lib/links';
import { usePersona } from '../lib/persona';
import { useToast } from '../lib/toast';
import { Badge, Banner, Card, Field, StatusBadge } from '../components/ui';
import { DriftTimeline, SpecCompare } from '../components/DriftReport';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';

interface CoverRow {
  ac: string;
  result: string;
  test_id?: string;
  evidence?: string;
}

export default function TaskPage() {
  const { id: fid = '', ref = '' } = useParams();
  const { persona } = usePersona();
  const { bump } = useRefresh();
  const say = useToast();
  const page = useJson<Page>(api('initiatives', fid, 'tasks', ref));
  const sha = page.kind === 'ready' ? asText(page.data.task.fields.pr_sha) : '';
  const guard = useJson<DeployGuard>(sha ? `/api/deploy-guard?${new URLSearchParams({ initiative_id: fid, task: ref, sha, environment: 'staging' })}` : null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  if (page.kind === 'error') return <LoadError what={`${ref} of ${fid}`} message={page.message} onRetry={page.reload} />;
  if (page.kind === 'loading') return <Loading what="the PR review" />;
  const { task, gate, drift, approver, test_runs, findings, deploys } = page.data;
  const f = task.fields;
  const prUrl = asText(f.pr_url);
  const covers = asList(f.covers);
  const pre = gate.rules.filter((r) => r.name !== 'approval_by_role');
  const failing = pre.filter((r) => !r.passed);
  const passed = gate.status === 'PASSED';
  const current = drift.approvals.find((a) => a.status === 'CURRENT');
  const stale = drift.approvals.filter((a) => a.status === 'STALE');
  const isEngg = persona === approver;
  const approvedHere = !!current && current.at_sha === sha;
  const openFindings = findings.filter((x) => x.status === 'OPEN');

  // Which covered ACs a test run proves at the PR head (rows of each run's `covers`).
  const tested = new Map<string, { result: string; test: string; sha: string }>();
  for (const r of test_runs) {
    for (const row of (r.fields.covers as CoverRow[] | undefined) || []) {
      const prev = tested.get(row.ac);
      if (!prev || asText(r.fields.at_sha) === sha) tested.set(row.ac, { result: row.result, test: row.test_id || r.title, sha: asText(r.fields.at_sha) });
    }
  }
  const latestRun = [...test_runs].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  const act = async (kind: 'approve' | 'changes') => {
    setBusy(true);
    setError('');
    try {
      if (kind === 'approve') {
        await postJson<WriteResult>(api('initiatives', fid, 'approvals'), { target: ref, role: 'engg', at_sha: sha, note: note.trim() || undefined });
        say(`Approved ${ref} at ${shortSha(sha)}. A new push or spec change will ask you again.`);
      } else {
        await postJson<WriteResult>(api('initiatives', fid, 'records'), {
          ops: [{ type: 'finding', title: `Changes requested on ${ref}`, fields: { summary: note.trim().slice(0, 400), details: note.trim(), severity: 'blocker', target: [ref], at_sha: sha } }],
        });
        say(`Changes requested on ${ref}: a blocker finding at ${shortSha(sha)} for the implementing agent. You review again after the next push.`);
      }
      setNote('');
      bump();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  let banner: { tone: 'human' | 'ok' | 'warn'; text: ReactNode } | null = null;
  if (passed && current) banner = { tone: 'ok', text: `Approved by ${nm(current.by)} at ${shortSha(current.at_sha)}. A new push or spec change will ask again.` };
  else if (failing.length)
    banner = {
      tone: 'human',
      text: (
        <>
          Not ready for approval: {failing.map((r) => ruleText(r.name, false) + (r.failing.length ? ` (${r.failing.join(', ')})` : '')).join(' · ')}
        </>
      ),
    };
  else if (stale.length) banner = { tone: 'warn', text: `The earlier approval (${stale.map((a) => `${nm(a.by)} at ${shortSha(a.at_sha)}`).join(', ')}) is stale: the PR head or the drift below changed after it.` };

  const checks: { k: string; v: string; cls: string }[] = [
    { k: 'Pull request', v: prUrl ? `${prNumber(prUrl)} · ${asText(f.pr_state) || '—'}` : 'not opened', cls: asText(f.pr_state) === 'open' || asText(f.pr_state) === 'approved' ? 'text-ok' : 'text-warn' },
    {
      k: 'Tests at the head',
      v: latestRun ? `${latestRun.status}${asText(latestRun.fields.at_sha) === sha ? '' : ` at ${shortSha(asText(latestRun.fields.at_sha))}`}${asText(f.ci_attempts) ? ` · CI attempt ${asText(f.ci_attempts)}` : ''}` : 'no runs yet',
      cls: latestRun?.status === 'GREEN' ? 'text-ok' : latestRun ? 'text-bad' : 'text-warn',
    },
    { k: 'AI review', v: findings.length ? (openFindings.length ? `${plural(openFindings.length, 'finding')} open` : `${plural(findings.length, 'finding')}, resolved`) : 'No findings', cls: openFindings.length ? 'text-bad' : 'text-ok' },
    {
      k: 'Criteria tested',
      v: covers.length ? covers.map((ac) => `${ac} ${tested.get(ac)?.result === 'GREEN' ? '✓' : tested.has(ac) ? '✗' : '–'}`).join(' · ') : '—',
      cls: covers.every((ac) => tested.get(ac)?.result === 'GREEN') ? 'text-ok' : 'text-warn',
    },
    {
      k: 'Drift since approval',
      v: drift.status === 'NO_BASELINE' ? 'no baseline' : drift.summary.changes ? `${drift.summary.explained} explained · ${drift.summary.unexplained} unexplained` : 'No changes',
      cls: drift.summary.unexplained ? 'text-bad' : 'text-ok',
    },
  ];

  const hint = !isEngg
    ? `Only the engineering reviewer (${nm(approver)}) approves this PR. Switch “Viewing as” to act.`
    : !sha
      ? 'No PR head to approve yet.'
      : failing.length
        ? 'Resolve what the banner lists first.'
        : approvedHere && passed
          ? 'Already approved at this head.'
          : `Your approval pins ${shortSha(sha)} and this drift report (digest ${drift.digest.slice(0, 8)}). A new push or spec change makes it stale.`;

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Features', href: '/' }, { label: <FeatureName fid={fid} />, href: `/features/${fid}`, mono: true }, { label: ref, mono: true }]}
        title={`${ref} · ${task.title}`}
        badge={
          <Badge tone="human" big>
            Touchpoint 3 · PR review
          </Badge>
        }
      >
        <div className="flex flex-wrap gap-x-[18px] gap-y-1.5 small items-center">
          <span>
            <span className="font-mono text-ink">{asText(f.repo)}</span> ·{' '}
            {prUrl ? (
              <a href={prUrl} target="_blank" rel="noreferrer">
                PR {prNumber(prUrl)}
              </a>
            ) : (
              'no PR'
            )}{' '}
            at <span className="font-mono text-ink">{shortSha(sha)}</span>
          </span>
          <span>
            implements <Refs fid={fid} refs={asList(f.implements)} />
          </span>
          <span>
            covers <Refs fid={fid} refs={covers} />
          </span>
          <StatusBadge status={task.status} pill={task.pill} />
          <span>GATE_PR {gate.status}</span>
        </div>
      </PageHeader>
      {banner && <Banner tone={banner.tone}>{banner.text}</Banner>}

      <section className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]" aria-label="Checks">
        {checks.map((c) => (
          <div key={c.k} className="bg-white border border-line rounded-item px-3 py-2.5">
            <div className="small">{c.k}</div>
            <div className={`font-semibold ${c.cls}`}>{c.v}</div>
          </div>
        ))}
      </section>

      <div className="flex flex-wrap gap-[22px] items-start">
        <div className="flex-[999_1_560px] min-w-0 flex flex-col gap-[22px]">
          <DriftTimeline report={drift} fid={fid} />
          <SpecCompare report={drift} fid={fid} />
        </div>
        <aside className="flex-[1_1_300px] min-w-0 flex flex-col gap-[22px]">
          <Card className="px-[18px] py-4 flex flex-col gap-2.5" aria-labelledby="pa-h">
            <h2 id="pa-h" className="text-[17px]">
              Approve this PR
            </h2>
            <p className="m-0 text-ink-muted text-[13px]">{hint}</p>
            <Field label="Note" htmlFor="prnote" optional="required to request changes">
              <textarea id="prnote" className="input" value={note} disabled={!isEngg} onChange={(e) => setNote(e.target.value)} />
            </Field>
            {error && <Banner tone="bad" role="alert">{error}</Banner>}
            <button type="button" className="btn btn-primary btn-lg" disabled={!isEngg || !sha || failing.length > 0 || (approvedHere && passed) || busy} onClick={() => act('approve')}>
              Approve at {shortSha(sha)}
            </button>
            <button type="button" className="btn btn-lg" disabled={!isEngg || !sha || !note.trim() || busy} onClick={() => act('changes')}>
              Request changes
            </button>
            <span className="small">Request changes records your note as a blocker finding at this head; the agent fixes and pushes. You review again from here.</span>
          </Card>

          <Card className="px-[18px] py-4 flex flex-col gap-2" aria-labelledby="pf-h">
            <h2 id="pf-h" className="text-[17px]">
              AI review
            </h2>
            {findings.length === 0 && <span className="small">No findings.</span>}
            {findings.map((x) => (
              <div key={x.ref} className="flex flex-col gap-0.5 px-3 py-2.5 border border-line rounded-ctl text-[13px]">
                <span>
                  <span className="font-mono font-semibold">{x.ref}</span> · {asText(x.fields.severity)} · {who(x.created_by)}
                </span>
                <span>
                  <Inline text={asText(x.fields.summary)} fid={fid} />
                </span>
                <span className={x.status === 'OPEN' ? 'text-bad font-semibold' : 'text-ok font-semibold'}>
                  {x.status.toLowerCase()}
                  {asText(x.fields.at_sha) && ` at ${shortSha(asText(x.fields.at_sha))}`}
                </span>
              </div>
            ))}
          </Card>

          <Card className="px-[18px] py-4 flex flex-col gap-2" aria-labelledby="pt-h">
            <h2 id="pt-h" className="text-[17px]">
              Tests from criteria
            </h2>
            {covers.length === 0 && <span className="small">This task covers no criteria.</span>}
            {covers.map((ac) => {
              const t = tested.get(ac);
              return (
                <div key={ac} className="flex justify-between gap-2 text-[13px]">
                  <span className="font-mono text-xs break-all">
                    {ac} · {t ? t.test : 'no test yet'}
                  </span>
                  <span className={t?.result === 'GREEN' ? 'text-ok' : t ? 'text-bad font-semibold' : 'text-warn'}>{t ? (t.result === 'GREEN' ? 'pass' : t.result.toLowerCase()) : 'missing'}</span>
                </div>
              );
            })}
            <span className="small">Written by write-tests from the approved criteria, not from the code.</span>
          </Card>

          <Card className="px-[18px] py-4 flex flex-col gap-2" aria-labelledby="pdep-h">
            <h2 id="pdep-h" className="text-[17px]">
              Deploy guard · staging
            </h2>
            {guard.kind === 'loading' && <span className="small">{sha ? 'Checking…' : 'No PR head yet.'}</span>}
            {guard.kind === 'error' && <span className="small text-bad">Could not check: {guard.message}</span>}
            {guard.kind === 'ready' && (
              <>
                <span className={`font-semibold ${guard.data.decision === 'GO' ? 'text-ok' : 'text-bad'}`}>{guard.data.decision}</span>
                {guard.data.reasons.map((x) => (
                  <span key={x} className="small">
                    {x}
                  </span>
                ))}
              </>
            )}
            {deploys.map((d) => (
              <span key={d.ref} className="small">
                {d.ref} · {asText(d.fields.environment)} at {shortSha(asText(d.fields.at_sha))} · {d.status.toLowerCase()}
              </span>
            ))}
          </Card>
        </aside>
      </div>
    </>
  );
}
