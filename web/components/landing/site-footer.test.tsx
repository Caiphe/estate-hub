import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { FOOTER_LINK_GROUPS } from "@/lib/landing/content";
import type { SocialLink } from "@/lib/landing/types";

import { SiteFooter } from "./site-footer";
import { SocialLinks } from "./social-links";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

const SAMPLE_SOCIAL: SocialLink[] = [
  { platform: "linkedin", label: "EstateHub on LinkedIn", href: "https://www.linkedin.com/company/example" },
  { platform: "youtube", label: "EstateHub on YouTube", href: "https://www.youtube.com/@example" },
];

describe("SiteFooter", () => {
  const html = renderToStaticMarkup(<SiteFooter />);

  it("is a footer landmark with a heading per group", () => {
    expect(html).toMatch(/^<footer\b/);
    const headings = [...html.matchAll(/<h2\b[^>]*>([^<]*)<\/h2>/g)].map(([, heading]) => heading);
    expect(headings).toEqual(["Platform", "Company", "Support", "Stay in the loop"]);
    for (const group of ["Platform", "Company", "Support"]) {
      const id = `footer-${group.toLowerCase()}`;
      expect(html).toContain(`<nav aria-labelledby="${id}">`);
      expect(html).toContain(`<h2 id="${id}"`);
    }
  });

  it("gives every link a real in-site destination", () => {
    const hrefs = [...html.matchAll(/<a\b[^>]*href="([^"]*)"/g)].map(([, href]) => href.replaceAll("&amp;", "&"));
    expect(hrefs).toEqual([
      "/",
      "/?listing=sale#search",
      "/?listing=rent#search",
      "/#invest",
      "/#how-it-works",
    ]);
  });

  it("shows planned destinations as text marked 'Soon', never as links", () => {
    const planned = FOOTER_LINK_GROUPS.flatMap((group) => group.links).filter((link) => "planned" in link);
    expect(planned.map((link) => link.label)).toEqual([
      "Manage portfolio",
      "Careers",
      "Contact",
      "Blog",
      "Help center",
      "FAQs",
      "Terms of service",
      "Privacy policy",
    ]);
    for (const { label } of planned) {
      expect(html).toContain(`${label}<span`);
      expect(html).not.toMatch(new RegExp(`<a\\b[^>]*>${label}</a>`));
    }
    expect(html.match(/>Soon<\/span>/g)).toHaveLength(planned.length);
  });

  it("documents every link as either a destination or planned", () => {
    for (const link of FOOTER_LINK_GROUPS.flatMap((group) => group.links)) {
      expect("href" in link ? link.href.startsWith("/") : link.planned).toBe(true);
    }
  });

  it("renders the newsletter with a labelled field, a named button, and a live region", () => {
    expect(html).toMatch(/<label for="newsletter-email"[^>]*>Email address<\/label>/);
    expect(html).toMatch(/<input[^>]*type="email"[^>]*autoComplete="email"/);
    const button = html.match(/<button type="submit"[^>]*>(.*?)<\/button>/);
    expect(text(button?.[1] ?? "")).toBe("Subscribe");
    // Disabled until hydration, so no native GET can put the address in a URL.
    expect(button?.[0]).toContain('disabled=""');
    expect(html).toMatch(/<p id="[^"]+" role="status"/);
  });

  it("shows no social links until official URLs exist", () => {
    expect(html).not.toContain("social media");
  });
});

describe("SocialLinks", () => {
  const html = renderToStaticMarkup(<SocialLinks links={SAMPLE_SOCIAL} />);

  it("names each icon link and opens it safely in a new tab", () => {
    const anchors = [...html.matchAll(/<a\b[^>]*>/g)].map(([tag]) => tag);
    expect(anchors).toHaveLength(2);
    for (const anchor of anchors) {
      expect(anchor).toContain('target="_blank"');
      expect(anchor).toContain('rel="noopener noreferrer"');
    }
    expect(anchors[0]).toContain('aria-label="EstateHub on LinkedIn (opens in a new tab)"');
    expect(html.match(/<svg\b[^>]*aria-hidden="true"/g)).toHaveLength(2);
  });

  it("renders nothing for an empty list", () => {
    expect(renderToStaticMarkup(<SocialLinks links={[]} />)).toBe("");
  });
});
