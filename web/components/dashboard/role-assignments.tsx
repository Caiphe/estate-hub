"use client";

import { useState } from "react";

import { ROLE_OPTIONS, type StaffApi } from "@/lib/api/staff";
import { formatShare, roleAssignments, type RoleAssignments as Assignments } from "@/lib/dashboard";
import { useStaffRevision } from "@/lib/staff-changes";
import { useRemote } from "@/lib/use-remote";

import { DashboardPanel, PanelError, PanelForbidden, PanelLoading } from "./panel";

/** How many staff hold each role: five count-only queries, sent together. */
async function loadAssignments(api: StaffApi, signal: AbortSignal): Promise<Assignments> {
  const [staffTotal, ...counts] = await Promise.all([
    api.count({}, signal),
    ...ROLE_OPTIONS.map((role) => api.count({ role: role.code }, signal)),
  ]);
  return roleAssignments(
    ROLE_OPTIONS.map((role, index) => ({ code: role.code, label: role.label, count: counts[index] })),
    staffTotal,
  );
}

export function RoleAssignments({ api }: { api: StaffApi }) {
  const revision = useStaffRevision();
  // Retrying changes the key, so the panel shows loading again rather than the old error.
  const [attempt, setAttempt] = useState(0);
  const [remote] = useRemote(`roles:${revision}:${attempt}`, (signal) => loadAssignments(api, signal));

  return (
    <DashboardPanel
      id="role-assignments"
      title="Role assignments"
      description="Roles held by staff. One person can hold several, so assignments can exceed the staff total."
    >
      {remote.status === "loading" && <PanelLoading rows={ROLE_OPTIONS.length} label="Loading role assignments" />}
      {remote.status === "ready" && <RoleAssignmentsView data={remote.data} />}
      {remote.status === "forbidden" && <PanelForbidden what="role assignments" />}
      {(remote.status === "error" || remote.status === "not_found") && (
        <PanelError what="Role assignments" onRetry={() => setAttempt((value) => value + 1)} />
      )}
    </DashboardPanel>
  );
}

const countFormat = new Intl.NumberFormat();

/**
 * Ranked bars, one per role, in a real table: the visible legend and the text equivalent
 * are the same element. The bars are decorative; every value is printed beside them.
 */
export function RoleAssignmentsView({ data, shareFormat }: { data: Assignments; shareFormat?: Intl.NumberFormat }) {
  return (
    <div className="grid gap-3">
      <p className="m-0 text-sm text-fg">
        {data.totalAssignments ? (
          <>
            <strong className="font-extrabold">{countFormat.format(data.totalAssignments)}</strong> role assignments
            across <strong className="font-extrabold">{countFormat.format(data.staffTotal)}</strong> staff members.
          </>
        ) : (
          "No roles are assigned yet."
        )}
      </p>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Role assignments by role, largest first</caption>
        <thead>
          <tr className="border-b border-line text-xs text-fg-muted">
            <th scope="col" className="pb-2 text-left font-semibold">
              Role
            </th>
            <th scope="col" className="pb-2 pl-4 text-right font-semibold">
              Assigned
            </th>
            <th scope="col" className="pb-2 pl-4 text-right font-semibold">
              Share
            </th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.code} className="border-b border-line last:border-b-0">
              <th scope="row" className="w-full py-3 text-left font-semibold text-fg">
                {row.label}
                <span aria-hidden="true" className="mt-2 block h-2 rounded-full bg-canvas">
                  <span className="block h-2 rounded-full bg-brand" style={{ width: `${row.width * 100}%` }} />
                </span>
              </th>
              <td className="py-3 pl-4 text-right text-base font-extrabold text-fg tabular-nums">
                {countFormat.format(row.count)}
              </td>
              <td className="py-3 pl-4 text-right text-fg-muted tabular-nums">{formatShare(row.share, shareFormat)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
