// Display helpers: names, phases, times, refs.

/** Handles are lowercase (`chandra`); people read names. */
export function nm(handle: string | null | undefined): string {
  if (!handle) return '—';
  const base = handle.split('/')[0];
  return base.charAt(0).toUpperCase() + base.slice(1);
}

/** `runner-sdk/implement-task` → `implement-task` (the agent), a person stays a person. */
export function who(actor: string): string {
  const parts = actor.split('/');
  return parts.length > 1 ? parts[parts.length - 1] : nm(actor);
}

const AVATAR = ['#3B38B8', '#A3134B', '#0B7F74', '#8A4F00', '#4A5568', '#1E6B35', '#6B3FA0', '#B42318'];

export function avatarColor(handle: string): string {
  let h = 0;
  for (const c of handle) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AVATAR[h % AVATAR.length];
}

export const ROLE_LABEL: Record<string, string> = { dri: 'DRI', engg: 'Engineering', product: 'Product', design: 'Design', qa: 'QA' };
export const ROLE_SHORT: Record<string, string> = { dri: 'DRI', engg: 'Engg', product: 'Product', design: 'Design', qa: 'QA' };

/** The phases the list filters on, in pipeline order (initiative status vocabulary). */
export const PHASES = ['DRAFT', 'PLAN', 'BUILD', 'VALIDATE', 'SHIP'];

export function phaseLabel(phase: string): string {
  const p = phase.toLowerCase();
  return p === 'ship' ? 'Shipped' : p.charAt(0).toUpperCase() + p.slice(1);
}

export function phaseTone(phase: string): Tone {
  switch (phase) {
    case 'DRAFT':
      return 'warn';
    case 'PLAN':
    case 'BUILD':
      return 'agent';
    case 'VALIDATE':
      return 'ok';
    case 'UNASSIGNED':
      return 'bad';
    default:
      return 'muted';
  }
}

export type Tone = 'ok' | 'warn' | 'bad' | 'human' | 'agent' | 'muted';

/** The blueprint's pill colours → the prototype's tones. */
export function pillTone(pill: string | null | undefined): Tone {
  switch (pill) {
    case 'green':
      return 'ok';
    case 'amber':
      return 'warn';
    case 'red':
      return 'bad';
    default:
      return 'muted';
  }
}

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/** "12 min ago", "3 h ago", "yesterday", "2 d ago", then a date. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = now - t;
  if (d < MIN) return 'just now';
  if (d < HOUR) return `${Math.round(d / MIN)} min ago`;
  if (d < DAY) return `${Math.round(d / HOUR)} h ago`;
  if (d < 2 * DAY) return 'yesterday';
  if (d < 7 * DAY) return `${Math.floor(d / DAY)} d ago`;
  return shortDate(iso);
}

/** "due in 22 h", "due in 2 d", "overdue 1 d". */
export function due(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const d = t - now;
  const span = (ms: number) => (ms < HOUR ? `${Math.max(1, Math.round(ms / MIN))} min` : ms < DAY ? `${Math.round(ms / HOUR)} h` : `${Math.round(ms / DAY)} d`);
  return d >= 0 ? `due in ${span(d)}` : `overdue ${span(-d)}`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

/** `https://dev.azure.com/…/_workitems/edit/4211` → `AB#4211`. */
export function workItem(url: string | null | undefined): string {
  if (!url) return 'no work item';
  const m = url.match(/(\d+)\/?\s*$/);
  return m ? `AB#${m[1]}` : 'linked';
}

/** `https://github.com/acme/x/pull/482` → `#482`. */
export function prNumber(url: string | null | undefined): string {
  if (!url) return '';
  const m = url.match(/\/pull\/(\d+)/);
  return m ? `#${m[1]}` : 'PR';
}

export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : '—';
}

export function plural(n: number, one: string, many = one + 's'): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function asList(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  if (v === null || v === undefined || v === '') return [];
  return [String(v)];
}

export function asText(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (Array.isArray(v)) return v.map(String).join('\n');
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/** Gate rule names → what a person reads in a checklist. */
export const RULE_TEXT: Record<string, [string, string]> = {
  no_open_decision_in_draft_scope: ['No open decisions', 'decisions still open'],
  no_open_gap_blocking_draft: ['No open questions blocking the draft', 'open questions block the draft'],
  no_open_review_items_on_spec: ['No open review items on the spec', 'review items open on the spec'],
  catalog_addressed: ['Catalog addressed', 'catalog items not addressed'],
  every_ac_has_source: ['Every criterion cites its source', 'criteria without a source'],
  every_decision_covered_by_an_ac: ['Every decision covered by a criterion', 'decisions no criterion comes from'],
  approval_by_role: ['Approved', 'not approved yet'],
  pr_state_in: ['PR is open', 'PR is not open for review'],
  no_blocker_finding_open_at_sha: ['No blocker finding open at the head', 'blocker findings open at the head'],
  every_covered_ac_has_a_test: ['Every covered criterion has a test', 'covered criteria without a test'],
  drift_explained_for_task: ['All drift explained', 'unexplained drift'],
  no_provisional_decision_implemented_at_must_level: ['No provisional MUST decision implemented', 'provisional MUST decisions implemented'],
  every_ac_green: ['Every live criterion green', 'criteria not green'],
  manual_acs_signed_by: ['Manual criteria signed by QA', 'manual criteria not signed'],
  no_blocker_finding_open: ['No blocker finding open', 'blocker findings open'],
};

export function ruleText(name: string, passed: boolean): string {
  const t = RULE_TEXT[name];
  if (!t) return name.replace(/_/g, ' ');
  return passed ? t[0] : t[1];
}
