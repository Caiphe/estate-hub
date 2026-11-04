"use client";

import { useMemo } from "react";

import { AccountSummary } from "@/components/dashboard/account-summary";
import { DashboardHeader } from "@/components/dashboard/dashboard-header";
import { RecentActivity } from "@/components/dashboard/recent-activity";
import { RoleAssignments } from "@/components/dashboard/role-assignments";
import { StaffSummary } from "@/components/dashboard/staff-summary";
import { staffApi } from "@/lib/api/staff";
import { useSession } from "@/lib/session";

export default function DashboardPage() {
  const { client, user, roles, permissions } = useSession();
  const api = useMemo(() => staffApi(client), [client]);
  const staffAccess = permissions.includes("staff:read");
  const auditAccess = permissions.includes("audit:read");

  return (
    <>
      <DashboardHeader fullName={user.fullName} staffAccess={staffAccess} />
      {staffAccess ? (
        <>
          <StaffSummary api={api} />
          {/* Without audit:read, role assignments take the full width. */}
          <div className={`grid gap-5 ${auditAccess ? "xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]" : ""}`}>
            {auditAccess && <RecentActivity api={api} />}
            <RoleAssignments api={api} />
          </div>
        </>
      ) : (
        <AccountSummary email={user.email} roles={roles} />
      )}
    </>
  );
}
