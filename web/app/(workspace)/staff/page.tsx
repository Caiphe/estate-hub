"use client";

import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { roleLabel } from "@/components/role-checkboxes";
import { Pagination } from "@/components/pagination";
import { Forbidden, LoadError, Loading } from "@/components/status-panels";
import { ROLE_OPTIONS, staffApi, type StaffQuery } from "@/lib/api/staff";
import { useSession } from "@/lib/session";
import { useRemote } from "@/lib/use-remote";

const PAGE_SIZE = 20;

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

export default function StaffListPage() {
  const { client, permissions } = useSession();
  const api = useMemo(() => staffApi(client), [client]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState<StaffQuery>({ status: "", role: "", q: "", offset: 0 });
  const key = JSON.stringify(query);
  const [remote, reload] = useRemote(key, () => api.list({ ...query, limit: PAGE_SIZE }));

  if (remote.status === "forbidden") return <Forbidden what="staff accounts" />;

  const update = (change: Partial<StaffQuery>) =>
    setQuery((previous) => ({ ...previous, ...change, offset: change.offset ?? 0 }));
  const onSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    update({ q: search });
  };

  return (
    <section className="panel" aria-labelledby="staff-heading">
      <div className="panel-header">
        <h1 id="staff-heading" className="page-title">
          Staff
        </h1>
        {permissions.includes("staff:create") && (
          <Link href="/staff/new" className="button">
            Add staff member
          </Link>
        )}
      </div>

      <div className="filters">
        <form role="search" className="filter-search" onSubmit={onSearch}>
          <label htmlFor="staff-search">Search name or email</label>
          <div className="inline">
            <input
              id="staff-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <button type="submit" className="button button-secondary">
              Search
            </button>
          </div>
        </form>
        <div className="field">
          <label htmlFor="staff-status">Status</label>
          <select
            id="staff-status"
            value={query.status}
            onChange={(event) => update({ status: event.target.value as StaffQuery["status"] })}
          >
            <option value="">Any status</option>
            <option value="active">Active</option>
            <option value="disabled">Disabled</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="staff-role">Role</label>
          <select id="staff-role" value={query.role} onChange={(event) => update({ role: event.target.value })}>
            <option value="">Any role</option>
            {ROLE_OPTIONS.map((role) => (
              <option key={role.code} value={role.code}>
                {role.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {remote.status === "loading" && <Loading label="Loading staff…" />}
      {(remote.status === "error" || remote.status === "not_found") && <LoadError onRetry={reload} />}
      {remote.status === "ready" && (
        <>
          <div className="table-wrap">
            <table className="table">
              <caption className="visually-hidden">Staff accounts</caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Email</th>
                  <th scope="col">Roles</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last sign-in</th>
                </tr>
              </thead>
              <tbody>
                {remote.data.items.map((member) => (
                  <tr key={member.id}>
                    <th scope="row">
                      <Link href={`/staff/${member.id}`} className="text-link">
                        {member.fullName}
                      </Link>
                    </th>
                    <td>{member.email}</td>
                    <td>{member.roles.map(roleLabel).join(", ") || "None"}</td>
                    <td>
                      <span className={`status status-${member.status}`}>{member.status}</span>
                    </td>
                    <td>{formatDate(member.lastLoginAt)}</td>
                  </tr>
                ))}
                {remote.data.items.length === 0 && (
                  <tr>
                    <td colSpan={5}>No staff members match these filters.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            total={remote.data.total}
            offset={remote.data.offset}
            count={remote.data.items.length}
            onPage={(offset) => update({ offset })}
            pageSize={PAGE_SIZE}
            label="Staff pages"
          />
        </>
      )}
    </section>
  );
}
