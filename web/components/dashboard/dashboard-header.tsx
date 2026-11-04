"use client";

import { CalendarIcon } from "@/components/landing/icons";
import { displayName, formatDay, greetingFor, isoDay } from "@/lib/format";
import { useNow } from "@/lib/use-now";

type DashboardHeaderProps = {
  fullName: string;
  /** Staff readers get copy about their team; everyone else about their own workspace. */
  staffAccess: boolean;
};

/** The dashboard greeting and today's date, in the browser's locale and time zone. */
export function DashboardHeader(props: DashboardHeaderProps) {
  return <DashboardHeaderView {...props} now={useNow()} />;
}

/**
 * Rendering only, with the clock (and, for tests, the locale and time zone) passed in. `now`
 * is null before hydration: the heading then greets without a time of day and the date is
 * left out, so the server HTML never disagrees with the browser's clock or time zone.
 */
export function DashboardHeaderView({
  fullName,
  staffAccess,
  now,
  locale,
  timeZone,
}: DashboardHeaderProps & { now: Date | null; locale?: string; timeZone?: string }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
      <div className="grid min-w-0 gap-1.5">
        <h1 className="m-0 text-2xl leading-tight font-extrabold tracking-tight break-words text-fg">
          {now ? greetingFor(now, timeZone) : "Welcome"}, {displayName(fullName)}{" "}
          <span aria-hidden="true">👋</span>
        </h1>
        <p className="m-0 text-base text-fg-muted">
          {staffAccess
            ? "Here’s what’s happening with your EstateHub team today."
            : "Here’s your EstateHub workspace for today."}
        </p>
      </div>
      {now && (
        <p className="m-0 inline-flex min-h-11 shrink-0 items-center gap-2.5 rounded-md border border-line bg-surface px-4 text-sm font-semibold text-fg">
          <CalendarIcon className="text-fg-muted" />
          <time dateTime={isoDay(now, timeZone)}>{formatDay(now, { locale, timeZone })}</time>
        </p>
      )}
    </div>
  );
}
