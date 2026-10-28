// Fetch helpers and the `useJson` hook every page reads through. Every request names the
// caller: AUTH_MODE=header trusts X-Actor / X-Actor-Kind (dev only), and the web UI is
// always a human — the person picked in the sidebar's "Viewing as".

import { createContext, useCallback, useContext, useEffect, useState } from 'react';

export type Loaded<T> = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; data: T };

let currentActor = '';

/** Set by the persona switcher; every request after this carries it. */
export function setActor(person: string) {
  currentActor = person;
}

export function actor(): string {
  return currentActor;
}

/** A failed request: the RFC 9457 problem body's `detail`, plus `error_data` when the write
 * path rejected a batch (each op's `errors`). */
export class ApiError extends Error {
  status: number;
  code: string;
  data: Record<string, unknown>;
  constructor(message: string, status: number, code = '', data: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  if (currentActor) h.set('X-Actor', currentActor);
  h.set('X-Actor-Kind', 'human');
  return h;
}

export async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, headers: headers(init?.headers) });
  } catch {
    throw new ApiError('The service is not reachable. Is `make dev` running?', 0);
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    let code = '';
    let data: Record<string, unknown> = {};
    try {
      const body = await response.json();
      detail = body.detail || body.title || body.message || detail;
      code = body.error_code || '';
      data = body.error_data || {};
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, response.status, code, data);
  }
  return response.json();
}

export function postJson<T>(url: string, body: unknown): Promise<T> {
  return getJson<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** `/api/initiatives/{slug}/…` with each segment encoded. */
export function api(...parts: (string | number)[]): string {
  return '/api/' + parts.map((p) => encodeURIComponent(String(p))).join('/');
}

/** The write path's refusal, readable: the problem detail plus each op's errors. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const results = (e.data.results as { errors?: string[] }[] | undefined) || [];
    const errs = results.flatMap((r) => r.errors || []).filter((x) => x !== 'not saved');
    const listed = (e.data.errors as string[] | undefined) || [];
    const extra = [...errs, ...listed].filter((x) => !e.message.includes(x));
    return [e.message, ...extra].join(' · ');
  }
  return (e as Error).message;
}

// ── refresh after a write ───────────────────────────────────────────────────

/** A write changes what many pages show (inbox counts, gates, drift): bumping the version
 * re-fetches every mounted `useJson`, without flashing back to a loading state. */
export const RefreshContext = createContext<{ version: number; bump: () => void }>({ version: 0, bump: () => {} });

export function useRefresh() {
  return useContext(RefreshContext);
}

export function useJson<T>(url: string | null): Loaded<T> & { reload: () => void } {
  const { version } = useRefresh();
  const [state, setState] = useState<{ url: string | null; loaded: Loaded<T> }>({ url, loaded: { kind: 'loading' } });
  const [local, setLocal] = useState(0);
  useEffect(() => {
    if (!url) return;
    let live = true;
    setState((s) => (s.url === url && s.loaded.kind === 'ready' ? s : { url, loaded: { kind: 'loading' } }));
    getJson<T>(url)
      .then((data) => live && setState({ url, loaded: { kind: 'ready', data } }))
      .catch((e: Error) => live && setState({ url, loaded: { kind: 'error', message: e.message } }));
    return () => {
      live = false;
    };
  }, [url, version, local]);
  const reload = useCallback(() => setLocal((n) => n + 1), []);
  const loaded: Loaded<T> = state.url === url ? state.loaded : { kind: 'loading' };
  return { ...loaded, reload } as Loaded<T> & { reload: () => void };
}

/** Several URLs at once (composition across initiatives or people); ready when all are. */
export function useJsonAll<T>(urls: string[] | null): Loaded<T[]> {
  const { version } = useRefresh();
  const key = urls ? urls.join('\n') : null;
  const [state, setState] = useState<{ key: string | null; loaded: Loaded<T[]> }>({ key, loaded: { kind: 'loading' } });
  useEffect(() => {
    if (key === null) return;
    let live = true;
    setState((s) => (s.key === key && s.loaded.kind === 'ready' ? s : { key, loaded: { kind: 'loading' } }));
    Promise.all((key ? key.split('\n') : []).map((u) => getJson<T>(u)))
      .then((data) => live && setState({ key, loaded: { kind: 'ready', data } }))
      .catch((e: Error) => live && setState({ key, loaded: { kind: 'error', message: e.message } }));
    return () => {
      live = false;
    };
  }, [key, version]);
  return state.key === key ? state.loaded : { kind: 'loading' };
}

/** Combine loaded values: an error wins, then loading, else all ready. */
export function all<A, B>(a: Loaded<A>, b: Loaded<B>): Loaded<[A, B]>;
export function all<A, B, C>(a: Loaded<A>, b: Loaded<B>, c: Loaded<C>): Loaded<[A, B, C]>;
export function all<A, B, C, D>(a: Loaded<A>, b: Loaded<B>, c: Loaded<C>, d: Loaded<D>): Loaded<[A, B, C, D]>;
export function all(...xs: Loaded<unknown>[]): Loaded<unknown[]> {
  const err = xs.find((x) => x.kind === 'error') as { kind: 'error'; message: string } | undefined;
  if (err) return err;
  if (xs.some((x) => x.kind === 'loading')) return { kind: 'loading' };
  return { kind: 'ready', data: xs.map((x) => (x as { data: unknown }).data) };
}
