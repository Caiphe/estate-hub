"use client";

import { useMemo, useState, type FormEvent } from "react";

import { Pagination } from "@/components/pagination";
import { Forbidden, LoadError, Loading } from "@/components/status-panels";
import { staffApi, type AuditQuery } from "@/lib/api/staff";
import { AUDIT_EVENT_CODES } from "@/lib/audit-events";
import { useSession } from "@/lib/session";
import { useRemote } from "@/lib/use-remote";

const PAGE_SIZE = 25;

type Draft = { eventCode: string; actorId: string; entityId: string; from: string; to: string };
const EMPTY: Draft = { eventCode: "", actorId: "", entityId: "", from: "", to: "" };

/** A datetime-local value (browser time zone) as an ISO timestamp the API accepts. */
function toIso(value: string): string | undefined {
  return value ? new Date(value).toISOString() : undefined;
}

export default function AuditPage() {
  const { client } = useSession();
  const api = useMemo(() => staffApi(client), [client]);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [query, setQuery] = useState<AuditQuery>({ offset: 0 });
  const [remote, reload] = useRemote(JSON.stringify(query), () =>
    api.auditEvents({ ...query, limit: PAGE_SIZE }),
  );

  if (remote.status === "forbidden") return <Forbidden what="the audit log" />;

  const field = (name: keyof Draft) => ({
    value: draft[name],
    onChange: (event: { target: { value: string } }) =>
      setDraft((previous) => ({ ...previous, [name]: event.target.value })),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery({
      eventCode: draft.eventCode,
      actorId: draft.actorId,
      entityId: draft.entityId,
      occurredFrom: toIso(draft.from),
      occurredTo: toIso(draft.to),
      offset: 0,
    });
  }

  return (
    <section className="panel" aria-labelledby="audit-heading">
      <h1 id="audit-heading" className="page-title">
        Audit log
      </h1>
      <p className="summary">Read-only record of security events and staff changes, newest first.</p>

      <form className="filters" onSubmit={onSubmit} aria-label="Filter audit events">
        <div className="field">
          <label htmlFor="audit-code">Event</label>
          <select id="audit-code" {...field("eventCode")}>
            <option value="">Any event</option>
            {AUDIT_EVENT_CODES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="audit-actor">Actor ID</label>
          <input id="audit-actor" {...field("actorId")} />
        </div>
        <div className="field">
          <label htmlFor="audit-entity">Staff member ID</label>
          <input id="audit-entity" {...field("entityId")} />
        </div>
        <div className="field">
          <label htmlFor="audit-from">From</label>
          <input id="audit-from" type="datetime-local" {...field("from")} />
        </div>
        <div className="field">
          <label htmlFor="audit-to">Until</label>
          <input id="audit-to" type="datetime-local" {...field("to")} />
        </div>
        <button type="submit" className="button button-secondary">
          Apply filters
        </button>
      </form>

      {remote.status === "loading" && <Loading label="Loading audit events…" />}
      {remote.status === "not_found" && (
        <div className="form-error" role="alert">
          Check the filters: IDs must be complete UUIDs and the start must be before the end.
        </div>
      )}
      {remote.status === "error" && <LoadError onRetry={reload} />}
      {remote.status === "ready" && (
        <>
          <div className="table-wrap">
            <table className="table">
              <caption className="visually-hidden">Audit events</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Event</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Staff member</th>
                  <th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {remote.data.items.map((event) => (
                  <tr key={event.id}>
                    <td>{new Date(event.occurredAt).toLocaleString()}</td>
                    <th scope="row">
                      <code>{event.eventCode}</code>
                    </th>
                    <td>{event.actorId ? <code>{event.actorId}</code> : "System"}</td>
                    <td>{event.entityId ? <code>{event.entityId}</code> : "—"}</td>
                    <td>
                      <code className="metadata">{JSON.stringify(event.metadata)}</code>
                    </td>
                  </tr>
                ))}
                {remote.data.items.length === 0 && (
                  <tr>
                    <td colSpan={5}>No events match these filters.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            total={remote.data.total}
            offset={remote.data.offset}
            count={remote.data.items.length}
            pageSize={PAGE_SIZE}
            label="Audit pages"
            onPage={(offset) => setQuery((previous) => ({ ...previous, offset }))}
          />
        </>
      )}
    </section>
  );
}
