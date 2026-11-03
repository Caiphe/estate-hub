import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { HowItWorks } from "./how-it-works";

const text = (html: string) => html.replace(/<[^>]+>/g, "").trim();

describe("HowItWorks", () => {
  const html = renderToStaticMarkup(<HowItWorks />);

  it("is the #how-it-works section, labelled by its h2", () => {
    expect(html).toMatch(/^<section id="how-it-works" aria-labelledby="how-it-works-heading"/);
    expect(html).toMatch(/<h2 id="how-it-works-heading"[^>]*>Get started in 3 simple steps<\/h2>/);
    expect(html).toContain(">How it works</p>");
  });

  it("is an ordered list of three numbered steps with their descriptions", () => {
    expect(html).toMatch(/<ol role="list"/);
    const steps = [...html.matchAll(/<li\b[^>]*>(.*?)<\/li>/g)].map(([, item]) => ({
      title: text(item.match(/<h3\b[^>]*>(.*?)<\/h3>/)?.[1] ?? ""),
      description: text(item.match(/<p\b[^>]*>(.*?)<\/p>/)?.[1] ?? ""),
    }));

    expect(steps).toEqual([
      { title: "1. Create an account", description: "Sign up and set up a profile." },
      { title: "2. Discover opportunities", description: "Browse verified properties that fit your goals." },
      {
        title: "3. Invest and grow",
        description: "Invest with confidence and track portfolio performance.",
      },
    ]);
  });

  it("keeps icons decorative and the connectors out of the markup", () => {
    expect(html.match(/<svg\b/g)).toHaveLength(3);
    expect(html.match(/<svg\b[^>]*aria-hidden="true"/g)).toHaveLength(3);
    // Connectors are CSS pseudo-elements: no extra elements to hide or announce.
    expect(html.match(/<li\b[^>]*>/g)?.every((tag) => tag.includes("before:"))).toBe(true);
    expect(html).not.toContain("<hr");
    expect(html.match(/<span\b/g)).toHaveLength(3); // the icon tiles, one per step
  });

  it("counts whatever steps it is given in the heading", () => {
    const two = renderToStaticMarkup(
      <HowItWorks
        steps={[
          { id: "a", icon: "user", title: "First", description: "One." },
          { id: "b", icon: "search", title: "Second", description: "Two." },
        ]}
      />,
    );
    expect(text(two)).toContain("Get started in 2 simple steps");
    expect(two).toContain("2. Second");
  });
});
