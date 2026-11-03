import { describe, expect, it } from "vitest";

import { config } from "../../proxy";
import { LOGIN_PATH, WORKSPACE_PREFIXES } from "./config";

describe("proxy matcher", () => {
  it("covers the login page and every workspace prefix", () => {
    expect(config.matcher).toEqual([
      LOGIN_PATH,
      ...WORKSPACE_PREFIXES.map((prefix) => `${prefix}/:path*`),
    ]);
  });
});
