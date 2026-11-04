import type { AuditEvent } from "./api/staff";

/** Readable names for the API's audit event codes (apis/app/audit/events.py). */
export const AUDIT_EVENT_LABELS = {
  "auth.login_succeeded": "Signed in",
  "auth.login_failed": "Sign-in failed",
  "auth.rate_limited": "Too many sign-in attempts",
  "auth.refresh_token_reused": "Reused session token blocked",
  "auth.logout": "Signed out",
  "auth.password_changed": "Password changed",
  "auth.permission_denied": "Access denied",
  "staff.bootstrap_admin_created": "First administrator created",
  "staff.created": "Staff member created",
  "staff.profile_updated": "Profile updated",
  "staff.roles_changed": "Roles changed",
  "staff.disabled": "Account disabled",
  "staff.reactivated": "Account reactivated",
  "staff.sessions_revoked": "Signed out everywhere",
} as const;

export const AUDIT_EVENT_CODES = Object.keys(AUDIT_EVENT_LABELS) as Array<keyof typeof AUDIT_EVENT_LABELS>;

/** The readable name, or the code itself for an event this version does not know yet. */
export function auditEventLabel(code: string): string {
  return (AUDIT_EVENT_LABELS as Record<string, string>)[code] ?? code;
}

// Recorded before anyone is signed in, so a missing actor is not the system acting.
const ANONYMOUS_EVENTS = new Set(["auth.login_failed", "auth.rate_limited"]);

/**
 * An audit event reduced to what the dashboard may show. Metadata is deliberately not
 * carried over: it holds IP prefixes and session identifiers, and the full audit log is the
 * place to inspect it.
 */
export type ActivityItem = {
  id: string;
  code: string;
  label: string;
  occurredAt: string;
  /** Who acted: a staff ID, or how to describe a missing actor. */
  actor: { kind: "staff"; id: string } | { kind: "system" } | { kind: "anonymous" };
  /** The staff member affected, when it is someone other than the actor. */
  subjectId: string | null;
};

export function toActivityItem(event: AuditEvent): ActivityItem {
  return {
    id: event.id,
    code: event.eventCode,
    label: auditEventLabel(event.eventCode),
    occurredAt: event.occurredAt,
    actor: event.actorId
      ? { kind: "staff", id: event.actorId }
      : { kind: ANONYMOUS_EVENTS.has(event.eventCode) ? "anonymous" : "system" },
    subjectId:
      event.entityType === "user" && event.entityId && event.entityId !== event.actorId ? event.entityId : null,
  };
}

/** Newest first, as the API sends them; sorted again so the order never depends on it. */
export function recentActivity(events: AuditEvent[]): ActivityItem[] {
  return [...events]
    .sort((a, b) => Date.parse(b.occurredAt) - Date.parse(a.occurredAt) || b.id.localeCompare(a.id))
    .map(toActivityItem);
}

/** Staff IDs the activity mentions, once each, for looking up names. */
export function mentionedStaff(items: ActivityItem[]): string[] {
  const ids = new Set<string>();
  for (const item of items) {
    if (item.actor.kind === "staff") ids.add(item.actor.id);
    if (item.subjectId) ids.add(item.subjectId);
  }
  return [...ids];
}
