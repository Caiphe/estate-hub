import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { HEADER_ACTIONS, PRIMARY_NAV } from "@/lib/landing/navigation";

import { LandingPage } from "./landing-page";
import { SiteHeader } from "./site-header";

const text = (html: string) => html.replace(/<[^>]+>/g, "").trim();

/** Visible text and destination of every link, in document order. */
function links(html: string): { text: string; href: string }[] {
  return [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/g)].map(
    ([, href, inner]) => ({
      href: href.replaceAll("&amp;", "&"),
      text: text(inner),
    }),
  );
}

const DESKTOP_ORDER = [
  { text: "EstateHub home", href: "/" },
  ...PRIMARY_NAV.map(({ label, href }) => ({ text: label, href })),
  { text: HEADER_ACTIONS.logIn.label, href: "/login" },
  {
    text: HEADER_ACTIONS.getStarted.label,
    href: HEADER_ACTIONS.getStarted.href,
  },
];

describe("SiteHeader", () => {
  const html = renderToStaticMarkup(<SiteHeader />);

  it("renders a header landmark with primary navigation for desktop and the menu", () => {
    expect(html).toMatch(/^<header\b/);
    expect(html.match(/<nav aria-label="Primary"/g)).toHaveLength(2);
  });

  it("links brand, navigation, and actions in visual order", () => {
    expect(links(html).slice(0, DESKTOP_ORDER.length)).toEqual(DESKTOP_ORDER);
  });

  it("repeats navigation and actions in the mobile menu, opened by a named button", () => {
    const button = html.match(/<button\b[^>]*>(.*?)<\/button>/);
    expect(button?.[0]).toContain('popoverTarget="site-menu"');
    expect(text(button?.[1] ?? "")).toBe("Menu");
    expect(html).toMatch(/<div id="site-menu" popover="auto"/);
    expect(links(html).slice(DESKTOP_ORDER.length)).toEqual(
      DESKTOP_ORDER.slice(1),
    );
  });

  it("hides the house mark from assistive technology", () => {
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
  });

  it("marks only the current item, in both navigations", () => {
    const current = renderToStaticMarkup(
      <SiteHeader currentHref={PRIMARY_NAV[3].href} />,
    );
    const marked = [
      ...current.matchAll(/<a\b[^>]*aria-current="page"[^>]*>([^<]*)<\/a>/g),
    ];

    expect(marked.map(([, label]) => label)).toEqual([
      "Properties",
      "Properties",
    ]);
    expect(html).not.toContain("aria-current");
  });

  it("never nests interactive elements", () => {
    for (const [, inner] of html.matchAll(
      /<(?:a|button)\b[^>]*>(.*?)<\/(?:a|button)>/g,
    )) {
      expect(inner).not.toMatch(/<(a|button|input|select|textarea)\b/);
    }
  });
});

describe("SiteHeader for a signed-in visitor", () => {
  const html = renderToStaticMarkup(<SiteHeader signedIn />);
  const account = {
    text: HEADER_ACTIONS.account.label,
    href: HEADER_ACTIONS.account.href,
  };

  it("drops Log in everywhere and offers a named profile icon", () => {
    expect(links(html).map((link) => link.href)).not.toContain("/login");
    expect(links(html).filter((link) => link.href === account.href)).toEqual([
      account,
    ]);
    const tag = html.match(/<a\b[^>]*href="\/dashboard"[^>]*>/)?.[0] ?? "";
    expect(tag).toContain('title="Your account"');
  });

  it("keeps the icon visible at every width, after the desktop actions", () => {
    const icon = html.indexOf('href="/dashboard"');
    expect(html.slice(html.lastIndexOf("<a", icon), icon)).not.toMatch(
      /hidden/,
    );
    expect(
      html.indexOf(
        `href="${HEADER_ACTIONS.getStarted.href.replaceAll("&", "&amp;")}"`,
      ),
    ).toBeLessThan(icon);
  });
});

describe("LandingPage", () => {
  const html = renderToStaticMarkup(<LandingPage />);

  it("starts with a skip link that targets main", () => {
    expect(links(html)[0]).toEqual({
      text: "Skip to main content",
      href: "#main-content",
    });
    expect(html).toMatch(/<main id="main-content" tabindex="-1"/);
  });

  it("passes the signed-in state to the header", () => {
    expect(renderToStaticMarkup(<LandingPage signedIn />)).toContain(
      'title="Your account"',
    );
    expect(html).not.toContain('title="Your account"');
  });

  it("keeps the header outside main", () => {
    expect(html.indexOf("</header>")).toBeLessThan(html.indexOf("<main"));
  });
});
