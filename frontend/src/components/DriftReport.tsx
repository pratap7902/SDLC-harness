import type { DriftReport as Report, Spec } from '../api';
import { nm, plural, shortDate, who } from '../lib/format';
import { Inline, Refs, refHref } from '../lib/links';
import { Link } from 'react-router-dom';
import { Badge, Card, Diff } from './ui';

function isSpec(s: Spec | Record<string, never>): s is Spec {
  return Array.isArray((s as Spec).decisions);
}

/** "What changed since the spec was approved": the timeline of drift entries, each with who
 * made it (human or agent) and the reason it cites. */
export function DriftTimeline({ report, slug }: { report: Report; slug: string }) {
  const r = report;
  const n = r.summary.changes;
  const intro =
    r.status === 'NO_BASELINE'
      ? 'The draft is not approved yet, so there is nothing to compare against.'
      : n === 0
        ? `No spec changes ${r.task ? `touch ${r.task}` : 'at all'} since approval. Review the code as usual.`
        : r.summary.unexplained
          ? `${plural(r.summary.unexplained, 'change')} below ${r.summary.unexplained === 1 ? 'has' : 'have'} no human reason. The gate stays blocked until someone explains or reverts ${r.summary.unexplained === 1 ? 'it' : 'them'}.`
          : 'Every change below has a human reason. Review these, not the whole feature. Everything else matches the approved spec.';
  return (
    <Card className="px-[18px] py-4 flex flex-col gap-3" aria-labelledby="pd-h">
      <div className="flex flex-wrap gap-3 items-center justify-between">
        <h2 id="pd-h" className="text-[17px]">
          What changed since the spec was approved
        </h2>
        {r.baseline && (
          <span className="small">
            baseline {r.baseline.ref} · {nm(r.baseline.approved_by)} · {shortDate(r.baseline.created_at)}
          </span>
        )}
      </div>
      <p className="m-0 text-ink-muted text-[13px]">{intro}</p>
      {r.entries.length > 0 && (
        <ol className="m-0 p-0 list-none">
          {r.entries.map((e) => {
            const human = e.actor_kind === 'human';
            return (
              <li key={e.id} className="flex flex-wrap gap-x-[14px] gap-y-1.5 py-3 items-baseline border-t border-line-soft first:border-t-0">
                <span className="font-mono small basis-[70px] shrink-0">{shortDate(e.at)}</span>
                <span className="flex-[1_1_300px] min-w-0">
                  <Inline text={e.summary} slug={slug} />{' '}
                  {e.because.length > 0 && (
                    <span className={e.explained ? 'text-ok font-semibold' : 'text-bad font-semibold'}>
                      · because <Refs slug={slug} refs={e.because} />
                    </span>
                  )}
                  {!e.explained && (
                    <span className="block mt-1">
                      <Badge tone="bad">UNEXPLAINED</Badge>{' '}
                      <span className="text-bad text-[13px]">{e.explanation.filter((x) => !x.ok).map((x) => (x.ref ? `${x.ref}: ${x.why}` : x.why)).join(' · ')}</span>
                    </span>
                  )}
                  {e.explained && e.explanation.length > 0 && e.because.length > 0 && (
                    <span className="small block">
                      {e.explanation.map((x) => (x.ref ? `${x.ref} ${x.why}` : x.why)).join(' · ')}
                    </span>
                  )}
                </span>
                <span className={`text-xs ${human ? 'text-human font-semibold' : 'text-agent font-semibold'}`}>
                  {who(e.actor)}
                  {human ? ' · human' : ` · ${e.actor_kind}`}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {(r.pending_gaps.length > 0 || r.pending_decisions.length > 0) && (
        <p className="m-0 text-[13px] text-human font-semibold">
          Still open since the baseline (not drift yet): <Refs slug={slug} refs={[...r.pending_gaps, ...r.pending_decisions].map((x) => x.ref)} />
        </p>
      )}
      {r.summary.other_changes > 0 && <p className="m-0 small">{plural(r.summary.other_changes, 'other change')} in this feature fall outside {r.task || 'this scope'}.</p>}
    </Card>
  );
}

/** Approved vs now, side by side, then the unified diff of every draft section that moved. */
export function SpecCompare({ report, slug }: { report: Report; slug: string }) {
  const a = report.approved_spec;
  const c = report.current_spec;
  if (!isSpec(a) || !isSpec(c)) return null;
  const diff = 'draft' in report.spec_diff ? report.spec_diff : null;
  const nowRefs = new Set([...c.decisions.map((x) => x.ref), ...c.criteria.map((x) => x.ref)]);
  const thenRefs = new Set([...a.decisions.map((x) => x.ref), ...a.criteria.map((x) => x.ref)]);
  const changedAc = new Map((diff?.criteria.changed || []).map((x) => [x.ref, x]));
  const changedDec = new Map((diff?.decisions.changed || []).map((x) => [x.ref, x]));
  const gone = (ref: string, status?: string) => !nowRefs.has(ref) || ['SUPERSEDED', 'RETIRED'].includes(status || '');
  const currentStatus = new Map([...c.decisions, ...c.criteria].map((x) => [x.ref, x.status]));
  const sections = diff ? Object.entries(diff.draft) : [];
  if (report.summary.changes === 0 && sections.length === 0) return null;
  const row = (ref: string, text: string, cls: string, note?: string) => (
    <span key={ref}>
      <Link to={refHref(slug, ref)} className={`font-mono font-semibold ${cls}`}>
        {ref}
      </Link>{' '}
      <span className={cls.includes('line-through') ? 'text-ink-muted' : ''}>
        <Inline text={text} slug={slug} />
      </span>
      {note && <span className="small"> · {note}</span>}
    </span>
  );
  return (
    <Card className="px-[18px] py-4 flex flex-col gap-3" aria-labelledby="cmp-h">
      <h2 id="cmp-h" className="text-[17px]">
        Approved vs now
      </h2>
      <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
        <div className="flex flex-col gap-1.5 border border-line rounded-item px-[14px] py-3 bg-[#FAFAFB]">
          <span className="eyebrow">Approved in {report.baseline?.ref}</span>
          {a.decisions.map((d) => row(d.ref, d.verdict, gone(d.ref, currentStatus.get(d.ref)) || changedDec.has(d.ref) ? 'line-through text-ink-muted' : 'text-ink'))}
          {a.criteria.map((x) => row(x.ref, x.text, gone(x.ref, currentStatus.get(x.ref)) || changedAc.has(x.ref) ? 'line-through text-ink-muted' : 'text-ink'))}
        </div>
        <div className="flex flex-col gap-1.5 border border-ok rounded-item px-[14px] py-3">
          <span className="eyebrow !text-ok">Now</span>
          {c.decisions
            .filter((d) => d.status !== 'SUPERSEDED')
            .map((d) => row(d.ref, d.verdict, 'text-ink', !thenRefs.has(d.ref) ? 'new' : changedDec.has(d.ref) ? 'changed' : undefined))}
          {c.criteria
            .filter((x) => x.status !== 'RETIRED')
            .map((x) => row(x.ref, x.text, 'text-ink', !thenRefs.has(x.ref) ? 'new' : changedAc.has(x.ref) ? 'changed' : undefined))}
        </div>
      </div>
      {sections.map(([section, d]) => (
        <div key={section} className="flex flex-col gap-1.5">
          <span className="small">
            draft.{section} · <span className="text-bad">−{d.removed}</span> <span className="text-ok">+{d.added}</span>
          </span>
          <Diff text={d.diff} />
        </div>
      ))}
      {diff?.criteria.changed.map((x) => (
        <div key={x.ref} className="flex flex-col gap-1.5">
          <span className="small">{x.ref} text</span>
          <Diff text={`- ${x.old}\n+ ${x.new}`} />
        </div>
      ))}
      {diff?.criteria.retired.map((x) => (
        <p key={x.ref} className="m-0 text-[13px]">
          <span className="font-mono font-semibold line-through">{x.ref}</span> retired: {x.retired_because}
        </p>
      ))}
    </Card>
  );
}
