import React from 'react';
import { Link } from 'react-router-dom';

type Props = React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string };

/** In-app paths go through the router; absolute URLs open in a new tab. */
export function AppLink({ href, children, ...rest }: Props) {
  if (/^https?:\/\//.test(href)) {
    return (
      <a href={href} target="_blank" rel="noreferrer" {...rest}>
        {children}
      </a>
    );
  }
  return (
    <Link to={href} {...rest}>
      {children}
    </Link>
  );
}

/** Where a ref lives: tasks have the PR review page, the draft its review page, everything
 * else the record page. */
export function refHref(slug: string, ref: string): string {
  if (/^T-\d+$/.test(ref)) return `/i/${slug}/t/${ref}`;
  if (ref === 'draft') return `/i/${slug}/draft`;
  if (ref === 'initiative') return `/i/${slug}`;
  return `/i/${slug}/r/${ref}`;
}

export function RefLink({ slug, r, className = '' }: { slug: string; r: string; className?: string }) {
  return (
    <Link to={refHref(slug, r)} className={`font-mono ${className}`}>
      {r}
    </Link>
  );
}

/** A list of refs, linked, comma separated; a dash when empty. */
export function Refs({ slug, refs, empty = '—' }: { slug: string; refs: string[]; empty?: string }) {
  if (!refs.length) return <span className="text-ink-muted">{empty}</span>;
  return (
    <span className="font-mono">
      {refs.map((r, i) => (
        <span key={r}>
          {i > 0 && ' '}
          <Link to={refHref(slug, r)}>{r}</Link>
        </span>
      ))}
    </span>
  );
}

// Plain text as agents write it: bare refs (D-4, AC-12), URLs and `code`.
const INLINE_RE = /(https?:\/\/[^\s<>")]+[^\s<>").,;:])|(`[^`]+`)|(\*\*[^*]+\*\*)|((?<![\w#-])(?:STD|DEP|APR|AC|[DGTFRBAL])-\d+(?![\w-]))/g;

export function Inline({ text, slug }: { text: string; slug?: string }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE_RE)) {
    const i = m.index ?? 0;
    if (i > last) parts.push(text.slice(last, i));
    const [whole, url, code, bold, ref] = m;
    if (url) {
      parts.push(
        <a key={i} href={url} target="_blank" rel="noreferrer" className="break-all">
          {url}
        </a>,
      );
    } else if (code) {
      parts.push(
        <code key={i} className="inline">
          {code.slice(1, -1)}
        </code>,
      );
    } else if (bold) {
      parts.push(<strong key={i}>{bold.slice(2, -2)}</strong>);
    } else if (ref && slug && !/^(STD|L)-/.test(ref)) {
      parts.push(
        <Link key={i} to={refHref(slug, ref)} className="font-mono">
          {ref}
        </Link>,
      );
    } else {
      parts.push(whole);
    }
    last = i + whole.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}
