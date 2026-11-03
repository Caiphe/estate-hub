import { describe, expect, it } from "vitest";

import {
  buildSearchUrl,
  DEFAULT_SEARCH,
  LOCATION_MAX,
  parseSearchQuery,
  PROPERTY_TYPES,
  validateLocation,
} from "./search";

describe("parseSearchQuery", () => {
  it("defaults an empty query to buy, any location, type, and price", () => {
    expect(parseSearchQuery(new URLSearchParams())).toEqual(DEFAULT_SEARCH);
    expect(parseSearchQuery({})).toEqual(DEFAULT_SEARCH);
  });

  it("reads every recognized value and trims the location", () => {
    const params = new URLSearchParams("listing=rent&location=%20Ikoyi%2C%20Lagos%20&type=apartment&price=10k-20k");

    expect(parseSearchQuery(params)).toEqual({
      listing: "rent",
      location: "Ikoyi, Lagos",
      type: "apartment",
      price: "10k-20k",
    });
  });

  it.each([
    ["listing=lease", { listing: "sale" }],
    ["type=castle", { type: "any" }],
    ["price=free", { price: "any" }],
    // A sale band is meaningless for monthly rent.
    ["listing=rent&price=3m-5m", { listing: "rent", price: "any" }],
    ["location=<script>", { location: "" }],
    [`location=${"a".repeat(LOCATION_MAX + 1)}`, { location: "" }],
  ])("drops malformed input: %s", (query, expected) => {
    expect(parseSearchQuery(new URLSearchParams(query))).toEqual({ ...DEFAULT_SEARCH, ...expected });
  });

  it("uses the first value of a repeated parameter", () => {
    expect(parseSearchQuery({ listing: ["investment", "rent"], type: ["villa"] })).toMatchObject({
      listing: "investment",
      type: "villa",
    });
  });
});

describe("validateLocation", () => {
  it.each(["", "Lekki", "Victoria Island, Lagos", "Saint-Étienne", "O'Fallon", "Kraków 31"])(
    "accepts %j",
    (location) => {
      expect(validateLocation(location)).toBeNull();
    },
  );

  it("limits length by characters, not UTF-16 units", () => {
    expect(validateLocation("é".repeat(LOCATION_MAX))).toBeNull();
    expect(validateLocation("é".repeat(LOCATION_MAX + 1))).toBe(`Use at most ${LOCATION_MAX} characters.`);
  });

  it.each(["Lagos;", "<b>", "a/b", "50%"])("rejects %j", (location) => {
    expect(validateLocation(location)).toMatch(/^Use letters/);
  });
});

describe("buildSearchUrl", () => {
  it("always includes the listing and omits 'any' values", () => {
    expect(buildSearchUrl()).toBe("/properties?listing=sale");
    expect(buildSearchUrl({ location: "  ", type: "any", price: "any" })).toBe("/properties?listing=sale");
  });

  it("encodes each field", () => {
    expect(
      buildSearchUrl({ listing: "investment", location: " Victoria Island ", type: "commercial", price: "over-5m" }),
    ).toBe("/properties?listing=investment&location=Victoria+Island&type=commercial&price=over-5m");
  });

  it("drops a price band that does not belong to the listing mode", () => {
    expect(buildSearchUrl({ listing: "rent", price: "3m-5m" })).toBe("/properties?listing=rent");
  });

  it("builds a popular-search URL for every property type", () => {
    expect(PROPERTY_TYPES.map(({ value }) => buildSearchUrl({ listing: "rent", type: value }))).toEqual([
      "/properties?listing=rent&type=apartment",
      "/properties?listing=rent&type=house",
      "/properties?listing=rent&type=villa",
      "/properties?listing=rent&type=commercial",
      "/properties?listing=rent&type=land",
    ]);
  });

  it("round-trips through the parser", () => {
    const query = { listing: "rent", location: "Lekki", type: "house", price: "20k-40k" } as const;
    expect(parseSearchQuery(new URL(buildSearchUrl(query), "http://x").searchParams)).toEqual(query);
  });
});
