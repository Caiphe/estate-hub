import { describe, expect, it } from "vitest";

import { NAVIGATION, isActive, staffSearchHref, visibleNavigation } from "./navigation";

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

  it("gives every item its own icon", () => {
    const icons = NAVIGATION.map((item) => item.icon);
    expect(new Set(icons).size).toBe(icons.length);
  });
});

describe("isActive", () => {
  it("matches the page itself and nested routes", () => {
    expect(isActive("/staff", "/staff")).toBe(true);
    expect(isActive("/staff/new", "/staff")).toBe(true);
    expect(isActive("/staff/0b5e0f6c-1c2d-4e5f-8a9b-0c1d2e3f4a5b", "/staff")).toBe(true);
  });

  it("does not match siblings that only share a prefix", () => {
    expect(isActive("/staffing", "/staff")).toBe(false);
    expect(isActive("/dashboard", "/staff")).toBe(false);
    expect(isActive("/account", "/account/password")).toBe(false);
  });
});

describe("staffSearchHref", () => {
  it("filters the staff directory by the trimmed term", () => {
    expect(staffSearchHref("  ada  ")).toBe("/staff?q=ada");
    expect(staffSearchHref("ada@example.com")).toBe("/staff?q=ada%40example.com");
    expect(staffSearchHref("Ada & Grace?")).toBe("/staff?q=Ada+%26+Grace%3F");
  });

  it("opens the unfiltered directory for an empty term", () => {
    expect(staffSearchHref("")).toBe("/staff");
    expect(staffSearchHref("   ")).toBe("/staff");
  });

  it("caps the term at the API's 100-character limit", () => {
    const q = new URLSearchParams(staffSearchHref("a".repeat(150)).split("?")[1]).get("q");
    expect(q).toHaveLength(100);
  });
});
