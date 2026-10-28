import { Banner } from './ui';

/** Loading is a shimmer, never a spinner. */
export function Loading({ what }: { what: string }) {
  return (
    <div className="flex flex-col gap-4" role="status" aria-label={`Loading ${what}`}>
      <div className="h-8 w-2/5 rounded-ctl bg-line-soft animate-pulse" />
      <div className="h-24 w-full rounded-card bg-line-soft animate-pulse" />
      <div className="h-40 w-full rounded-card bg-line-soft animate-pulse" />
    </div>
  );
}

/** A failed fetch is a banner, never an empty state. */
export function LoadError({ what, message, onRetry }: { what: string; message: string; onRetry?: () => void }) {
  return (
    <Banner tone="bad" role="alert">
      Could not load {what}: <span className="font-normal">{message}</span>
      {onRetry && (
        <button type="button" className="btn btn-link ml-2 min-h-0" onClick={onRetry}>
          Try again
        </button>
      )}
    </Banner>
  );
}
