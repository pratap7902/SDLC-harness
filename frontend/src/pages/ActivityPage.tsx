import { useParams } from 'react-router-dom';
import type { ActivityEntry } from '../api';
import { api, useJson } from '../lib/api';
import { dateTime, who } from '../lib/format';
import { RefLink, FeatureName } from '../lib/links';
import { Card, Empty } from '../components/ui';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';

/** Every revision and review item of the initiative, newest first: who, as what, and why. */
export default function ActivityPage() {
  const { id: fid = '' } = useParams();
  const feed = useJson<ActivityEntry[]>(`${api('initiatives', fid, 'activity')}?limit=200`);
  return (
    <>
      <PageHeader crumbs={[{ label: 'Features', href: '/' }, { label: <FeatureName fid={fid} />, href: `/features/${fid}`, mono: true }, { label: 'Activity' }]} title="Activity" />
      {feed.kind === 'error' && <LoadError what="the activity" message={feed.message} onRetry={feed.reload} />}
      {feed.kind === 'loading' && <Loading what="the activity" />}
      {feed.kind === 'ready' && feed.data.length === 0 && <Empty boxed>Nothing has happened yet.</Empty>}
      {feed.kind === 'ready' && feed.data.length > 0 && (
        <Card>
          <ol className="m-0 p-0 list-none">
            {feed.data.map((e, i) => (
              <li key={i} className="flex flex-wrap gap-x-[14px] gap-y-1 px-[18px] py-2.5 items-baseline border-t border-line-soft first:border-t-0 text-[13px]">
                <span className="font-mono small basis-[110px] shrink-0">{dateTime(e.at)}</span>
                <RefLink fid={fid} r={e.ref} className="font-semibold basis-14 shrink-0" />
                <span className="flex-[1_1_300px] min-w-0">
                  {e.action} · {e.title}
                  <span className="small">
                    {' '}
                    · {e.status}
                    {e.because.length > 0 && ` · because ${e.because.join(', ')}`}
                    {e.note && ` · ${e.note}`}
                    {e.assigned_to && ` · assigned to ${e.assigned_to}${e.answered_for ? `, answered for them by ${e.answered_by}` : ''}`}
                  </span>
                </span>
                <span className={`text-xs font-semibold ${e.actor_kind === 'human' ? 'text-human' : e.actor_kind === 'agent' ? 'text-agent' : 'text-ink-muted'}`}>
                  {who(e.actor)}
                  {e.actor_kind ? ` · ${e.actor_kind}` : ''}
                </span>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </>
  );
}
