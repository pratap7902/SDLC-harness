import { useState } from 'react';
import type { RecordJson, WriteResult } from '../api';
import { api, errorText, postJson, useJson, useRefresh } from '../lib/api';
import { asText, who } from '../lib/format';
import { Inline } from '../lib/links';
import { useToast } from '../lib/toast';
import { Card, Empty, StatusBadge } from '../components/ui';
import { PageHeader } from '../components/PageHeader';
import { LoadError, Loading } from '../components/state';

function Promote({ r }: { r: RecordJson }) {
  const [busy, setBusy] = useState(false);
  const say = useToast();
  const { bump } = useRefresh();
  const send = async () => {
    setBusy(true);
    try {
      await postJson<WriteResult>(api('learnings', r.ref, 'promote'), {});
      say(`${r.ref} promoted.`);
      bump();
    } catch (e) {
      say(errorText(e), 'error');
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" className="btn" disabled={busy} onClick={send}>
      Promote
    </button>
  );
}

/** Global scope: the standards decisions cite, and the learnings retros write. */
export default function GlobalPage({ kind }: { kind: 'standards' | 'learnings' }) {
  const list = useJson<RecordJson[]>(`/api/${kind}`);
  const title = kind === 'standards' ? 'Standards' : 'Learnings';
  return (
    <>
      <PageHeader title={title}>
        <p className="m-0 text-ink-muted">
          {kind === 'standards' ? 'Rules every feature is held to. Decisions cite them; MUST standards need a DRI exception to break.' : 'What earlier features taught. Promotion is a human call.'}
        </p>
      </PageHeader>
      {list.kind === 'error' && <LoadError what={kind} message={list.message} onRetry={list.reload} />}
      {list.kind === 'loading' && <Loading what={kind} />}
      {list.kind === 'ready' && list.data.length === 0 && <Empty boxed>No {kind} yet.</Empty>}
      {list.kind === 'ready' && list.data.length > 0 && (
        <Card className="tbl">
          <table className="min-w-[720px]">
            <thead>
              <tr>
                <th scope="col">Ref</th>
                <th scope="col">{kind === 'standards' ? 'Rule' : 'Learning'}</th>
                <th scope="col">{kind === 'standards' ? 'Level · owner' : 'Source'}</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((r) => (
                <tr key={r.ref}>
                  <td className="font-mono font-semibold">{r.ref}</td>
                  <td>
                    <Inline text={r.line || r.title} />
                    {asText(r.fields.applies_to) && <div className="small font-mono">{asText(r.fields.applies_to)}</div>}
                  </td>
                  <td className="small">{kind === 'standards' ? `${asText(r.fields.level)} · ${who(asText(r.fields.owner))}` : asText(r.fields.source)}</td>
                  <td>
                    <div className="flex flex-wrap gap-2 items-center">
                      <StatusBadge status={r.status} pill={r.pill} />
                      {kind === 'learnings' && r.status !== 'PROMOTED' && <Promote r={r} />}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
