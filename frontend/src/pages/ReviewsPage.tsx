import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { ReviewItem } from '../api';
import { api, errorText, postJson, useJson, useRefresh } from '../lib/api';
import { ago, nm } from '../lib/format';
import { refHref } from '../lib/links';
import { usePersona } from '../lib/persona';
import { useToast } from '../lib/toast';
import { Badge, Banner, Card, Empty } from '../components/ui';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';

const FILTERS = ['open', 'upheld', 'revised', 'dismissed', 'all'];

function Resolve({ slug, item }: { slug: string; item: ReviewItem }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const say = useToast();
  const { bump } = useRefresh();
  const send = async (resolution: string) => {
    setBusy(true);
    setError('');
    try {
      await postJson<ReviewItem>(api('initiatives', slug, 'reviews', item.id, 'resolve'), { resolution, note: note.trim() });
      say(`Review item on ${item.target} ${resolution}.`);
      bump();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-2 mt-2">
      <label className="sr-only" htmlFor={`note-${item.id}`}>
        Note
      </label>
      <input id={`note-${item.id}`} className="input" placeholder="Note (required): why it holds, or what changed" value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <Banner tone="bad">{error}</Banner>}
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-primary" disabled={!note.trim() || busy} onClick={() => send('upheld')}>
          Still holds
        </button>
        <button type="button" className="btn" disabled={!note.trim() || busy} onClick={() => send('revised')}>
          Revised
        </button>
        <button type="button" className="btn btn-link" disabled={!note.trim() || busy} onClick={() => send('dismissed')}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

/** The review queue: records put up for review because something they rest on changed. */
export default function ReviewsPage() {
  const { slug = '' } = useParams();
  const { persona } = usePersona();
  const [status, setStatus] = useState('open');
  const items = useJson<ReviewItem[]>(`${api('initiatives', slug, 'reviews')}?status=${status}`);
  return (
    <>
      <PageHeader crumbs={[{ label: 'Features', href: '/' }, { label: slug, href: `/i/${slug}`, mono: true }, { label: 'Reviews' }]} title="Review queue">
        <p className="m-0 text-ink-muted">A change puts what rests on it up for review. Say it still holds (upheld) or change it (revised).</p>
      </PageHeader>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button key={f} type="button" aria-pressed={status === f} className={`chip ${status === f ? 'chip-on' : ''}`} onClick={() => setStatus(f)}>
            {f}
          </button>
        ))}
      </div>
      {items.kind === 'error' && <LoadError what="the review queue" message={items.message} onRetry={items.reload} />}
      {items.kind === 'loading' && <Loading what="the review queue" />}
      {items.kind === 'ready' && items.data.length === 0 && <Empty boxed>No {status === 'all' ? '' : status} review items.</Empty>}
      {items.kind === 'ready' &&
        items.data.map((x) => (
          <Card key={x.id} className="px-[18px] py-4 flex flex-col gap-1">
            <div className="flex flex-wrap gap-2 items-center">
              <Link to={refHref(slug, x.target)} className="font-mono font-semibold">
                {x.target}
              </Link>
              <span>←</span>
              <Link to={refHref(slug, x.cause)} className="font-mono">
                {x.cause}
              </Link>
              <Badge tone={x.status === 'open' ? 'human' : 'muted'}>{x.status}</Badge>
              <span className="small">
                routed to {x.route_to === persona ? 'you' : nm(x.route_to)} · {ago(x.created_at)}
              </span>
            </div>
            <span className="text-[13px]">{x.what_moved}</span>
            {x.note && <span className="small">“{x.note}” · {nm(x.resolved_by)}</span>}
            {x.status === 'open' && <Resolve slug={slug} item={x} />}
          </Card>
        ))}
    </>
  );
}
