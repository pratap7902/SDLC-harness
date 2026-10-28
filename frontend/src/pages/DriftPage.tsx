import { FeatureName } from '../lib/links';
import { useParams, useSearchParams } from 'react-router-dom';
import type { DriftReport } from '../api';
import { api, useJson } from '../lib/api';
import { nm, shortSha } from '../lib/format';
import { Badge, Card } from '../components/ui';
import { DriftTimeline, SpecCompare } from '../components/DriftReport';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';

const TONE = { NO_BASELINE: 'muted', CLEAN: 'ok', EXPLAINED: 'ok', UNEXPLAINED: 'bad' } as const;

/** The initiative-scope drift report (every task's view is on its PR review page). */
export default function DriftPage() {
  const { id: fid = '' } = useParams();
  const [params] = useSearchParams();
  const baseline = params.get('baseline');
  const url = api('initiatives', fid, 'drift') + (baseline ? `?${new URLSearchParams({ baseline })}` : '');
  const report = useJson<DriftReport>(url);
  if (report.kind === 'error') return <LoadError what="the drift report" message={report.message} onRetry={report.reload} />;
  if (report.kind === 'loading') return <Loading what="the drift report" />;
  const r = report.data;
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Features', href: '/' }, { label: <FeatureName fid={fid} />, href: `/features/${fid}`, mono: true }, { label: 'Drift' }]}
        title="Drift since approval"
        badge={
          <Badge tone={TONE[r.status as keyof typeof TONE] || 'muted'} big>
            {r.status}
          </Badge>
        }
      >
        <p className="m-0 text-ink-muted">
          Given the approved baseline, what is different in the spec now, and which human decision authorised each difference. Each task's PR review shows the slice that touches it.
        </p>
      </PageHeader>
      <DriftTimeline report={r} fid={fid} />
      <SpecCompare report={r} fid={fid} />
      <Card className="px-[18px] py-4 flex flex-col gap-1.5 text-[13px]">
        <span>
          Digest <span className="font-mono">{r.digest.slice(0, 16)}</span> · <a href={`${url}${url.includes('?') ? '&' : '?'}format=md`}>as the PR comment (markdown)</a>
        </span>
        {r.approvals.map((a) => (
          <span key={a.ref} className="small">
            {a.ref} · {nm(a.by)} at {shortSha(a.at_sha)} · {a.status.toLowerCase()}
            {a.matches_digest ? '' : ' (drift moved since)'}
          </span>
        ))}
      </Card>
    </>
  );
}
