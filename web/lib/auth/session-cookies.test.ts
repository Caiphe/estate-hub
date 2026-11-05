import { describe, expect, it } from "vitest";

import { ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME } from "./config";
import { hasSessionCookie } from "./session-cookies";

const jar = (...names: string[]) => ({
  has: (name: string) => names.includes(name),
});

describe("hasSessionCookie", () => {
  it("is true with the access cookie, or the CSRF cookie that outlives it", () => {
    expect(hasSessionCookie(jar(ACCESS_COOKIE_NAME))).toBe(true);
    expect(hasSessionCookie(jar(CSRF_COOKIE_NAME))).toBe(true);
  });

  it("is false without either", () => {
    expect(hasSessionCookie(jar())).toBe(false);
    expect(hasSessionCookie(jar("theme", "estatehub_refresh"))).toBe(false);
  });
});
