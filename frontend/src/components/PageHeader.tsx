import React from 'react';
import { Link } from 'react-router-dom';

export interface Crumb {
  label: React.ReactNode;
  href?: string;
  mono?: boolean;
}

/** Breadcrumb, the page title with its badge, and a line of metadata under it. */
export function PageHeader({
  crumbs,
  title,
  badge,
  aside,
  children,
}: {
  crumbs?: Crumb[];
  title: React.ReactNode;
  badge?: React.ReactNode;
  aside?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-2.5">
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="text-[13px] text-ink-muted flex gap-1.5 items-center flex-wrap">
          {crumbs.map((c, i) => (
            <React.Fragment key={i}>
              {i > 0 && <span aria-hidden="true">/</span>}
              {c.href ? (
                <Link to={c.href} className={`no-underline hover:underline ${c.mono ? 'font-mono' : ''}`}>
                  {c.label}
                </Link>
              ) : (
                <span className={c.mono ? 'font-mono' : ''}>{c.label}</span>
              )}
            </React.Fragment>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap gap-3 items-center justify-between">
        <div className="flex flex-wrap gap-3 items-center min-w-0">
          <h1>{title}</h1>
          {badge}
        </div>
        {aside}
      </div>
      {children}
    </header>
  );
}
