import type { StaffQuery } from "./api/staff";

export type StaffSummaryId = "total" | "active" | "disabled" | "administrators";

export type StaffSummaryCard = {
  id: StaffSummaryId;
  label: string;
  /** What the number counts. Static wording, never a trend: there is no history to compare. */
  description: string;
  filters: Pick<StaffQuery, "status" | "role">;
};

/** The dashboard's four current totals, each one count-only staff query. */
export const STAFF_SUMMARY: readonly StaffSummaryCard[] = [
  { id: "total", label: "Total staff", description: "All staff accounts", filters: {} },
  { id: "active", label: "Active staff", description: "Can sign in", filters: { status: "active" } },
  { id: "disabled", label: "Disabled staff", description: "Cannot sign in", filters: { status: "disabled" } },
  {
    id: "administrators",
    label: "Administrators",
    description: "Full workspace access",
    filters: { role: "administrator" },
  },
];

export type RoleCount = { code: string; label: string; count: number };

export type RoleAssignmentRow = RoleCount & {
  /** Share of all role assignments, or null when there are none to share. */
  share: number | null;
  /** Bar length relative to the largest role, 0 to 1. */
  width: number;
};

export type RoleAssignments = { rows: RoleAssignmentRow[]; totalAssignments: number; staffTotal: number };

/**
 * Per-role assignment counts, largest first (ties keep the given role order). Staff can hold
 * several roles, so the assignments may add up to more than the staff total.
 */
export function roleAssignments(counts: RoleCount[], staffTotal: number): RoleAssignments {
  const totalAssignments = counts.reduce((sum, role) => sum + role.count, 0);
  const largest = Math.max(0, ...counts.map((role) => role.count));
  const rows = counts
    .map((role) => ({
      ...role,
      share: totalAssignments ? role.count / totalAssignments : null,
      width: largest ? role.count / largest : 0,
    }))
    .sort((a, b) => b.count - a.count);
  return { rows, totalAssignments, staffTotal };
}

const shareFormat = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });

/** "47.2%" in the user's locale, or a dash when there is nothing to take a share of. */
export function formatShare(share: number | null, format: Intl.NumberFormat = shareFormat): string {
  return share === null ? "—" : format.format(share);
}
