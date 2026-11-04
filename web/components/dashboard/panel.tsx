import type { ReactNode } from "react";

import { AlertCircleIcon } from "@/components/landing/icons";

/** A titled dashboard card. The heading names the region for assistive technology. */
export function DashboardPanel({
  id,
  title,
  description,
  action,
  children,
}: {
  id: string;
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`${id}-heading`}
      className="grid min-w-0 content-start gap-5 rounded-lg border border-line bg-surface p-5 shadow-card sm:p-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="grid gap-1">
          <h2 id={`${id}-heading`} className="m-0 text-xl leading-tight font-extrabold tracking-tight text-fg">
            {title}
          </h2>
          <p className="m-0 text-sm text-fg-muted">{description}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Placeholder rows the size of the real ones, so the panel keeps its shape while loading. */
export function PanelLoading({ rows, label }: { rows: number; label: string }) {
  return (
    <div role="status" className="grid gap-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, index) => (
        <span
          key={index}
          aria-hidden="true"
          className="block h-11 animate-pulse rounded-sm bg-canvas motion-reduce:animate-none"
        />
      ))}
    </div>
  );
}

export function PanelError({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md bg-danger-subtle px-4 py-3">
      <span className="inline-flex items-center gap-2 text-sm font-semibold text-fg">
        <AlertCircleIcon width="18" height="18" className="shrink-0 text-danger" />
        {what} could not be loaded.
      </span>
      <button
        type="button"
        onClick={onRetry}
        className="m-0 min-h-11 cursor-pointer rounded-sm border border-line bg-surface px-3 font-sans text-sm font-bold text-brand-strong hover:bg-canvas"
      >
        Try again
      </button>
    </div>
  );
}

export function PanelForbidden({ what }: { what: string }) {
  return <p className="m-0 text-sm font-semibold text-fg-muted">You do not have access to {what}.</p>;
}
