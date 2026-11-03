import { describe, expect, it } from "vitest";

import { visibleNavigation } from "./navigation";

const labels = (permissions: string[]) => visibleNavigation(permissions).map((item) => item.label);

describe("visibleNavigation", () => {
  it("shows common items to everyone", () => {
    expect(labels([])).toEqual(["Dashboard", "Change password"]);
  });

  it("shows permission-gated items only with the permission", () => {
    expect(labels(["staff:read"])).toEqual(["Dashboard", "Staff", "Change password"]);
    expect(labels(["staff:read", "audit:read"])).toEqual([
      "Dashboard",
      "Staff",
      "Audit log",
      "Change password",
    ]);
  });

  it("ignores unrelated permissions", () => {
    expect(labels(["deals:read", "staff:create"])).toEqual(["Dashboard", "Change password"]);
  });
});
