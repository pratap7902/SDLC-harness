// The prototype's primitives as plain Tailwind components: badges in six tones (pink =
// needs a human, indigo = agent, green / amber / red, muted grey), cards, banners, fields,
// tabs, the person chip and the unified diff.

import React from 'react';
import { avatarColor, nm, pillTone, type Tone } from '../lib/format';

const BADGE: Record<Tone, string> = {
  ok: 'text-ok bg-ok-bg',
  warn: 'text-warn bg-warn-bg',
  bad: 'text-bad bg-bad-bg',
  human: 'text-human bg-human-bg',
  agent: 'text-agent bg-agent-bg',
  muted: 'text-ink-muted bg-muted-bg',
};

export function Badge({ tone = 'muted', children, big = false, title }: { tone?: Tone; children: React.ReactNode; big?: boolean; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center font-semibold rounded-full whitespace-nowrap ${big ? 'text-xs px-3 py-[3px]' : 'text-[11px] px-[9px] py-px'} ${BADGE[tone]}`}
    >
      {children}
    </span>
  );
}

/** A status pill coloured by the blueprint (every record JSON carries its `pill`). */
export function StatusBadge({ status, pill, suffix }: { status: string; pill?: string | null; suffix?: string }) {
  return (
    <Badge tone={pillTone(pill)}>
      {status}
      {suffix ? ` · ${suffix}` : ''}
    </Badge>
  );
}

const TEXT_TONE: Record<Tone, string> = {
  ok: 'text-ok',
  warn: 'text-warn',
  bad: 'text-bad font-semibold',
  human: 'text-human font-semibold',
  agent: 'text-agent font-semibold',
  muted: 'text-ink-muted',
};

export function toneText(t: Tone): string {
  return TEXT_TONE[t];
}

export function Card({ children, className = '', as = 'section', ...rest }: { children: React.ReactNode; className?: string; as?: 'section' | 'article' | 'div' | 'aside' } & React.HTMLAttributes<HTMLElement>) {
  const Tag = as;
  return (
    <Tag className={`card ${className}`} {...rest}>
      {children}
    </Tag>
  );
}

export function CardHead({ title, aside, id }: { title: React.ReactNode; aside?: React.ReactNode; id?: string }) {
  return (
    <div className="cardhead">
      <h2 id={id} className="text-[17px]">
        {title}
      </h2>
      {aside && <span className="small">{aside}</span>}
    </div>
  );
}

const BANNER: Record<string, string> = {
  ok: 'bg-ok-bg text-ok',
  warn: 'bg-warn-bg text-warn',
  human: 'bg-human-bg text-human',
  bad: 'bg-bad-bg text-bad',
  agent: 'bg-agent-bg text-agent',
  muted: 'bg-muted-bg text-ink-muted',
};

export function Banner({ tone, children, role }: { tone: Tone; children: React.ReactNode; role?: string }) {
  return (
    <div role={role} className={`rounded-item px-[14px] py-3 text-[13px] font-semibold ${BANNER[tone]}`}>
      {children}
    </div>
  );
}

export function Empty({ children, boxed = false }: { children: React.ReactNode; boxed?: boolean }) {
  return <div className={`p-[22px] text-center text-ink-muted text-[13px] ${boxed ? 'card' : ''}`}>{children}</div>;
}

export function Field({ label, htmlFor, hint, required, optional, children }: { label: React.ReactNode; htmlFor?: string; hint?: React.ReactNode; required?: boolean; optional?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="font-semibold text-[13px]">
        {label} {required && <span className="text-bad font-normal">required</span>}
        {optional && <span className="small font-normal">({optional})</span>}
      </label>
      {children}
      {hint && <span className="small">{hint}</span>}
    </div>
  );
}

export function Kv({ k, v, vClass = '' }: { k: React.ReactNode; v: React.ReactNode; vClass?: string }) {
  return (
    <div className="flex justify-between gap-2 text-[13px]">
      <span>{k}</span>
      <span className={`font-semibold text-right ${vClass}`}>{v}</span>
    </div>
  );
}

export function Avatar({ handle }: { handle: string }) {
  return (
    <span
      aria-hidden="true"
      className="w-6 h-6 rounded-full inline-grid place-items-center text-white text-[11px] font-bold shrink-0"
      style={{ background: avatarColor(handle) }}
    >
      {nm(handle).charAt(0)}
    </span>
  );
}

export function PersonChip({ handle, role }: { handle: string; role?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px]">
      <Avatar handle={handle} />
      <span>
        <strong>{nm(handle)}</strong> {role && <span className="small">{role}</span>}
      </span>
    </span>
  );
}

export function Tabs<K extends string>({ tabs, value, onChange, label }: { tabs: [K, string][]; value: K; onChange: (k: K) => void; label: string }) {
  return (
    <div className="flex gap-1 border-b border-line overflow-x-auto" role="tablist" aria-label={label}>
      {tabs.map(([k, text]) => {
        const on = k === value;
        return (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(k)}
            className={[
              'border-0 bg-transparent px-3 py-[9px] cursor-pointer -mb-px text-sm whitespace-nowrap border-b-2',
              on ? 'text-ink font-semibold border-ink' : 'text-ink-muted border-transparent',
            ].join(' ')}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}

/** A unified diff, line by line: removed red, added green, headers muted. */
export function Diff({ text }: { text: string }) {
  return (
    <div className="overflow-x-auto border border-line rounded-item">
      <pre className="m-0 px-[14px] py-3 font-mono text-xs leading-[1.6] min-w-[520px]">
        {text.split('\n').map((line, i) => {
          const cls =
            line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')
              ? 'text-ink-muted'
              : line.startsWith('+')
                ? 'text-ok bg-ok-bg'
                : line.startsWith('-')
                  ? 'text-bad bg-bad-bg'
                  : '';
          return (
            <span key={i} className={`block ${cls}`}>
              {line || ' '}
            </span>
          );
        })}
      </pre>
    </div>
  );
}

/** ✓ / • checklist line. */
export function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex gap-2">
      <span aria-hidden="true" className={`font-bold ${ok ? 'text-ok' : 'text-bad'}`}>
        {ok ? '✓' : '•'}
      </span>
      <span>
        <span className="sr-only">{ok ? 'Done: ' : 'Not done: '}</span>
        {children}
      </span>
    </li>
  );
}

export function Section({ title, aside, children, id }: { title: React.ReactNode; aside?: React.ReactNode; children: React.ReactNode; id: string }) {
  return (
    <section className="flex flex-col gap-3" aria-labelledby={id}>
      <div className="flex flex-wrap gap-3 items-center justify-between">
        <h2 id={id}>{title}</h2>
        {aside && <span className="small">{aside}</span>}
      </div>
      {children}
    </section>
  );
}
