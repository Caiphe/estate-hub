import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LANDING_ASSETS } from "@/lib/landing/assets";

import { HeroSection } from "./hero-section";

const SIZES = "(min-width: 64rem) 60vw, 100vw";

describe("HeroSection", () => {
  const html = renderToStaticMarkup(<HeroSection />);

  it("is a section labelled by its single h1", () => {
    expect(html).toMatch(/<section aria-labelledby="hero-heading"/);
    expect(html.match(/<h1\b/g)).toHaveLength(1);
    expect(html).toMatch(/<h1 id="hero-heading"/);
  });

  it("emphasizes only the EstateHub name in the headline", () => {
    const heading = html.match(/<h1\b[^>]*>(.*?)<\/h1>/)?.[1] ?? "";

    expect(heading.replace(/<[^>]+>/g, "")).toBe("Find, invest, and manage properties with EstateHub");
    expect([...heading.matchAll(/<span class="text-brand">([^<]*)<\/span>/g)].map(([, inner]) => inner)).toEqual([
      "EstateHub",
    ]);
    expect(heading.match(/text-brand/g)).toHaveLength(1);
    expect(heading).not.toContain("<br");
  });

  it("renders a responsive, preloaded image with the manifest alt text", () => {
    const image = html.match(/<img\b[^>]*>/)?.[0] ?? "";

    expect(image).toContain(`alt="${LANDING_ASSETS.hero.alt}"`);
    expect(image).toContain(`sizes="${SIZES}"`);
    expect(image).not.toContain('loading="lazy"');
    // `preload` emits a responsive <link rel="preload">, which React hoists into <head>.
    expect(html).toContain(`imageSizes="${SIZES}"`);
    expect(html).toMatch(/<link rel="preload" as="image"/);
  });

  it("places copy before the photograph in reading order", () => {
    expect(html.indexOf("<h1")).toBeLessThan(html.indexOf("<img"));
  });

  it("has no search controls of its own", () => {
    expect(html).not.toMatch(/<(form|input|select|button)\b/);
  });
});
