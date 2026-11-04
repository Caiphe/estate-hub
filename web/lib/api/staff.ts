import { notifyStaffChanged } from "../staff-changes";

import type { ApiClient } from "./client";
import { ResponseShapeError, parseCurrentUser, type CurrentUser } from "./types";

export const ROLE_OPTIONS = [
  { code: "administrator", label: "Administrator" },
  { code: "manager", label: "Manager" },
  { code: "agent", label: "Agent" },
  { code: "accountant", label: "Accountant" },
] as const;

export type StaffMember = CurrentUser & { createdAt: string; updatedAt: string };

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type AuditEvent = {
  id: string;
  eventCode: string;
  actorId: string | null;
  entityType: string | null;
  entityId: string | null;
  occurredAt: string;
  requestId: string | null;
  metadata: Record<string, unknown>;
};

export type StaffQuery = {
  q?: string;
  status?: "" | "active" | "disabled";
  role?: string;
  limit?: number;
  offset?: number;
};

/** The API refuses longer searches with a validation error. */
export const STAFF_SEARCH_MAX_LENGTH = 100;

/** A search term as the API accepts it: trimmed, at most 100 characters (code points). */
export function normalizeStaffSearch(value: string | null | undefined): string {
  return [...(value ?? "").trim()].slice(0, STAFF_SEARCH_MAX_LENGTH).join("").trim();
}

export type AuditQuery = {
  eventCode?: string;
  actorId?: string;
  entityId?: string;
  occurredFrom?: string;
  occurredTo?: string;
  limit?: number;
  offset?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function parseStaffMember(data: unknown): StaffMember {
  const user = parseCurrentUser(data);
  const record = data as Record<string, unknown>;
  if (typeof record.created_at !== "string" || typeof record.updated_at !== "string") {
    throw new ResponseShapeError("staff member");
  }
  return { ...user, createdAt: record.created_at, updatedAt: record.updated_at };
}

export function parseAuditEvent(data: unknown): AuditEvent {
  if (
    !isRecord(data) ||
    typeof data.id !== "string" ||
    typeof data.event_code !== "string" ||
    !nullableString(data.actor_id) ||
    !nullableString(data.entity_type) ||
    !nullableString(data.entity_id) ||
    typeof data.occurred_at !== "string" ||
    !nullableString(data.request_id) ||
    !isRecord(data.metadata)
  ) {
    throw new ResponseShapeError("audit event");
  }
  return {
    id: data.id,
    eventCode: data.event_code,
    actorId: data.actor_id,
    entityType: data.entity_type,
    entityId: data.entity_id,
    occurredAt: data.occurred_at,
    requestId: data.request_id,
    metadata: data.metadata,
  };
}

export function pageParser<T>(parseItem: (item: unknown) => T): (data: unknown) => Page<T> {
  return (data) => {
    if (
      !isRecord(data) ||
      !Array.isArray(data.items) ||
      typeof data.total !== "number" ||
      typeof data.limit !== "number" ||
      typeof data.offset !== "number"
    ) {
      throw new ResponseShapeError("page");
    }
    return {
      items: data.items.map(parseItem),
      total: data.total,
      limit: data.limit,
      offset: data.offset,
    };
  };
}

/** A query string with empty values left out. */
export function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

const staffPath = (id: string) => `/staff/${encodeURIComponent(id)}`;

/** Passes a mutation's result through, after telling views that staff data changed. */
async function changed<T>(mutation: Promise<T>): Promise<T> {
  const result = await mutation;
  notifyStaffChanged();
  return result;
}

/** Staff and audit endpoints over the shared client (CSRF and refresh included). */
export function staffApi(client: ApiClient) {
  const list = (query: StaffQuery, signal?: AbortSignal) =>
    client.request(
      `/staff${queryString({ q: query.q?.trim(), status: query.status, role: query.role, limit: query.limit, offset: query.offset })}`,
      { signal },
      pageParser(parseStaffMember),
    );

  return {
    list,
    /** How many staff match the filters: the page total, fetching a single row. */
    count: async (filters: Pick<StaffQuery, "status" | "role">, signal?: AbortSignal) =>
      (await list({ status: filters.status, role: filters.role, limit: 1 }, signal)).total,
    get: (id: string, signal?: AbortSignal) => client.request(staffPath(id), { signal }, parseStaffMember),
    create: (input: { email: string; fullName: string; password: string; roles: string[] }) =>
      changed(
        client.request(
          "/staff",
          {
            method: "POST",
            json: {
              email: input.email,
              full_name: input.fullName,
              password: input.password,
              roles: input.roles,
            },
          },
          parseStaffMember,
        ),
      ),
    updateProfile: (id: string, input: { email?: string; fullName?: string }) =>
      changed(
        client.request(
          staffPath(id),
          {
            method: "PATCH",
            json: {
              ...(input.email !== undefined && { email: input.email }),
              ...(input.fullName !== undefined && { full_name: input.fullName }),
            },
          },
          parseStaffMember,
        ),
      ),
    replaceRoles: (id: string, roles: string[]) =>
      changed(
        client.request(`${staffPath(id)}/roles`, { method: "PUT", json: { roles } }, parseStaffMember),
      ),
    disable: (id: string) =>
      changed(client.request(`${staffPath(id)}/disable`, { method: "POST" }, parseStaffMember)),
    reactivate: (id: string) =>
      changed(client.request(`${staffPath(id)}/reactivate`, { method: "POST" }, parseStaffMember)),
    revokeSessions: (id: string) =>
      changed(client.request(`${staffPath(id)}/revoke-sessions`, { method: "POST" })),
    auditEvents: (query: AuditQuery, signal?: AbortSignal) =>
      client.request(
        `/audit-events${queryString({
          event_code: query.eventCode?.trim(),
          actor_id: query.actorId?.trim(),
          entity_id: query.entityId?.trim(),
          entity_type: query.entityId?.trim() ? "user" : undefined,
          occurred_from: query.occurredFrom,
          occurred_to: query.occurredTo,
          limit: query.limit,
          offset: query.offset,
        })}`,
        { signal },
        pageParser(parseAuditEvent),
      ),
  };
}

export type StaffApi = ReturnType<typeof staffApi>;
