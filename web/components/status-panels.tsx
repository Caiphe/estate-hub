import Link from "next/link";

/** Shown when the API answers 403. The API decides; the UI only reports it. */
export function Forbidden({ what }: { what: string }) {
  return (
    <section className="panel" aria-labelledby="forbidden-heading">
      <h1 id="forbidden-heading" className="page-title">
        Access denied
      </h1>
      <p className="summary">You do not have permission to view {what}.</p>
      <Link href="/dashboard" className="text-link">
        Back to the dashboard
      </Link>
    </section>
  );
}

export function NotFound({ what }: { what: string }) {
  return (
    <section className="panel" aria-labelledby="not-found-heading">
      <h1 id="not-found-heading" className="page-title">
        Not found
      </h1>
      <p className="summary">{what} does not exist or was removed.</p>
    </section>
  );
}

export function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="form-error" role="alert">
      <p>The data could not be loaded.</p>
      <button type="button" className="button button-secondary" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <p className="muted" role="status" aria-live="polite">
      {label}
    </p>
  );
}
