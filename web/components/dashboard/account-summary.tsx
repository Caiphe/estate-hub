import Link from "next/link";

import { roleLabel } from "@/components/role-checkboxes";

/**
 * Who is signed in and with which roles: the dashboard for staff without staff:read, who
 * see no staff summaries, so the page still says something useful about their access.
 */
export function AccountSummary({ email, roles }: { email: string; roles: string[] }) {
  return (
    <section className="panel" aria-labelledby="account-summary-heading">
      <h2 id="account-summary-heading" className="section-title">
        Your account
      </h2>
      <dl className="details">
        <div>
          <dt>Signed in as</dt>
          <dd>{email}</dd>
        </div>
        <div>
          <dt>Roles</dt>
          <dd>{roles.length ? roles.map(roleLabel).join(", ") : "No roles assigned"}</dd>
        </div>
      </dl>
      <p className="m-0">
        <Link href="/account/password" className="text-link">
          Change your password
        </Link>
      </p>
    </section>
  );
}
