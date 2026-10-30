import React, { Suspense, useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import type { Inbox } from '../api';
import { useJson } from '../lib/api';
import { ROLE_LABEL, nm } from '../lib/format';
import { usePersona } from '../lib/persona';
import { useToast } from '../lib/toast';
import { Loading } from '../components/state';

const ICON = {
  features: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  ),
  inbox: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z" />
    </svg>
  ),
  new: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
};

function NavItem({ to, on, icon, children, count }: { to: string; on: boolean; icon?: React.ReactNode; children: React.ReactNode; count?: number }) {
  return (
    <Link
      to={to}
      aria-current={on ? 'page' : undefined}
      className={[
        'flex items-center gap-2.5 w-full rounded-[7px] px-2.5 py-[9px] min-h-[40px] text-sm no-underline',
        on ? 'bg-side-on text-white font-semibold hover:text-white' : 'text-side-text hover:bg-side-hover hover:text-white',
      ].join(' ')}
    >
      {icon}
      {children}
      {count ? (
        <span className="ml-auto bg-human-strong text-white rounded-full px-2 text-xs font-semibold" aria-label={`${count} waiting`}>
          {count}
        </span>
      ) : null}
    </Link>
  );
}

function section(pathname: string): string {
  if (pathname.startsWith('/inbox')) return 'inbox';
  if (pathname === '/new') return 'new';
  if (pathname === '/standards') return 'standards';
  if (pathname === '/learnings') return 'learnings';
  if (pathname === '/blueprint') return 'blueprint';
  return 'features';
}

/** The app shell: the dark sidebar (navigation, inbox count, "Viewing as") beside the page. */
export function Shell() {
  const { persona, setPersona, people, peopleError } = usePersona();
  const location = useLocation();
  const say = useToast();
  const inbox = useJson<Inbox>(persona ? '/api/inbox' : null);
  const count = inbox.kind === 'ready' ? inbox.data.count : 0;
  const on = section(location.pathname);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  const roles = (p: string) => {
    const rs = Array.from(new Set(people.find((x) => x.person === p)?.roles.map((r) => ROLE_LABEL[r.role] || r.role) || []));
    return rs.length ? rs.join(', ') : 'no role';
  };

  return (
    <div className="flex flex-wrap min-h-screen bg-page">
      <nav aria-label="Main" className="flex-[1_1_230px] bg-side text-[#E8EAF0] px-[14px] py-[22px] flex flex-col gap-1">
        <Link to="/" className="flex items-center gap-2.5 font-bold text-base px-2.5 pb-[18px] tracking-[-.01em] text-[#E8EAF0] no-underline hover:text-white">
          <span aria-hidden="true" className="w-[26px] h-[26px] rounded-[7px] bg-agent grid place-items-center text-white font-mono font-bold text-xs">
            H
          </span>
          Harness
        </Link>
        <NavItem to="/" on={on === 'features'} icon={ICON.features}>
          Features
        </NavItem>
        <NavItem to="/inbox" on={on === 'inbox'} icon={ICON.inbox} count={count}>
          Inbox
        </NavItem>
        <NavItem to="/new" on={on === 'new'} icon={ICON.new}>
          Start feature
        </NavItem>
        <div className="mt-3 pt-3 border-t border-side-on flex flex-col gap-0.5">
          <span className="px-2.5 pb-1 text-[11px] tracking-[.06em] uppercase text-side-muted font-semibold">Reference</span>
          <NavItem to="/standards" on={on === 'standards'}>
            Standards
          </NavItem>
          <NavItem to="/learnings" on={on === 'learnings'}>
            Learnings
          </NavItem>
          <NavItem to="/blueprint" on={on === 'blueprint'}>
            Blueprint
          </NavItem>
        </div>
        <div className="mt-auto flex flex-col gap-1.5 pt-[14px] px-2.5 pb-1 border-t border-side-on">
          <label htmlFor="persona" className="text-[11px] tracking-[.06em] uppercase text-side-muted font-semibold">
            Viewing as
          </label>
          <select
            id="persona"
            value={persona}
            onChange={(e) => {
              setPersona(e.target.value);
              say(`Viewing as ${nm(e.target.value)}. Answers and approvals are recorded as ${nm(e.target.value)}.`);
            }}
            className="bg-side-hover border border-side-border text-white rounded-[7px] min-h-[40px] px-2"
          >
            {!people.length && <option value={persona}>{persona ? nm(persona) : 'Loading…'}</option>}
            {people.map((p) => (
              <option key={p.person} value={p.person}>
                {p.name && p.name !== p.person ? p.name : nm(p.person)} · {roles(p.person)}
              </option>
            ))}
          </select>
          {peopleError ? (
            <span className="text-xs text-[#F4A3A3]">Could not load people: {peopleError}</span>
          ) : (
            <span className="text-xs text-side-muted">Dev sign-in: sent as X-Actor on every request.</span>
          )}
        </div>
      </nav>
      <main className="flex-[999_1_600px] min-w-0 px-4 pt-5 pb-10 sm:px-9 sm:pt-7 sm:pb-14">
        <div className="max-w-[1240px] w-full flex flex-col gap-6">
          <Suspense fallback={<Loading what="the page" />}>
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
