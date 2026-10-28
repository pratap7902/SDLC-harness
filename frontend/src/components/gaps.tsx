import { Link } from 'react-router-dom';
import type { InboxItem } from '../api';
import { asText, nm } from '../lib/format';
import { inboxHref } from '../lib/waiting';

/** "Assigned to Arjun · answered by Priya" — both people, as the gap record keeps them. */
export function answeredText(fields: Record<string, unknown>): string {
  const by = nm(asText(fields.answered_by));
  const assigned = asText(fields.assigned_to);
  return assigned ? `Assigned to ${nm(assigned)} · answered by ${by}` : `Answered by ${by}`;
}

/** Any human may answer an open gap: the viewer's own go to their inbox, anyone else's to
 * "All open questions" with the item selected. */
export function AnswerLink({ item, persona, button = false }: { item: InboxItem; persona: string; button?: boolean }) {
  const mine = item.person === persona;
  return (
    <Link to={inboxHref(item.key, !mine)} className={button ? `btn ${mine ? 'btn-primary hover:text-white' : ''} no-underline` : ''}>
      {button ? 'Answer' : 'answer'}
    </Link>
  );
}
