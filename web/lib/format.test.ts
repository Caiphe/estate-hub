import { describe, expect, it } from "vitest";

import { characterCount, formatWait } from "./format";

describe("formatWait", () => {
  it.each([
    [null, "a few minutes"],
    [0, "a few minutes"],
    [1, "1 second"],
    [45, "45 seconds"],
    [60, "1 minute"],
    [61, "2 minutes"],
    [900, "15 minutes"],
  ])("formats %s", (seconds, expected) => {
    expect(formatWait(seconds)).toBe(expected);
  });
});

describe("characterCount", () => {
  it("counts characters, not UTF-16 code units", () => {
    expect(characterCount("🔐🔐")).toBe(2);
    expect(characterCount("pass phrase")).toBe(11);
  });
});
