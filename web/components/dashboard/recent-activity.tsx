"use client";

import Link from "next/link";
import { useState } from "react";

import { LockIcon, UsersIcon } from "@/components/landing/icons";
import type { StaffApi } from "@/lib/api/staff";
import { mentionedStaff, recentActivity, type ActivityItem } from "@/lib/audit-events";
import { formatDateTime } from "@/lib/format";
import { useStaffRevision } from "@/lib/staff-changes";
import { useRemote } from "@/lib/use-remote";

import { DashboardPanel, PanelError, PanelForbidden, PanelLoading } from "./panel";

const LIMIT = 6;

type Activity = { items: ActivityItem[]; names: Map<string, string> };

/** The newest events, then the names of the staff they mention (one lookup per person). */
async function loadActivity(api: StaffApi, signal: AbortSignal): Promise<Activity> {
  const page = await api.auditEvents({ limit: LIMIT }, signal);
  const items = recentActivity(page.items);
  const ids = mentionedStaff(items);
  const people = await Promise.allSettled(ids.map((id) => api.get(id, signal)));
  signal.throwIfAborted();
  const names = new Map<string, string>();
  people.forEach((result, index) => {
    if (result.status === "fulfilled") names.set(ids[index], result.value.fullName);
  });
  return { items, names };
}

export function RecentActivity({ api }: { api: StaffApi }) {
  const revision = useStaffRevision();
  const [attempt, setAttempt] = useState(0);
  const [remote] = useRemote(`activity:${revision}:${attempt}`, (signal) => loadActivity(api, signal));

  return (
    <DashboardPanel
      id="recent-activity"
      title="Recent staff activity"
      description="The latest sign-ins and staff changes, newest first."
      action={
        <Link
          href="/audit"
          className="inline-flex min-h-11 items-center text-sm font-bold text-brand-strong underline underline-offset-4"
        >
          View full audit log
        </Link>
      }
    >
      {remote.status === "loading" && <PanelLoading rows={LIMIT} label="Loading recent activity" />}
      {remote.status === "ready" && <RecentActivityView {...remote.data} />}
      {remote.status === "forbidden" && <PanelForbidden what="the audit log" />}
      {(remote.status === "error" || remote.status === "not_found") && (
        <PanelError what="Recent activity" onRetry={() => setAttempt((value) => value + 1)} />
      )}
    </DashboardPanel>
  );
}

function actorText(item: ActivityItem, names: Map<string, string>): string {
  if (item.actor.kind === "anonymous") return "Not signed in";
  if (item.actor.kind === "system") return "By the system";
  return `By ${names.get(item.actor.id) ?? "an unknown staff member"}`;
}

/** The event list. Takes ActivityItems only, so audit metadata can never reach the page. */
export function RecentActivityView({
  items,
  names,
  locale,
  timeZone,
}: Activity & { locale?: string; timeZone?: string }) {
  if (!items.length) {
    return <p className="m-0 text-sm text-fg-muted">No staff activity has been recorded yet.</p>;
  }
  return (
    <ol className="m-0 grid list-none p-0">
      {items.map((item) => {
        const Icon = item.code.startsWith("auth.") ? LockIcon : UsersIcon;
        return (
          <li key={item.id} className="flex items-start gap-3 border-b border-line py-3 first:pt-0 last:border-b-0 last:pb-0">
            <span
              aria-hidden="true"
              className="grid size-9 shrink-0 place-items-center rounded-md bg-brand-subtle text-brand-strong"
            >
              <Icon width="18" height="18" />
            </span>
            <div className="grid min-w-0 flex-1 gap-0.5">
              <p className="m-0 text-sm font-bold text-fg">{item.label}</p>
              <p className="m-0 text-sm break-words text-fg-muted">
                {actorText(item, names)}
                {item.subjectId && <> · Affected: {names.get(item.subjectId) ?? "an unknown staff member"}</>}
              </p>
            </div>
            <div className="grid shrink-0 justify-items-end gap-0.5 text-right">
              <time dateTime={item.occurredAt} className="text-xs font-semibold text-fg">
                {formatDateTime(item.occurredAt, { locale, timeZone })}
              </time>
              <code className="font-mono text-xs text-fg-muted">
                <span className="sr-only">Event code </span>
                {item.code}
              </code>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
