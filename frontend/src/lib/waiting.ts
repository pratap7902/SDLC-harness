// "Decisions waiting" across every initiative, composed from existing endpoints: the people
// list says who has an inbox, and each of those inboxes lists its items (routed, with SLA,
// what they block). No aggregate endpoint needed.

import type { Inbox, InboxItem, Person } from '../api';
import { api, useJsonAll, type Loaded } from './api';
import { usePersona } from './persona';

export function useAllWaiting(): Loaded<InboxItem[]> {
  const { people, peopleError } = usePersona();
  const urls = people.length ? people.filter((p: Person) => p.inbox > 0).map((p) => api('inbox', p.person)) : null;
  const inboxes = useJsonAll<Inbox>(peopleError ? null : urls);
  if (peopleError) return { kind: 'error', message: peopleError };
  if (!people.length) return { kind: 'loading' };
  if (inboxes.kind !== 'ready') return inboxes;
  return { kind: 'ready', data: inboxes.data.flatMap((i) => i.items) };
}

/** A task's PR approval is not a decision: it has its own line on the features page. */
export function isPrApproval(it: InboxItem): boolean {
  return it.kind === 'approval' && it.target !== 'draft';
}

/** What an item blocks, as a person reads it. */
export function blocksText(it: InboxItem): string {
  switch (it.kind) {
    case 'gap':
    case 'decision':
      return it.blocks.length ? it.blocks.join(', ') : it.kind === 'decision' ? 'the draft approval' : 'nothing named';
    case 'approval':
      return it.target === 'draft' ? 'build start (baseline)' : `${it.target} merge and deploy`;
    case 'review_item':
      return `${it.target} until someone says it still holds`;
    case 'manual_ac':
      return 'GATE_VALIDATED (deploy)';
  }
}

export function isBlocking(it: InboxItem): boolean {
  if (it.kind === 'gap') return it.level !== 'SHOULD' && it.blocks.length > 0;
  if (it.kind === 'decision') return it.level === 'MUST';
  return it.kind === 'approval' || it.kind === 'manual_ac';
}

export const KIND_LABEL: Record<InboxItem['kind'], string> = {
  gap: 'Gap',
  decision: 'Decision',
  approval: 'Approval',
  review_item: 'Review item',
  manual_ac: 'Manual criterion',
};

export function itemLabel(it: InboxItem): string {
  switch (it.kind) {
    case 'gap':
      return `Gap · ${it.record.fields.domain ?? it.route.domain ?? ''}`.replace(/ · $/, '');
    case 'decision':
      return `Decision · ${it.level || ''}`.replace(/ · $/, '');
    case 'approval':
      return it.target === 'draft' ? 'Draft approval' : 'PR approval';
    case 'review_item':
      return 'Review item';
    case 'manual_ac':
      return 'Manual criterion';
  }
}

/** The one-line "what" of an item (cards, rows). */
export function itemTitle(it: InboxItem): string {
  if (it.kind === 'gap' || it.kind === 'decision') return it.question || it.title;
  if (it.kind === 'manual_ac') return it.text || it.title;
  return it.title;
}

/** Sort: yours first, then what blocks work, then overdue, then the inbox's own priority. */
export function sortWaiting(items: InboxItem[], persona: string): InboxItem[] {
  return [...items].sort(
    (a, b) =>
      Number(b.person === persona) - Number(a.person === persona) ||
      Number(isBlocking(b)) - Number(isBlocking(a)) ||
      Number(b.overdue) - Number(a.overdue) ||
      a.priority - b.priority ||
      (a.since || '').localeCompare(b.since || ''),
  );
}

/** Where an item is acted on: drafts and PRs have their review pages; the rest the inbox. */
export function itemHref(it: InboxItem): string {
  if (it.kind === 'approval') return it.target === 'draft' ? `/i/${it.initiative}/draft` : `/i/${it.initiative}/t/${it.target}`;
  return `/inbox/${it.person}?item=${encodeURIComponent(it.key)}`;
}
