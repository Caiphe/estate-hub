import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { FEATURED_PROPERTIES } from "@/lib/landing/content";
import type { PropertySummary } from "@/lib/landing/types";

import { PropertyCard } from "./property-card";

const [sale, rent, investment] = FEATURED_PROPERTIES;

const render = (property: PropertySummary, headingLevel?: "h2" | "h3") =>
  renderToStaticMarkup(<PropertyCard property={property} headingLevel={headingLevel} />);

/** Text a screen reader would read: tags removed, aria-hidden content dropped. */
function spoken(html: string): string {
  return html
    .replace(/<(\w+)[^>]*aria-hidden="true"[^>]*>.*?<\/\1>/g, "")
    .replace(/<[^>]+>/g, "")
    // Also folds en-ZA's non-breaking digit separators into plain spaces.
    .replace(/\s+/g, " ");
}

function facts(html: string): string[] {
  const list = html.match(/<ul\b[^>]*>(.*?)<\/ul>/)?.[1] ?? "";
  return [...list.matchAll(/<li\b[^>]*>(.*?)<\/li>/g)].map(([, item]) => spoken(item).trim());
}

describe("PropertyCard", () => {
  it.each([
    [sale, "For sale", "R 4 500 000", ["4 beds", "4 baths", "5 200 square feet"]],
    [rent, "For rent", "R 35 000 per month", ["3 beds", "3 baths", "2 100 square feet"]],
    [investment, "For investment", "R 12 000 000", ["12 000 square feet"]],
  ])("renders the reference listing %#", (property, badge, price, expectedFacts) => {
    const html = render(property);

    expect(html).toContain(`>${badge}</span>`);
    expect(spoken(html)).toContain(price);
    expect(facts(html)).toEqual(expectedFacts);
  });

  it("shows '/ month' visually for rent but reads 'per month'", () => {
    const html = render(rent);
    expect(html).toMatch(/<span aria-hidden="true"[^>]*> \/ month<\/span>/);
    expect(spoken(html)).not.toContain("/ month");
  });

  it("leaves out bedrooms and bathrooms for commercial stock", () => {
    const text = spoken(render(investment));
    expect(text).not.toMatch(/\b(beds?|baths?|undefined|NaN)\b|\b0 /);
  });

  it("omits the facts list when no facts are available", () => {
    const html = render({ ...sale, bedrooms: 0, bathrooms: undefined, floorArea: undefined });
    expect(html).not.toContain("<ul");
  });

  it("keeps the price when the title and location are long", () => {
    const html = render({ ...sale, title: "A".repeat(200), locationLabel: "B".repeat(200) });
    expect(spoken(html)).toContain("R 4 500 000");
    expect(html).toContain("line-clamp-2");
    expect(html).toContain("truncate");
  });

  it("says 'Price on request' instead of printing a malformed price", () => {
    expect(spoken(render({ ...sale, price: { amount: "4.5e5", currency: "ZAR" } }))).toContain(
      "Price on request",
    );
  });

  it("links the title to the listing and uses the requested heading level", () => {
    expect(render(sale)).toMatch(/<h3\b[^>]*><a\b[^>]*href="\/properties\/modern-duplex-lekki"[^>]*>Modern Duplex in Lekki<\/a><\/h3>/);
    expect(render(sale, "h2")).toMatch(/<h2\b/);
  });

  it("names the favorite toggle, starts unpressed, and says favorites are not saved", () => {
    const html = render(sale);
    const button = html.match(/<button\b[^>]*>/)?.[0] ?? "";

    expect(button).toContain('aria-label="Favorite Modern Duplex in Lekki"');
    expect(button).toContain('aria-pressed="false"');
    const noteId = button.match(/aria-describedby="([^"]+)"/)?.[1];
    expect(html).toContain(`id="${noteId}" hidden="">Favorites last for this visit only and are not saved.`);
    expect(render({ ...sale, isFavorite: true })).toContain('aria-pressed="true"');
  });

  it("has exactly one link and one button, neither nested in the other", () => {
    const html = render(sale);
    expect(html.match(/<a\b/g)).toHaveLength(1);
    expect(html.match(/<button\b/g)).toHaveLength(1);
    expect(html.match(/<a\b[^>]*>(.*?)<\/a>/)?.[1]).not.toMatch(/<(a|button)\b/);
    expect(html.match(/<button\b[^>]*>(.*?)<\/button>/)?.[1]).not.toMatch(/<(a|button)\b/);
  });

  it("describes the photo with the listing's alt text", () => {
    expect(render(sale)).toContain(`alt="${sale.image.alt}"`);
  });
});
