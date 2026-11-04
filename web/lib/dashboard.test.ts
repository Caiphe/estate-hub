import { describe, expect, it } from "vitest";

import { formatShare, roleAssignments } from "./dashboard";

const roles = (admin: number, manager: number, agent: number, accountant: number) => [
  { code: "administrator", label: "Administrator", count: admin },
  { code: "manager", label: "Manager", count: manager },
  { code: "agent", label: "Agent", count: agent },
  { code: "accountant", label: "Accountant", count: accountant },
];

const percent = new Intl.NumberFormat("en-GB", { style: "percent", maximumFractionDigits: 1 });

describe("roleAssignments", () => {
  it("counts assignments, which can exceed the staff total when staff hold several roles", () => {
    const result = roleAssignments(roles(10, 55, 83, 28), 149);
    expect(result.totalAssignments).toBe(176);
    expect(result.staffTotal).toBe(149);
  });

  it("takes each share of the assignments, not of the staff", () => {
    const shares = Object.fromEntries(roleAssignments(roles(10, 55, 83, 28), 149).rows.map((row) => [row.code, row.share]));
    expect(shares.agent).toBeCloseTo(83 / 176);
    expect(shares.administrator).toBeCloseTo(10 / 176);
    expect(Object.values(shares).reduce((sum, share) => sum! + share!, 0)).toBeCloseTo(1);
  });

  it("ranks the largest first and keeps role order for ties", () => {
    expect(roleAssignments(roles(10, 55, 83, 28), 149).rows.map((row) => row.code)).toEqual([
      "agent",
      "manager",
      "accountant",
      "administrator",
    ]);
    expect(roleAssignments(roles(5, 5, 5, 5), 20).rows.map((row) => row.code)).toEqual([
      "administrator",
      "manager",
      "agent",
      "accountant",
    ]);
  });

  it("sizes bars against the largest role", () => {
    const widths = roleAssignments(roles(10, 55, 80, 0), 120).rows.map((row) => row.width);
    expect(widths).toEqual([1, 55 / 80, 10 / 80, 0]);
  });

  it("has no shares and empty bars when nobody holds a role", () => {
    const result = roleAssignments(roles(0, 0, 0, 0), 3);
    expect(result.totalAssignments).toBe(0);
    for (const row of result.rows) {
      expect(row.share).toBeNull();
      expect(row.width).toBe(0);
    }
  });
});

describe("formatShare", () => {
  it("prints a percentage with at most one decimal", () => {
    expect(formatShare(83 / 176, percent)).toBe("47.2%");
    expect(formatShare(1, percent)).toBe("100%");
    expect(formatShare(0, percent)).toBe("0%");
  });

  it("prints a dash instead of NaN when there is nothing to share", () => {
    expect(formatShare(null, percent)).toBe("—");
  });
});
