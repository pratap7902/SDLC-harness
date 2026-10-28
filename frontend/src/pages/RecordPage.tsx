import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { RecordJson, Revision, WriteResult } from '../api';
import { all, api, errorText, postJson, useJson, useRefresh } from '../lib/api';
import { dateTime, nm, who } from '../lib/format';
import { Inline, refHref } from '../lib/links';
import { useToast } from '../lib/toast';
import { Badge, Banner, Card, CardHead, Field, StatusBadge } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';

function Value({ v, slug }: { v: unknown; slug: string }) {
  if (v === null || v === undefined || v === '') return <span className="text-ink-muted">—</span>;
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x !== 'object' || x === null)) {
      return (
        <span className="flex flex-wrap gap-x-2">
          {v.map((x, i) => (
            <span key={i}>
              <Inline text={String(x)} slug={slug} />
            </span>
          ))}
        </span>
      );
    }
    const cols = Array.from(new Set(v.flatMap((row) => Object.keys(row as object))));
    return (
      <div className="tbl border border-line rounded-ctl">
        <table>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {v.map((row, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>
                    <Inline text={String((row as Record<string, unknown>)[c] ?? '')} slug={slug} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (typeof v === 'object') return <pre className="m-0 text-xs font-mono whitespace-pre-wrap">{JSON.stringify(v, null, 2)}</pre>;
  const s = String(v);
  return s.includes('\n') ? <Markdown text={s} slug={slug} /> : <Inline text={s} slug={slug} />;
}

function RetireForm({ slug, r }: { slug: string; r: RecordJson }) {
  const [because, setBecause] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const say = useToast();
  const { bump } = useRefresh();
  const send = async () => {
    setBusy(true);
    setError('');
    try {
      await postJson<WriteResult>(api('initiatives', slug, 'criteria', r.ref, 'retire'), { because: because.trim() });
      say(`${r.ref} retired. It shows as ac_retired in the drift report, with your reason.`);
      setBecause('');
      bump();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="px-[18px] py-4 flex flex-col gap-2.5">
      <h2 className="text-[17px]">Retire this criterion</h2>
      <p className="m-0 small text-[13px]">Only a person can retire a criterion. It stays in the history and in the drift report.</p>
      <Field label="Because" htmlFor="because" required>
        <input id="because" className="input" value={because} onChange={(e) => setBecause(e.target.value)} />
      </Field>
      {error && <Banner tone="bad" role="alert">{error}</Banner>}
      <div>
        <button type="button" className="btn" disabled={!because.trim() || busy} onClick={send}>
          Retire {r.ref}
        </button>
      </div>
    </Card>
  );
}

export default function RecordPage() {
  const { slug = '', ref = '' } = useParams();
  const record = useJson<RecordJson>(api('initiatives', slug, 'records', ref));
  const history = useJson<Revision[]>(api('initiatives', slug, 'records', ref, 'history'));
  const loaded = all(record, history);
  if (loaded.kind === 'error') return <LoadError what={ref} message={loaded.message} onRetry={record.reload} />;
  if (loaded.kind === 'loading') return <Loading what={ref} />;
  const [r, revs] = loaded.data;
  const links = [...(r.links?.out || []).map((l) => ({ dir: '→', kind: l.kind, ref: l.to || '' })), ...(r.links?.in || []).map((l) => ({ dir: '←', kind: l.kind, ref: l.from || '' }))];
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Features', href: '/' }, { label: slug, href: `/i/${slug}`, mono: true }, { label: ref, mono: true }]}
        title={
          <>
            <span className="font-mono">{r.ref}</span> {r.title}
          </>
        }
        badge={<StatusBadge status={r.status} pill={r.pill} />}
      >
        <p className="m-0 small">
          {r.type.replace(/_/g, ' ')} · rev {r.rev} · created by {who(r.created_by)} {dateTime(r.created_at)} · last change by {who(r.updated_by)} {dateTime(r.updated_at)}
          {/^T-\d+$/.test(r.ref) && (
            <>
              {' · '}
              <Link to={`/i/${slug}/t/${r.ref}`}>PR review</Link>
            </>
          )}
        </p>
      </PageHeader>
      {(r.stale || []).length > 0 && <Banner tone="warn">Stale narrative: {(r.stale || []).join(', ')} should be rewritten.</Banner>}
      <div className="flex flex-wrap gap-[22px] items-start">
        <div className="flex-[999_1_560px] min-w-0 flex flex-col gap-[22px]">
          <Card>
            <CardHead title="Fields" />
            <dl className="m-0 px-[18px] py-2">
              {Object.entries(r.fields).map(([k, v]) => {
                const st = r.stamps?.[k];
                return (
                  <div key={k} className="grid gap-x-4 gap-y-1 py-2.5 border-t border-line-soft first:border-t-0 [grid-template-columns:minmax(120px,180px)_1fr]">
                    <dt className="font-semibold text-[13px]">
                      {k.replace(/_/g, ' ')}
                      {st && (
                        <span className={`block text-[11px] font-normal ${st.kind === 'human' ? 'text-human' : 'text-agent'}`}>
                          {who(st.by)} · {st.kind}
                        </span>
                      )}
                    </dt>
                    <dd className="m-0 min-w-0 text-[13px]">
                      <Value v={v} slug={slug} />
                    </dd>
                  </div>
                );
              })}
            </dl>
          </Card>
          {r.type === 'acceptance_criterion' && r.status !== 'RETIRED' && <RetireForm slug={slug} r={r} />}
        </div>
        <aside className="flex-[1_1_300px] min-w-0 flex flex-col gap-[22px]">
          <Card className="px-[18px] py-4 flex flex-col gap-1.5">
            <h2 className="text-[17px]">Links</h2>
            {links.length === 0 && <span className="small">No links.</span>}
            {links.map((l, i) => (
              <span key={i} className="text-[13px]">
                <span className="small">
                  {l.dir} {l.kind}
                </span>{' '}
                <Link to={refHref(slug, l.ref)} className="font-mono">
                  {l.ref}
                </Link>
              </span>
            ))}
          </Card>
          {(r.review_items || []).length > 0 && (
            <Card className="px-[18px] py-4 flex flex-col gap-1.5">
              <h2 className="text-[17px]">Up for review</h2>
              {(r.review_items || []).map((x) => (
                <span key={x.id} className="text-[13px]">
                  ← {x.cause}: {x.what_moved} · {nm(x.route_to)} · <Link to={`/i/${slug}/reviews`}>resolve</Link>
                </span>
              ))}
            </Card>
          )}
          <Card className="px-[18px] py-4 flex flex-col gap-1.5">
            <h2 className="text-[17px]">History</h2>
            {revs.map((h) => (
              <span key={h.rev} className="small">
                <span className="font-mono">rev {h.rev}</span> · {dateTime(h.at)} · <span className={h.actor_kind === 'human' ? 'text-human font-semibold' : 'text-agent font-semibold'}>{who(h.actor)}</span> · {h.status}
                {h.because.length > 0 && ` · because ${h.because.join(', ')}`}
                {h.note && ` · ${h.note}`}
              </span>
            ))}
            <Badge tone="muted">{revs.length} revisions</Badge>
          </Card>
        </aside>
      </div>
    </>
  );
}
