"use client";

import { useState, type ComponentType, type SVGProps } from "react";

import {
  AlertCircleIcon,
  ShieldCheckIcon,
  UserCheckIcon,
  UserXIcon,
  UsersIcon,
} from "@/components/landing/icons";
import type { StaffApi } from "@/lib/api/staff";
import { STAFF_SUMMARY, type StaffSummaryCard, type StaffSummaryId } from "@/lib/dashboard";
import { useStaffRevision } from "@/lib/staff-changes";
import { useRemote, type Remote } from "@/lib/use-remote";

const ICONS: Record<StaffSummaryId, ComponentType<SVGProps<SVGSVGElement>>> = {
  total: UsersIcon,
  active: UserCheckIcon,
  disabled: UserXIcon,
  administrators: ShieldCheckIcon,
};

/**
 * Four current staff totals. Each card runs its own count-only query, so one failure or slow
 * response never holds back the others, and each refetches after a staff mutation.
 */
export function StaffSummary({ api }: { api: StaffApi }) {
  const revision = useStaffRevision();
  return (
    <section aria-labelledby="staff-summary-heading">
      <h2 id="staff-summary-heading" className="sr-only">
        Staff summary
      </h2>
      <dl className="m-0 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {STAFF_SUMMARY.map((card) => (
          <SummaryCard key={card.id} card={card} api={api} revision={revision} />
        ))}
      </dl>
    </section>
  );
}

function SummaryCard({ card, api, revision }: { card: StaffSummaryCard; api: StaffApi; revision: number }) {
  // Retrying changes the key, so the card shows loading again rather than the old error.
  const [attempt, setAttempt] = useState(0);
  const [remote] = useRemote(`${card.id}:${revision}:${attempt}`, (signal) => api.count(card.filters, signal));
  const Icon = ICONS[card.id];

  return (
    <div className="flex items-center gap-4 rounded-lg border border-line bg-surface p-5 shadow-card">
      <span
        aria-hidden="true"
        className="grid size-14 shrink-0 place-items-center rounded-md bg-brand-subtle text-brand-strong"
      >
        <Icon width="28" height="28" />
      </span>
      <div className="grid min-w-0">
        <dt className="text-sm font-bold text-fg">{card.label}</dt>
        <dd className="m-0 flex min-h-11 items-center">
          <SummaryValue remote={remote} label={card.label} onRetry={() => setAttempt((value) => value + 1)} />
        </dd>
        <dd className="m-0 text-xs text-fg-muted">{card.description}</dd>
      </div>
    </div>
  );
}

const numberFormat = new Intl.NumberFormat();

/** One card's number, or what stands in for it. Every state keeps the same height. */
export function SummaryValue({
  remote,
  label,
  onRetry,
}: {
  remote: Remote<number>;
  label: string;
  onRetry: () => void;
}) {
  switch (remote.status) {
    case "loading":
      return (
        <>
          <span aria-hidden="true" className="block h-8 w-16 animate-pulse rounded-sm bg-canvas motion-reduce:animate-none" />
          <span className="sr-only">Loading</span>
        </>
      );
    case "ready":
      return (
        <span className="text-[2rem] leading-tight font-extrabold tracking-tight text-fg tabular-nums">
          {numberFormat.format(remote.data)}
        </span>
      );
    case "forbidden":
      return <span className="text-sm font-semibold text-fg-muted">No access</span>;
    default:
      return (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-fg">
            <AlertCircleIcon width="16" height="16" className="text-danger" />
            Unavailable
          </span>
          <button
            type="button"
            onClick={onRetry}
            className="m-0 min-h-11 cursor-pointer rounded-sm border border-line bg-surface px-3 font-sans text-sm font-bold text-brand-strong hover:bg-canvas"
          >
            Retry<span className="sr-only"> {label}</span>
          </button>
        </span>
      );
  }
}
