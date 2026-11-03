"use client";

import { useSession } from "@/lib/session";

export default function DashboardPage() {
  const { user, roles } = useSession();

  return (
    <section className="panel" aria-labelledby="dashboard-heading">
      <p className="eyebrow">Staff workspace</p>
      <h1 id="dashboard-heading" className="page-title">
        Welcome, {user.fullName}
      </h1>
      <dl className="details">
        <div>
          <dt>Signed in as</dt>
          <dd>{user.email}</dd>
        </div>
        <div>
          <dt>Roles</dt>
          <dd>{roles.length ? roles.join(", ") : "No roles assigned"}</dd>
        </div>
      </dl>
    </section>
  );
}
