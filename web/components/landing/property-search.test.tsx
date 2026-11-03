import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DEFAULT_SEARCH } from "@/lib/landing/search";

import { PropertySearch } from "./property-search";

function render(query = {}) {
  return renderToStaticMarkup(<PropertySearch initialQuery={{ ...DEFAULT_SEARCH, ...query }} />);
}

describe("PropertySearch", () => {
  const html = render();

  it("is a labelled GET search form targeting the results route", () => {
    const form = html.match(/<form\b[^>]*>/)?.[0] ?? "";
    for (const attribute of ['role="search"', 'aria-label="Property search"', 'action="/properties"', 'method="get"']) {
      expect(form).toContain(attribute);
    }
    expect(html).toContain('id="search"');
  });

  it("offers buy, rent, and invest as one radio group with buy selected", () => {
    expect(html).toMatch(/<legend\b[^>]*>Looking to<\/legend>/);
    const radios = [...html.matchAll(/<input type="radio"[^>]*>/g)].map(([tag]) => [
      tag.match(/value="(\w+)"/)?.[1],
      tag.includes('checked=""'),
    ]);
    expect(html.match(/name="listing"/g)).toHaveLength(3);
    expect(radios).toEqual([
      ["sale", true],
      ["rent", false],
      ["investment", false],
    ]);
  });

  it("labels every field", () => {
    for (const [id, label] of [
      ["search-location", "Location"],
      ["search-type", "Property type"],
      ["search-price", "Price range"],
    ]) {
      expect(html).toMatch(new RegExp(`<label for="${id}"[^>]*>${label}</label>`));
      expect(html).toContain(`id="${id}"`);
    }
  });

  it("names the submit button 'Search properties' at every width", () => {
    const button = html.match(/<button type="submit"[^>]*>(.*?)<\/button>/)?.[1] ?? "";
    expect(button.replace(/<[^>]+>/g, "")).toBe("Search properties");
  });

  it("shows price bands for the selected mode", () => {
    const plain = (value: string) => value.replace(/\s/g, " ");
    expect(plain(html)).toContain("Under R 1 000 000");
    const rent = plain(render({ listing: "rent", price: "10k-20k" }));
    expect(rent).toContain("Under R 10 000 / month");
    expect(rent).not.toContain("Under R 1 000 000");
    expect(rent).toMatch(/<option value="10k-20k" selected="">/);
  });

  it("links popular searches for the selected mode", () => {
    expect(render({ listing: "rent" })).toContain('href="/properties?listing=rent&amp;type=villa"');
  });

  it("never nests forms or interactive elements", () => {
    expect(html.match(/<form\b/g)).toHaveLength(1);
    expect(html.match(/<button\b/g)).toHaveLength(1);
    expect(html).not.toMatch(/<(a|button|label)\b[^>]*>(?:(?!<\/\1>).)*<(a|button|select|textarea)\b/);
  });
});
