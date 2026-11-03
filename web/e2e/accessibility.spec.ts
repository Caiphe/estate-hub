import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

/** Runs axe and fails on any violation, listing rule, impact, and first target. */
async function expectNoViolations(page: Page, disabledRules: string[] = []) {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG_TAGS).disableRules(disabledRules).analyze();
  expect(
    violations.map((violation) => `${violation.impact} ${violation.id}: ${violation.nodes[0].target.join(" ")}`),
  ).toEqual([]);
}

test.describe("axe", () => {
  const STATES: [string, { width: number; path?: string; act?: (page: Page) => Promise<void> }][] = [
    ["desktop", { width: 1440 }],
    ["mobile", { width: 390 }],
    ["mobile menu open", { width: 390, act: (page) => page.getByRole("button", { name: "Menu" }).click() }],
    ["rent mode", { width: 1440, path: "/?listing=rent" }],
    [
      "search error",
      {
        width: 1440,
        act: async (page) => {
          await page.getByLabel("Location").fill("Lagos;");
          await page.getByRole("button", { name: "Search properties" }).click();
        },
      },
    ],
    ["newsletter error", { width: 1440, act: (page) => page.getByRole("button", { name: "Subscribe" }).click() }],
    [
      "newsletter result",
      {
        width: 1440,
        act: async (page) => {
          await page.getByLabel("Email address").fill("reader@example.com");
          await page.getByRole("button", { name: "Subscribe" }).click();
          await expect(page.getByRole("status").filter({ hasText: "hasn't been saved" })).toBeVisible();
        },
      },
    ],
  ];

  for (const [name, { width, path = "/", act }] of STATES) {
    test(`no violations: ${name}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(path);
      await act?.(page);
      await expectNoViolations(page);
    });
  }

  test("no violations: card and section states (dev preview)", async ({ page }) => {
    const response = await page.goto("/dev/property-cards");
    test.skip(response?.status() === 404, "The preview page only exists in development.");
    await page.getByRole("button", { name: "Favorite Victoria Commercial Plaza" }).click();
    // The gallery deliberately shows the featured section three times (loading, empty,
    // error), so those regions share a name; the landing page has exactly one.
    await expectNoViolations(page, ["landmark-unique"]);
  });
});

test.describe("structure", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("one h1 and no skipped heading levels", async ({ page }) => {
    const levels = await page
      .locator("h1, h2, h3, h4, h5, h6")
      .evaluateAll((headings) => headings.map((heading) => Number(heading.tagName[1])));

    expect(levels.filter((level) => level === 1)).toHaveLength(1);
    expect(levels[0]).toBe(1);
    levels.forEach((level, index) => {
      if (index > 0) expect(level).toBeLessThanOrEqual(levels[index - 1] + 1);
    });
  });

  test("landmarks are present and uniquely named", async ({ page }) => {
    await expect(page.getByRole("banner")).toHaveCount(1);
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.getByRole("contentinfo")).toHaveCount(1);
    await expect(page.getByRole("search", { name: "Property search" })).toHaveCount(1);
    await expect(page.getByRole("form", { name: "Newsletter sign-up" })).toHaveCount(1);

    const navigationNames = await page
      .getByRole("navigation")
      .evaluateAll((navs) =>
        navs.map((nav) => nav.getAttribute("aria-label") ?? document.getElementById(nav.getAttribute("aria-labelledby") ?? "")?.textContent),
      );
    expect(navigationNames).toEqual(["Primary", "Platform", "Company", "Support"]);
    for (const region of [
      /^Find, invest/,
      "Why EstateHub",
      "Discover our handpicked properties",
      "Grow your wealth through real estate",
      "Get started in 3 simple steps",
    ]) {
      await expect(page.getByRole("region", { name: region })).toHaveCount(1);
    }
  });

  test("meaningful images are described; decorative ones are silent", async ({ page }) => {
    const images = await page.locator("img").evaluateAll((elements) =>
      elements.map((image) => ({ alt: image.getAttribute("alt"), banner: !!image.closest("#invest") })),
    );
    for (const image of images) {
      expect(image.alt).not.toBeNull();
      if (image.banner) expect(image.alt).toBe("");
      else expect(image.alt!.length).toBeGreaterThan(10);
    }
    const svgs = await page.locator("main svg, header svg, footer svg").evaluateAll((elements) =>
      elements.filter((svg) => svg.getAttribute("aria-hidden") !== "true").length,
    );
    expect(svgs).toBe(0);
  });
});

/** Tabs through the whole page, recording each stop and whether its focus is visible. */
async function tabThrough(page: Page) {
  const stops: { name: string; visible: boolean; unobscured: boolean }[] = [];
  await page.locator("body").focus();
  for (let step = 0; step < 80; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      // Stop at the end of the page (the dev-only Next.js overlay sits after it).
      if (!element || element === document.body || element.tagName === "NEXTJS-PORTAL") return null;
      // Radio tabs draw their ring on the label; a card's title link draws it on the card.
      const ringHost = element.matches("input[type=radio]")
        ? element.closest("label")!
        : element.matches("article :is(h2, h3, h4) a")
          ? element.closest("article")!
          : element;
      const style = getComputedStyle(ringHost);
      const box = element.getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      return {
        name: (element.getAttribute("aria-label") ?? element.textContent ?? "").trim().slice(0, 40) || element.tagName,
        visible: style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 2,
        unobscured: !!hit && (element.contains(hit) || hit.contains(element) || ringHost.contains(hit)),
      };
    });
    if (!stop || stops.some((seen) => seen.name === stop.name && stops.length > 3 && stop.name === stops[0].name)) break;
    stops.push(stop);
  }
  return stops;
}

test.describe("keyboard", () => {
  test("every stop on the desktop page shows an unobscured focus ring", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    // The subscribe button only enables after hydration.
    await expect(page.getByRole("button", { name: "Subscribe" })).toBeEnabled();
    const stops = await tabThrough(page);

    expect(stops.length).toBeGreaterThan(30);
    expect(stops.filter((stop) => !stop.visible).map((stop) => stop.name)).toEqual([]);
    expect(stops.filter((stop) => !stop.unobscured).map((stop) => stop.name)).toEqual([]);
    expect(stops.map((stop) => stop.name)).toEqual(
      expect.arrayContaining(["Skip to main content", "Start investing", "Subscribe", "Favorite Modern Duplex in Lekki"]),
    );
  });

  test("mobile: the menu is reachable and its links take focus in order", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.keyboard.press("Tab"); // skip link
    await page.keyboard.press("Tab"); // brand
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Menu" })).toBeFocused();

    await page.keyboard.press("Enter");
    const order: string[] = [];
    for (let step = 0; step < 7; step += 1) {
      await page.keyboard.press("Tab");
      order.push(await page.evaluate(() => document.activeElement?.textContent?.trim() ?? ""));
    }
    expect(order).toEqual(["Buy", "Rent", "Invest", "Properties", "About", "Log in", "Get started"]);
  });
});

test.describe("user preferences", () => {
  test("forced colors: the selected search mode is underlined, not just filled", async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active" });
    await page.goto("/?listing=rent");
    const tab = (name: string) => page.getByRole("radio", { name }).locator("..");

    await expect(tab("Rent")).toHaveCSS("text-decoration-line", "underline");
    await expect(tab("Buy")).toHaveCSS("text-decoration-line", "none");
  });

  test("forced colors: focus rings remain outlines", async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active" });
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to main content" })).toHaveCSS("outline-style", "solid");
  });

  test("reduced motion: no transitions and no hover movement", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");

    const durations = await page
      .locator(".site *")
      .evaluateAll((elements) => [...new Set(elements.map((element) => getComputedStyle(element).transitionDuration))]);
    expect(durations.every((duration) => duration.split(",").every((part) => parseFloat(part) === 0))).toBe(true);

    const card = page.getByRole("article").first();
    await card.hover();
    await expect(card.locator("img")).toHaveCSS("transform", "none");
    await expect(page.locator(".motion-safe\\:animate-pulse")).toHaveCount(0);
  });

  test("WCAG text-spacing overrides do not clip or overflow text", async ({ page }) => {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      await page.addStyleTag({
        content: `* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
                  p { margin-bottom: 2em !important; }`,
      });
      const problems = await page.evaluate(() => {
        // Clamped titles and the truncated card location shorten by design; the full text
        // stays in the accessible name.
        const intentional = (element: Element) => element.closest(".line-clamp-2, .truncate, .sr-only, [popover]");
        const clipped = [...document.querySelectorAll("main *, header *, footer *")]
          .filter((element) => !intentional(element) && element.children.length === 0 && element.textContent?.trim())
          .filter((element) => {
            const style = getComputedStyle(element.parentElement ?? element);
            const self = element as HTMLElement;
            return style.overflow === "hidden" && self.scrollWidth > self.clientWidth + 1;
          })
          .map((element) => element.textContent?.trim().slice(0, 30));
        return { overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, clipped };
      });
      expect(problems, `at ${width}px`).toEqual({ overflow: 0, clipped: [] });
    }
  });
});
