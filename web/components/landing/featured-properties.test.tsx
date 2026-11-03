import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { FEATURED_PROPERTIES } from "@/lib/landing/content";
import { getFeaturedProperties } from "@/lib/landing/featured";

import { FeaturedProperties, type FeaturedPropertiesState } from "./featured-properties";

const render = (state: FeaturedPropertiesState) => renderToStaticMarkup(<FeaturedProperties state={state} />);

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

function links(html: string): { text: string; href: string }[] {
  return [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/g)].map(([, href, inner]) => ({
    href,
    text: text(inner).trim(),
  }));
}

describe("FeaturedProperties", () => {
  const ready = render({ status: "ready", properties: FEATURED_PROPERTIES, isSample: true });

  it("is the #featured-properties section, labelled by an h2 under the page h1", () => {
    expect(ready).toMatch(/^<section id="featured-properties" aria-labelledby="featured-properties-heading"/);
    expect(ready).toMatch(/<h2 id="featured-properties-heading"[^>]*>Discover our handpicked properties<\/h2>/);
    expect(ready).toContain(">Featured properties</p>");
    expect(ready).not.toMatch(/<h1\b/);
    // Card titles sit one level below the section heading.
    expect(ready.match(/<h3\b/g)).toHaveLength(3);
  });

  it("renders the three fixtures in the supplied order", () => {
    const titles = [...ready.matchAll(/<h3\b[^>]*><a\b[^>]*>([^<]*)<\/a><\/h3>/g)].map(([, title]) => title);
    expect(titles).toEqual(["Modern Duplex in Lekki", "Palm Heights Apartments", "Victoria Commercial Plaza"]);
  });

  it("links 'View all properties' to the listings route, with the arrow hidden", () => {
    expect(links(ready)[0]).toEqual({ text: "View all properties", href: "/properties" });
    expect(ready).toMatch(/View all properties<svg[^>]*aria-hidden="true"/);
  });

  it("labels fixtures as sample content, and only when they are", () => {
    expect(text(ready)).toContain("Sample listings for illustration.");
    expect(text(render({ status: "ready", properties: FEATURED_PROPERTIES }))).not.toContain("Sample listings");
  });

  it("loading: announces once, keeps three card-shaped skeletons, and marks the section busy", () => {
    const html = render({ status: "loading" });
    expect(html).toContain('aria-busy="true"');
    expect(html).toMatch(/<p role="status"[^>]*>Loading featured properties…<\/p>/);
    expect(html.match(/<div aria-hidden="true"[^>]*>\s*<div class="aspect-video/g)).toHaveLength(3);
    expect(html).not.toContain("<article");
  });

  it("empty: explains and points to all properties", () => {
    const html = render({ status: "ready", properties: [] });
    expect(text(html)).toContain("No featured properties right now.");
    expect(links(html).map((link) => link.text)).toEqual(["View all properties", "Browse all properties"]);
    expect(html).not.toContain('aria-busy');
  });

  it("error: offers a retry and an alternate browse action", () => {
    const html = render({ status: "error" });
    expect(text(html)).toContain("Featured properties could not be loaded.");
    expect(links(html).slice(1)).toEqual([
      { text: "Try again", href: "/#featured-properties" },
      { text: "Browse all properties", href: "/properties" },
    ]);
    expect(links(render({ status: "error", retryHref: "/?retry=1" }))[1].href).toBe("/?retry=1");
  });
});

describe("getFeaturedProperties", () => {
  it("returns the fixtures in order, flagged as sample content", async () => {
    const { properties, isSample } = await getFeaturedProperties();
    expect(properties.map((property) => property.listingType)).toEqual(["sale", "rent", "investment"]);
    expect(isSample).toBe(true);
  });
});
