import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { Remote } from "@/lib/use-remote";

import { SummaryValue } from "./staff-summary";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const render = (remote: Remote<number>) =>
  renderToStaticMarkup(<SummaryValue remote={remote} label="Disabled staff" onRetry={() => {}} />);

describe("SummaryValue", () => {
  it("shows the real total", () => {
    expect(text(render({ status: "ready", data: 27 }))).toBe("27");
  });

  it("shows zero as a number, not as missing data", () => {
    expect(text(render({ status: "ready", data: 0 }))).toBe("0");
  });

  it("groups large totals for reading", () => {
    expect(text(render({ status: "ready", data: 1413 }))).toMatch(/^1\D?413$/);
  });

  it("announces loading without showing a fake number", () => {
    const html = render({ status: "loading" });
    expect(text(html)).toBe("Loading");
    expect(html).toContain('aria-hidden="true"');
  });

  it.each(["error", "not_found"] as const)("offers a named retry on %s", (status) => {
    const html = render({ status });
    expect(text(html)).toBe("Unavailable Retry Disabled staff");
    expect(html).toContain('<button type="button"');
  });

  it("says access is missing on 403, with nothing to retry", () => {
    const html = render({ status: "forbidden" });
    expect(text(html)).toBe("No access");
    expect(html).not.toContain("<button");
  });
});
