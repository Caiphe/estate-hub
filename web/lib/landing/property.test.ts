import { describe, expect, it } from "vitest";

import { formatArea, formatCount, formatPrice, hasFact, isDecimalAmount, propertyHref } from "./property";

/** en-ZA separates thousands with non-breaking spaces; compare with plain spaces. */
const plain = (value: string | null) => value?.replace(/\s/g, " ") ?? null;

describe("formatPrice", () => {
  it.each([
    ["sale", { amount: "4500000.00", currency: "ZAR" }, "R 4 500 000"],
    ["monthly rent", { amount: "35000.00", currency: "ZAR" }, "R 35 000"],
    ["investment", { amount: "12000000.00", currency: "ZAR" }, "R 12 000 000"],
    ["real cents, with a decimal comma", { amount: "1250.5", currency: "ZAR" }, "R 1 250,50"],
    ["another currency", { amount: "450000", currency: "USD" }, "$450 000"],
  ])("formats %s", (_case, price, expected) => {
    expect(plain(formatPrice(price))).toBe(expected);
  });

  it("formats beyond float precision exactly", () => {
    // As a float, 9007199254740993 rounds to …992.
    expect(plain(formatPrice({ amount: "9007199254740993.99", currency: "ZAR" }))).toBe(
      "R 9 007 199 254 740 993,99",
    );
  });

  it("keeps a price on one line", () => {
    expect(formatPrice({ amount: "4500000", currency: "ZAR" })).not.toMatch(/ /);
  });

  it.each(["", "-100", "4.5e5", "1,000", "12.345", " 100", "NaN"])("rejects the amount %j", (amount) => {
    expect(formatPrice({ amount, currency: "ZAR" })).toBeNull();
  });

  it("rejects an unknown currency", () => {
    expect(formatPrice({ amount: "100", currency: "DOLLARS" })).toBeNull();
  });
});

describe("isDecimalAmount", () => {
  it("accepts plain non-negative decimals with up to two fraction digits", () => {
    expect(["0", "7", "450000.00", "0.5"].every(isDecimalAmount)).toBe(true);
  });
});

describe("formatArea", () => {
  it("gives visible and spoken forms", () => {
    const area = formatArea({ value: 5200, unit: "sqft" });
    expect([plain(area.short), plain(area.long)]).toEqual(["5 200 sqft", "5 200 square feet"]);
    expect(formatArea({ value: 480, unit: "sqm" })).toEqual({ short: "480 m²", long: "480 square metres" });
  });
});

describe("formatCount", () => {
  it("pluralizes", () => {
    expect(formatCount(1, "bed", "beds")).toBe("1 bed");
    expect(formatCount(4, "bath", "baths")).toBe("4 baths");
  });
});

describe("hasFact", () => {
  it.each([
    [undefined, false],
    [0, false],
    [-1, false],
    [Number.NaN, false],
    [3, true],
  ])("%s → %s", (value, expected) => {
    expect(hasFact(value)).toBe(expected);
  });
});

describe("propertyHref", () => {
  it("builds the future detail route and encodes the slug", () => {
    expect(propertyHref("modern-duplex-lekki")).toBe("/properties/modern-duplex-lekki");
    expect(propertyHref("a/b?c")).toBe("/properties/a%2Fb%3Fc");
  });
});
