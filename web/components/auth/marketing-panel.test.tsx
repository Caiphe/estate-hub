import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MarketingPanel, SIGN_IN_HIGHLIGHTS } from "./marketing-panel";

describe("MarketingPanel", () => {
  const html = renderToStaticMarkup(<MarketingPanel />);

  it("is a complementary landmark labelled by its statement, with no headings", () => {
    expect(html.match(/<aside aria-labelledby="sign-in-statement"/g)).toHaveLength(1);
    expect(html).toMatch(/<p id="sign-in-statement"[^>]*>Your gateway to smarter <span[^>]*>real estate<\/span><\/p>/);
    expect(html).not.toMatch(/<h[1-6]\b/);
  });

  it("emphasizes real estate in sunset gold", () => {
    expect(html).toMatch(/<span class="text-sunset">real estate<\/span>/);
  });

  it("shows the brand, linking home", () => {
    expect(html).toMatch(/<a [^>]*href="\/"[^>]*>.*EstateHub.*<\/a>/);
  });

  it("carries the supporting copy", () => {
    expect(html).toContain("Buy, rent, invest, and manage properties all in one place.");
  });

  it("renders the three value points in order as a semantic list", () => {
    expect(html.match(/<ul\b/g)).toHaveLength(1);
    expect([...html.matchAll(/<li\b[^>]*>.*?<\/li>/g)].map(([li]) => li.replace(/<[^>]+>/g, ""))).toEqual([
      "Discover verified properties",
      "Invest and grow your wealth",
      "Manage your portfolio securely",
    ]);
    expect(SIGN_IN_HIGHLIGHTS.map((item) => item.icon)).toEqual(["chart", "layers", "shield"]);
  });

  it("keeps the photograph and every icon silent", () => {
    expect(html.match(/<img\b/g)).toHaveLength(1);
    expect(html).toMatch(/<img [^>]*alt=""/);
    const svgs = html.match(/<svg\b[^>]*>/g) ?? [];
    expect(svgs).toHaveLength(4); // brand mark plus three value-point icons
    for (const svg of svgs) expect(svg).toContain('aria-hidden="true"');
  });

  it("offers no fake carousel controls", () => {
    expect(html).not.toMatch(/<button\b|role="tab"|carousel/i);
  });

  it("renders whatever value points it is given", () => {
    const one = renderToStaticMarkup(
      <MarketingPanel highlights={[{ id: "x", icon: "user", label: "Only one" }]} />,
    );
    expect(one.match(/<li\b/g)).toHaveLength(1);
    expect(one).toContain("Only one");
  });
});
