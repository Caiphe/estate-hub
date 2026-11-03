import { describe, expect, it } from "vitest";

import { isWorkspacePath, loginPathFor, postLoginPath, safeNextPath } from "./redirect";

describe("safeNextPath", () => {
  it.each([
    ["/dashboard", "/dashboard"],
    ["/dashboard/", "/dashboard/"],
    ["/account/password", "/account/password"],
    ["/dashboard?tab=recent#top", "/dashboard?tab=recent#top"],
    ["/dashboard/../account/password", "/account/password"],
  ])("accepts the workspace path %s", (value, expected) => {
    expect(safeNextPath(value)).toBe(expected);
  });

  it.each([
    ["absolute URL", "https://evil.example/dashboard"],
    ["absolute http URL", "http://localhost:3001/dashboard"],
    ["protocol-relative URL", "//evil.example/dashboard"],
    ["backslash protocol-relative", "/\\evil.example"],
    ["leading backslashes", "\\\\evil.example"],
    ["javascript URL", "javascript:alert(1)"],
    ["data URL", "data:text/html,hi"],
    ["relative path", "dashboard"],
    ["encoded slashes stay a path", "/%2F%2Fevil.example"],
    ["tab character", "/\t/evil.example"],
    ["newline", "/dashboard\nLocation: https://evil.example"],
    ["path outside the workspace", "/login"],
    ["API path", "/api/v1/auth/logout"],
    ["prefix lookalike", "/dashboards"],
    ["dot segments escaping the workspace", "/dashboard/../login"],
    ["empty", ""],
    ["too long", `/dashboard/${"a".repeat(2100)}`],
  ])("rejects %s", (_, value) => {
    expect(safeNextPath(value)).toBeNull();
  });

  it("rejects missing values", () => {
    expect(safeNextPath(null)).toBeNull();
    expect(safeNextPath(undefined)).toBeNull();
  });
});

describe("redirect helpers", () => {
  it("falls back to the dashboard", () => {
    expect(postLoginPath("https://evil.example")).toBe("/dashboard");
    expect(postLoginPath("/account/password")).toBe("/account/password");
  });

  it("builds login URLs only with safe next values", () => {
    expect(loginPathFor("/account/password?x=1")).toBe("/login?next=%2Faccount%2Fpassword%3Fx%3D1");
    expect(loginPathFor("//evil.example")).toBe("/login");
  });

  it("recognizes workspace paths", () => {
    expect(isWorkspacePath("/dashboard")).toBe(true);
    expect(isWorkspacePath("/account/password")).toBe(true);
    expect(isWorkspacePath("/")).toBe(false);
    expect(isWorkspacePath("/accounting")).toBe(false);
  });
});
