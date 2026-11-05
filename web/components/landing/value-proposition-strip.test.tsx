import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VALUE_PROPOSITIONS } from "@/lib/landing/content";

import { ValuePropositionStrip } from "./value-proposition-strip";

describe("ValuePropositionStrip", () => {
  const html = renderToStaticMarkup(<ValuePropositionStrip />);

  it("renders the four propositions in order as a semantic list", () => {
    expect(html.match(/<ul\b/g)).toHaveLength(1);
    expect(html.match(/<li\b/g)).toHaveLength(4);
    expect([...html.matchAll(/<h3[^>]*>([^<]*)<\/h3>/g)].map(([, title]) => title)).toEqual([
      "Verified properties",
      "Invest with confidence",
      "Manage your portfolio",
      "Secure and reliable",
    ]);
  });

  it("pairs each title with its supporting line", () => {
    for (const item of VALUE_PROPOSITIONS) {
      expect(html).toMatch(new RegExp(`${item.title}</h3><p\\b[^>]*>${item.description.replace(".", "\\.")}</p>`));
    }
  });

  it("is a labelled section whose icons are decorative", () => {
    expect(html).toContain('aria-labelledby="value-strip-heading"');
    expect(html).toMatch(/<h2 id="value-strip-heading"[^>]*>Why EstateHub<\/h2>/);
    expect(html.match(/<svg\b/g)).toHaveLength(4);
    expect(html.match(/<svg\b[^>]*aria-hidden="true"/g)).toHaveLength(4);
  });

  it("provides one coordinated reveal with a stable stagger order", () => {
    expect(html).toMatch(/<ul[^>]*class="[^"]*value-proposition-list[^"]*"/);
    expect(html.match(/class="[^"]*value-proposition-item[^"]*"/g)).toHaveLength(4);
    expect(html).toContain("--value-delay:0ms");
    expect(html).toContain("--value-delay:315ms");
    expect(html.match(/class="value-proposition-icon"/g)).toHaveLength(4);
    expect(html.match(/class="value-proposition-copy"/g)).toHaveLength(4);
  });

  it("renders whatever typed items it is given", () => {
    const one = renderToStaticMarkup(
      <ValuePropositionStrip items={[{ id: "x", icon: "user", title: "Only one", description: "Line." }]} />,
    );
    expect(one.match(/<li\b/g)).toHaveLength(1);
    expect(one).toContain("Only one");
  });
});
