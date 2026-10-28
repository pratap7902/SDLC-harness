import React from 'react';
import { Inline, type Fid } from '../lib/links';

/** The markdown agents write (draft sections, contexts, requirements): fenced code,
 * headings, lists and paragraphs, with refs, `code` and URLs inline. Rendered as React
 * elements — no HTML from the record ever reaches the DOM. */
export function Markdown({ text, fid, className = '' }: { text: string; fid?: Fid; className?: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
      i++;
      blocks.push(<pre key={key++}>{body.join('\n')}</pre>);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ''));
      blocks.push(
        <blockquote key={key++} className="m-0 mb-2 px-3 py-2 bg-page rounded-md text-[13px] text-ink-soft">
          <Inline text={quote.join(' ')} fid={fid} />
        </blockquote>,
      );
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      blocks.push(
        <h3 key={key++}>
          <Inline text={h[2]} fid={fid} />
        </h3>,
      );
      i++;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && (ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*]\s+/).test(lines[i])) {
        items.push(lines[i].replace(ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*]\s+/, ''));
        i++;
      }
      const Tag = ordered ? 'ol' : 'ul';
      blocks.push(
        <Tag key={key++}>
          {items.map((it, j) => (
            <li key={j}>
              <Inline text={it} fid={fid} />
            </li>
          ))}
        </Tag>,
      );
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i]) && !/^>/.test(lines[i]) && !/^#{1,4}\s/.test(lines[i]) && !/^\s*([-*]|\d+[.)])\s+/.test(lines[i])) {
      para.push(lines[i++]);
    }
    blocks.push(
      <p key={key++}>
        <Inline text={para.join(' ')} fid={fid} />
      </p>,
    );
  }
  return <div className={`md max-w-[76ch] ${className}`}>{blocks}</div>;
}
