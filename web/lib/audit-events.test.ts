import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { AuditEvent } from "./api/staff";
import {
  AUDIT_EVENT_CODES,
  auditEventLabel,
  mentionedStaff,
  recentActivity,
  toActivityItem,
} from "./audit-events";

const ADMIN = "11111111-1111-4111-8111-111111111111";
const MEMBER = "22222222-2222-4222-8222-222222222222";

function event(overrides: Partial<AuditEvent>): AuditEvent {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    eventCode: "staff.disabled",
    actorId: ADMIN,
    entityType: "user",
    entityId: MEMBER,
    occurredAt: "2026-11-04T09:00:00Z",
    requestId: "req-1",
    metadata: { revoked_sessions: 2, client_ip_prefix: "203.0.113.0/24", session_family_id: "f-1" },
    ...overrides,
  };
}

describe("audit event labels", () => {
  it("names every known event", () => {
    for (const code of AUDIT_EVENT_CODES) {
      expect(auditEventLabel(code)).not.toBe(code);
    }
    expect(auditEventLabel("staff.disabled")).toBe("Account disabled");
  });

  it("falls back to the code for an event this version does not know", () => {
    expect(auditEventLabel("staff.renamed")).toBe("staff.renamed");
  });

  const events = fileURLToPath(new URL("../../apis/app/audit/events.py", import.meta.url));
  it.skipIf(!existsSync(events))("matches the API's AuditEventCode enum exactly", () => {
    const codes = [...readFileSync(events, "utf8").matchAll(/=\s*"([a-z]+\.[a-z_]+)"/g)].map((match) => match[1]);
    expect([...AUDIT_EVENT_CODES].sort()).toEqual(codes.sort());
  });
});

describe("toActivityItem", () => {
  it("keeps the canonical code beside the readable label", () => {
    const item = toActivityItem(event({}));
    expect(item.code).toBe("staff.disabled");
    expect(item.label).toBe("Account disabled");
  });

  it("never carries metadata, request IDs, or other raw fields", () => {
    const item = toActivityItem(event({}));
    expect(Object.keys(item).sort()).toEqual(["actor", "code", "id", "label", "occurredAt", "subjectId"]);
    expect(JSON.stringify(item)).not.toMatch(/203\.0\.113|f-1|req-1|revoked/);
  });

  it("names the affected staff member only when it is someone else", () => {
    expect(toActivityItem(event({})).subjectId).toBe(MEMBER);
    expect(toActivityItem(event({ eventCode: "auth.login_succeeded", entityId: ADMIN })).subjectId).toBeNull();
  });

  it("ignores entities that are not staff", () => {
    expect(toActivityItem(event({ entityType: "property", entityId: MEMBER })).subjectId).toBeNull();
    expect(toActivityItem(event({ entityType: null, entityId: null })).subjectId).toBeNull();
  });

  it("describes a missing actor honestly", () => {
    expect(toActivityItem(event({ actorId: null, eventCode: "auth.login_failed" })).actor).toEqual({ kind: "anonymous" });
    expect(toActivityItem(event({ actorId: null, eventCode: "auth.rate_limited" })).actor).toEqual({ kind: "anonymous" });
    expect(toActivityItem(event({ actorId: null, eventCode: "staff.bootstrap_admin_created" })).actor).toEqual({
      kind: "system",
    });
    expect(toActivityItem(event({})).actor).toEqual({ kind: "staff", id: ADMIN });
  });
});

describe("recentActivity", () => {
  it("lists the newest first whatever order the events arrive in", () => {
    const items = recentActivity([
      event({ id: "a", occurredAt: "2026-11-04T08:00:00Z" }),
      event({ id: "c", occurredAt: "2026-11-04T10:00:00Z" }),
      event({ id: "b", occurredAt: "2026-11-04T09:00:00Z" }),
    ]);
    expect(items.map((item) => item.id)).toEqual(["c", "b", "a"]);
  });

  it("breaks timestamp ties by ID, like the API", () => {
    const at = "2026-11-04T08:00:00Z";
    const items = recentActivity([event({ id: "a", occurredAt: at }), event({ id: "b", occurredAt: at })]);
    expect(items.map((item) => item.id)).toEqual(["b", "a"]);
  });
});

describe("mentionedStaff", () => {
  it("lists each actor and affected person once", () => {
    const items = recentActivity([
      event({ id: "a" }),
      event({ id: "b", eventCode: "auth.login_succeeded", entityId: ADMIN }),
      event({ id: "c", actorId: null, eventCode: "auth.login_failed", entityType: null, entityId: null }),
    ]);
    expect(mentionedStaff(items).sort()).toEqual([ADMIN, MEMBER].sort());
  });
});
