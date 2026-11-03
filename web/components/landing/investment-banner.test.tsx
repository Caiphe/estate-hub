import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { InvestmentBanner, START_INVESTING_HREF } from "./investment-banner";

describe("InvestmentBanner", () => {
  const html = renderToStaticMarkup(<InvestmentBanner />);

  it("is the #invest section, labelled by its h2", () => {
    expect(html).toMatch(/^<section id="invest" aria-labelledby="invest-heading"/);
    expect(html).toMatch(/<h2 id="invest-heading"[^>]*>Grow your wealth through real estate<\/h2>/);
  });

  it("has one real link named 'Start investing' that opens the search in Invest mode", () => {
    const links = [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/g)];
    expect(links).toHaveLength(1);
    expect(links[0][1].replaceAll("&amp;", "&")).toBe("/?listing=investment#search");
    expect(START_INVESTING_HREF).toBe("/?listing=investment#search");
    expect(links[0][2].replace(/<[^>]+>/g, "")).toBe("Start investing");
    expect(links[0][2]).toMatch(/<svg[^>]*aria-hidden="true"/);
  });

  it("treats the photo as decoration and lazy-loads it", () => {
    const image = html.match(/<img\b[^>]*>/)?.[0] ?? "";
    expect(image).toContain('alt=""');
    expect(image).toContain('loading="lazy"');
    // `fill` positions the image inside a box the layout sizes, so it cannot shift content.
    expect(image).toContain("position:absolute");
  });

  it("puts the message before the photo in reading order", () => {
    expect(html.indexOf("<h2")).toBeLessThan(html.indexOf("<img"));
  });
});
