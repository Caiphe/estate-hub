import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AuditEvent } from "@/lib/api/staff";
import { recentActivity } from "@/lib/audit-events";

import { RecentActivityView } from "./recent-activity";

const ADMIN = "11111111-1111-4111-8111-111111111111";
const MEMBER = "22222222-2222-4222-8222-222222222222";

function event(overrides: Partial<AuditEvent>): AuditEvent {
  return {
    id: "e-1",
    eventCode: "staff.disabled",
    actorId: ADMIN,
    entityType: "user",
    entityId: MEMBER,
    occurredAt: "2026-11-04T17:05:00Z",
    requestId: "req-1",
    metadata: { revoked_sessions: 2, client_ip_prefix: "203.0.113.0/24" },
    ...overrides,
  };
}

const render = (events: AuditEvent[], names: Array<[string, string]> = []) =>
  renderToStaticMarkup(
    <RecentActivityView items={recentActivity(events)} names={new Map(names)} locale="en-GB" timeZone="Europe/London" />,
  );
const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

describe("RecentActivityView", () => {
  it("shows the readable event, who acted, who was affected, and the local time", () => {
    const html = render([event({})], [
      [ADMIN, "Ada Admin"],
      [MEMBER, "Mo Member"],
    ]);
    expect(text(html)).toContain("Account disabled By Ada Admin · Affected: Mo Member");
    expect(html).toContain('<time dateTime="2026-11-04T17:05:00Z"');
    expect(text(html)).toContain("4 Nov 2026, 17:05");
  });

  it("keeps the canonical event code available", () => {
    expect(text(render([event({})]))).toContain("Event code staff.disabled");
  });

  it("never renders metadata or request IDs", () => {
    const html = render([event({})], [[ADMIN, "Ada Admin"]]);
    expect(html).not.toMatch(/203\.0\.113|revoked|req-1/);
  });

  it("describes missing actors and unresolved names honestly", () => {
    const html = render([
      event({ id: "a", actorId: null, eventCode: "auth.login_failed", entityType: null, entityId: null }),
      event({ id: "b", actorId: null, eventCode: "staff.bootstrap_admin_created", occurredAt: "2026-11-04T16:00:00Z" }),
      event({ id: "c", occurredAt: "2026-11-04T15:00:00Z" }),
    ]);
    expect(text(html)).toContain("Sign-in failed Not signed in");
    expect(text(html)).toContain("First administrator created By the system");
    expect(text(html)).toContain("By an unknown staff member · Affected: an unknown staff member");
  });

  it("is an ordered list, newest first", () => {
    const html = render([
      event({ id: "old", eventCode: "auth.logout", occurredAt: "2026-11-04T08:00:00Z" }),
      event({ id: "new", eventCode: "auth.login_succeeded", occurredAt: "2026-11-04T09:00:00Z" }),
    ]);
    expect(html.startsWith("<ol")).toBe(true);
    expect(text(html).indexOf("Signed in")).toBeLessThan(text(html).indexOf("Signed out"));
  });

  it("says when there is no activity", () => {
    expect(text(render([]))).toBe("No staff activity has been recorded yet.");
  });
});
