import { describe, expect, it } from "vitest";

import {
  characterCount,
  displayName,
  formatDay,
  formatWait,
  greetingFor,
  initials,
  isoDay,
} from "./format";

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

describe("initials", () => {
  it.each([
    ["Ada Lovelace", "AL"],
    ["Ada M. Lovelace", "AL"],
    ["  grace   hopper ", "GH"],
    ["Cher", "C"],
    ["Émile Zola", "ÉZ"],
    ["", "?"],
    ["   ", "?"],
  ])("%j becomes %j", (name, expected) => {
    expect(initials(name)).toBe(expected);
  });

  it("keeps characters outside the basic plane whole", () => {
    expect(initials("𝒜da 𝒵ola")).toBe("𝒜𝒵");
  });
});

describe("greetingFor", () => {
  it.each([
    ["2026-11-04T04:59:59Z", "Good evening"],
    ["2026-11-04T05:00:00Z", "Good morning"],
    ["2026-11-04T11:59:59Z", "Good morning"],
    ["2026-11-04T12:00:00Z", "Good afternoon"],
    ["2026-11-04T17:59:59Z", "Good afternoon"],
    ["2026-11-04T18:00:00Z", "Good evening"],
    ["2026-11-04T23:59:59Z", "Good evening"],
    ["2026-11-04T00:00:00Z", "Good evening"],
  ])("%s in UTC is %s", (instant, expected) => {
    expect(greetingFor(new Date(instant), "UTC")).toBe(expected);
  });

  it("uses the local hour, not the UTC hour", () => {
    const instant = new Date("2026-11-04T08:30:00Z");
    expect(greetingFor(instant, "Europe/London")).toBe("Good morning");
    expect(greetingFor(instant, "America/Los_Angeles")).toBe("Good evening"); // 00:30
    expect(greetingFor(instant, "Asia/Tokyo")).toBe("Good afternoon"); // 17:30
  });
});

describe("formatDay", () => {
  const instant = new Date("2026-11-04T08:30:00Z");

  it("matches the reference wording in en-GB", () => {
    expect(formatDay(instant, { locale: "en-GB", timeZone: "Europe/London" })).toBe("Wed, 04 Nov 2026");
  });

  it("follows the locale's own order", () => {
    expect(formatDay(instant, { locale: "en-US", timeZone: "America/New_York" })).toBe("Wed, Nov 04, 2026");
  });

  it("shows the day in the given time zone", () => {
    expect(formatDay(instant, { locale: "en-GB", timeZone: "America/Los_Angeles" })).toBe("Wed, 04 Nov 2026");
    expect(formatDay(new Date("2026-11-04T23:30:00Z"), { locale: "en-GB", timeZone: "Pacific/Auckland" })).toBe(
      "Thu, 05 Nov 2026",
    );
  });
});

describe("isoDay", () => {
  it("gives the local calendar day, which can differ from the UTC day", () => {
    const lateUtc = new Date("2026-11-04T23:30:00Z");
    expect(isoDay(lateUtc, "UTC")).toBe("2026-11-04");
    expect(isoDay(lateUtc, "Pacific/Auckland")).toBe("2026-11-05");
    expect(isoDay(new Date("2026-01-01T03:00:00Z"), "America/New_York")).toBe("2025-12-31");
  });
});

describe("displayName", () => {
  it("collapses whitespace and never returns an empty name", () => {
    expect(displayName("  Ada   Lovelace ")).toBe("Ada Lovelace");
    expect(displayName("   ")).toBe("there");
  });

  it("keeps markup-like text as plain text for React to escape", () => {
    expect(displayName("<b>Ada</b>")).toBe("<b>Ada</b>");
  });
});
