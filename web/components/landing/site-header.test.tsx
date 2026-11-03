import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { HEADER_ACTIONS, PRIMARY_NAV } from "@/lib/landing/navigation";

import { LandingPage } from "./landing-page";
import { SiteHeader } from "./site-header";

/** Visible text and destination of every link, in document order. */
function links(html: string): { text: string; href: string }[] {
  return [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/g)].map(([, href, inner]) => ({
    href: href.replaceAll("&amp;", "&"),
    text: inner.replace(/<[^>]+>/g, "").trim(),
  }));
}

describe("SiteHeader", () => {
  const html = renderToStaticMarkup(<SiteHeader />);

  it("renders a header landmark with a labelled primary navigation", () => {
    expect(html).toMatch(/^<header\b/);
    expect(html).toContain('<nav class="primary-nav" aria-label="Primary">');
  });

  it("links brand, navigation, and actions in visual order", () => {
    expect(links(html)).toEqual([
      { text: "EstateHub home", href: "/" },
      ...PRIMARY_NAV.map(({ label, href }) => ({ text: label, href })),
      { text: HEADER_ACTIONS.logIn.label, href: "/login" },
      { text: HEADER_ACTIONS.getStarted.label, href: HEADER_ACTIONS.getStarted.href },
    ]);
  });

  it("hides the house mark from assistive technology", () => {
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
  });

  it("marks only the current item", () => {
    const current = renderToStaticMarkup(<SiteHeader currentHref={PRIMARY_NAV[3].href} />);
    const marked = [...current.matchAll(/<a\b[^>]*aria-current="page"[^>]*>([^<]*)<\/a>/g)];

    expect(marked.map(([, label]) => label)).toEqual(["Properties"]);
    expect(html).not.toContain("aria-current");
  });

  it("never nests interactive elements", () => {
    for (const [, inner] of html.matchAll(/<a\b[^>]*>(.*?)<\/a>/g)) {
      expect(inner).not.toMatch(/<(a|button|input|select|textarea)\b/);
    }
    expect(html).not.toContain("<button");
  });
});

describe("LandingPage", () => {
  const html = renderToStaticMarkup(<LandingPage />);

  it("starts with a skip link that targets main", () => {
    expect(links(html)[0]).toEqual({ text: "Skip to main content", href: "#main-content" });
    expect(html).toContain('<main id="main-content" tabindex="-1"');
  });

  it("keeps the header outside main", () => {
    expect(html.indexOf("</header>")).toBeLessThan(html.indexOf("<main"));
  });
});
