import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { roleAssignments } from "@/lib/dashboard";

import { RoleAssignmentsView } from "./role-assignments";

const percent = new Intl.NumberFormat("en-GB", { style: "percent", maximumFractionDigits: 1 });
const counts = (admin: number, manager: number, agent: number, accountant: number) => [
  { code: "administrator", label: "Administrator", count: admin },
  { code: "manager", label: "Manager", count: manager },
  { code: "agent", label: "Agent", count: agent },
  { code: "accountant", label: "Accountant", count: accountant },
];
const render = (admin: number, manager: number, agent: number, accountant: number, staff: number) =>
  renderToStaticMarkup(
    <RoleAssignmentsView data={roleAssignments(counts(admin, manager, agent, accountant), staff)} shareFormat={percent} />,
  );
const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

/** Each body row as [role, assigned, share], read from the table cells. */
function rows(html: string): string[][] {
  const body = html.match(/<tbody>(.*)<\/tbody>/)?.[1] ?? "";
  return [...body.matchAll(/<tr[^>]*>(.*?)<\/tr>/g)].map((row) =>
    [...row[1].matchAll(/<t[hd][^>]*>(.*?)<\/t[hd]>/g)].map((cell) => text(cell[1])),
  );
}

describe("RoleAssignmentsView", () => {
  it("is a captioned table with role row headers, the visible legend and text equivalent in one", () => {
    const html = render(10, 55, 83, 28, 149);
    expect(html).toContain('<caption class="sr-only">Role assignments by role, largest first</caption>');
    expect(html.match(/<th scope="row"/g)).toHaveLength(4);
    expect(html.match(/<th scope="col"/g)).toHaveLength(3);
  });

  it("lists counts and shares of assignments, largest first", () => {
    expect(rows(render(10, 55, 83, 28, 149))).toEqual([
      ["Agent", "83", "47.2%"],
      ["Manager", "55", "31.3%"],
      ["Accountant", "28", "15.9%"],
      ["Administrator", "10", "5.7%"],
    ]);
  });

  it("explains that assignments exceed the staff total", () => {
    expect(text(render(10, 55, 83, 28, 149))).toContain("176 role assignments across 149 staff members.");
  });

  it("hides the bars from assistive technology; the numbers carry the meaning", () => {
    const html = render(10, 55, 83, 28, 149);
    expect(html.match(/<span aria-hidden="true" class="mt-2 block h-2/g)).toHaveLength(4);
    expect(html).toContain('style="width:100%"');
  });

  it("shows zero assignments without NaN or empty bars pretending to be data", () => {
    const html = render(0, 0, 0, 0, 3);
    expect(text(html)).toContain("No roles are assigned yet.");
    expect(html).not.toContain("NaN");
    expect(rows(html).map((row) => row.slice(1))).toEqual([
      ["0", "—"],
      ["0", "—"],
      ["0", "—"],
      ["0", "—"],
    ]);
    expect(html.match(/style="width:0%"/g)).toHaveLength(4);
  });
});
