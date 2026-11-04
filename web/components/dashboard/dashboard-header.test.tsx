import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DashboardHeaderView } from "./dashboard-header";

type Options = { now?: Date | null; fullName?: string; staffAccess?: boolean; timeZone?: string };

function render({ now = null, fullName = "Ada Lovelace", staffAccess = true, timeZone = "UTC" }: Options) {
  return renderToStaticMarkup(
    <DashboardHeaderView fullName={fullName} staffAccess={staffAccess} now={now} locale="en-GB" timeZone={timeZone} />,
  );
}

/** The heading as assistive technology reads it: aria-hidden content left out, tags stripped. */
function headingName(html: string): string {
  const heading = html.match(/<h1[^>]*>(.*?)<\/h1>/)?.[1] ?? "";
  return heading
    .replace(/<span aria-hidden="true">.*?<\/span>/g, "")
    .replace(/<[^>]+>/g, "")
    .replace(/&#x27;|&quot;|&lt;|&gt;|&amp;/g, (entity) => ({ "&#x27;": "'", "&quot;": '"', "&lt;": "<", "&gt;": ">", "&amp;": "&" })[entity]!)
    .trim();
}

describe("DashboardHeaderView", () => {
  it.each([
    ["2026-11-04T04:59:00Z", "Good evening"],
    ["2026-11-04T05:00:00Z", "Good morning"],
    ["2026-11-04T11:59:00Z", "Good morning"],
    ["2026-11-04T12:00:00Z", "Good afternoon"],
    ["2026-11-04T17:59:00Z", "Good afternoon"],
    ["2026-11-04T18:00:00Z", "Good evening"],
  ])("greets by the time of day at %s", (instant, greeting) => {
    expect(headingName(render({ now: new Date(instant) }))).toBe(`${greeting}, Ada Lovelace`);
  });

  it("uses the time zone's hour and calendar day", () => {
    // 23:30 UTC on the 4th is 12:30 on the 5th in Auckland.
    const html = render({ now: new Date("2026-11-04T23:30:00Z"), timeZone: "Pacific/Auckland" });
    expect(headingName(html)).toBe("Good afternoon, Ada Lovelace");
    expect(html).toContain('<time dateTime="2026-11-05">Thu, 05 Nov 2026</time>');
  });

  it("has exactly one h1 and hides the wave emoji from assistive technology", () => {
    const html = render({ now: new Date("2026-11-04T09:00:00Z") });
    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).toContain('<span aria-hidden="true">👋</span>');
  });

  it("collapses whitespace in the name and escapes markup", () => {
    const html = render({ now: new Date("2026-11-04T09:00:00Z"), fullName: "  <b>Ada</b>   Lovelace " });
    expect(html).not.toContain("<b>");
    expect(headingName(html)).toBe("Good morning, <b>Ada</b> Lovelace");
  });

  it("before hydration greets without a time of day and leaves the date out", () => {
    const html = render({ now: null });
    expect(headingName(html)).toBe("Welcome, Ada Lovelace");
    expect(html).not.toContain("<time");
  });

  it("speaks to the team for staff readers and to the workspace for everyone else", () => {
    const now = new Date("2026-11-04T09:00:00Z");
    expect(render({ now, staffAccess: true })).toContain("what’s happening with your EstateHub team today");
    expect(render({ now, staffAccess: false })).toContain("your EstateHub workspace for today");
  });
});
