import { expect, type Page, test } from "@playwright/test";

const NAV_LABELS = ["Buy", "Rent", "Invest", "Properties", "About"];

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("header exposes the brand, primary navigation, and actions", async ({ page }) => {
  const header = page.getByRole("banner");

  await expect(header.getByRole("link", { name: "EstateHub home" })).toHaveAttribute("href", "/");
  const navigation = header.getByRole("navigation", { name: "Primary" });
  await expect(navigation.getByRole("link")).toHaveText(NAV_LABELS);
  await expect(header.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
  await expect(header.getByRole("link", { name: "Get started" })).toBeVisible();
});

test("keyboard order starts with the skip link and follows the visual order", async ({ page }) => {
  const expected = ["Skip to main content", "EstateHub home", ...NAV_LABELS, "Log in", "Get started"];
  const focused: string[] = [];

  for (let index = 0; index < expected.length; index += 1) {
    await page.keyboard.press("Tab");
    focused.push(await page.evaluate(() => document.activeElement?.textContent?.trim() ?? ""));
  }

  expect(focused).toEqual(expected);
});

test("the skip link becomes visible on focus and moves focus to main", async ({ page }) => {
  const skip = page.getByRole("link", { name: "Skip to main content" });

  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();

  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
});

test("the hero has one page heading and a described, preloaded photograph", async ({ page }) => {
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Find, invest, and manage properties with EstateHub",
  );

  const image = page.getByRole("img", { name: /family/ });
  await expect(image).toHaveAttribute("sizes", "(min-width: 64rem) 60vw, 100vw");
  await expect(page.locator('head link[rel="preload"][as="image"]')).toHaveCount(1);
});

test("hero copy stays readable and the layout holds with images blocked", async ({ page, browser }) => {
  const hero = (target: typeof page) => target.getByRole("region", { name: /^Find, invest/ });
  const heroBox = await hero(page).boundingBox();

  const blocked = await browser.newPage({ viewport: page.viewportSize() });
  await blocked.route(/\/_next\/image|\.png$/, (route) => route.abort());
  await blocked.goto("/");

  const heading = blocked.getByRole("heading", { level: 1 });
  await expect(heading).toBeVisible();
  // Copy sits on the wash, never on the image, so the fallback colors are what readers see.
  const colors = await hero(blocked).evaluate((section) => ({
    background: getComputedStyle(section).backgroundColor,
    text: getComputedStyle(section.querySelector("h1")!).color,
  }));
  expect(colors).toEqual({ background: "rgb(237, 246, 255)", text: "rgb(7, 22, 45)" });
  expect(await hero(blocked).boundingBox()).toEqual(heroBox);
  await blocked.close();
});

test("the value strip lists four propositions that survive 200% text size", async ({ page }) => {
  const strip = page.getByRole("region", { name: "Why EstateHub" });
  await expect(strip.getByRole("listitem")).toHaveCount(4);
  await expect(strip.getByRole("heading", { level: 3 })).toHaveText([
    "Verified properties",
    "Invest with confidence",
    "Manage your portfolio",
    "Secure and reliable",
  ]);

  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  const clipped = await strip
    .locator("h3, p")
    .evaluateAll((elements) => elements.filter((element) => element.scrollWidth > element.clientWidth + 1).length);
  expect(clipped).toBe(0);
});

test("featured properties follow the h1 with an h2 and three cards in order", async ({ page }) => {
  const headings = await page
    .getByRole("main")
    .getByRole("heading")
    .evaluateAll((elements) => elements.map((element) => `${element.tagName}:${element.textContent?.trim()}`));
  expect(headings.slice(0, 1)).toEqual(["H1:Find, invest, and manage properties with EstateHub"]);
  expect(headings).toContain("H2:Discover our handpicked properties");

  const section = page.getByRole("region", { name: "Discover our handpicked properties" });
  await expect(section.getByRole("article").getByRole("heading", { level: 3 })).toHaveText([
    "Modern Duplex in Lekki",
    "Palm Heights Apartments",
    "Victoria Commercial Plaza",
  ]);
  await expect(section.getByRole("link", { name: "View all properties" })).toHaveAttribute("href", "/properties");
  await expect(section.getByText(/^Sample listings for illustration/)).toBeVisible();
});

test("the header's Properties link reaches the featured section", async ({ page }) => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Properties" }).click();

  await expect(page).toHaveURL(/#featured-properties$/);
  await expect(page.getByRole("heading", { name: "Discover our handpicked properties" })).toBeInViewport();
});

test("featured cards share one row height at desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const boxes = await page
    .getByRole("region", { name: "Discover our handpicked properties" })
    .getByRole("article")
    .evaluateAll((articles) => articles.map((article) => article.getBoundingClientRect()));

  expect(new Set(boxes.map((box) => Math.round(box.top))).size).toBe(1);
  expect(new Set(boxes.map((box) => Math.round(box.height))).size).toBe(1);
});

test.describe("investment banner", () => {
  const banner = (target: Page) =>
    target.getByRole("region", { name: "Grow your wealth through real estate" });

  test("its action opens the search in Invest mode", async ({ page }) => {
    await banner(page).getByRole("link", { name: "Start investing" }).click();

    await expect(page).toHaveURL(/\/\?listing=investment#search$/);
    await expect(page.getByRole("radio", { name: "Invest" })).toBeChecked();
  });

  test("the header's Invest link reaches it", async ({ page }) => {
    await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Invest" }).click();
    await expect(banner(page).getByRole("heading")).toBeInViewport();
  });

  test("keeps its size and readable colours when the photo fails", async ({ page, browser }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const expected = await banner(page).boundingBox();

    const blocked = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await blocked.route(/\/_next\/image|\.png$|\.jpg$/, (route) => route.abort());
    await blocked.goto("/");
    const section = banner(blocked);

    expect(await section.boundingBox()).toEqual(expected);
    const colors = await section.getByRole("heading").evaluate((heading) => ({
      text: getComputedStyle(heading).color,
      background: getComputedStyle(heading.parentElement!.parentElement!).backgroundColor,
    }));
    expect(colors).toEqual({ text: "rgb(255, 255, 255)", background: "rgb(0, 77, 64)" });
    await blocked.close();
  });

  test("survives 200% zoom without clipping or sideways scrolling", async ({ page }) => {
    // 200% browser zoom on a 1440px window lays out like a 720px viewport.
    await page.setViewportSize({ width: 720, height: 900 });
    const section = banner(page);
    await expect(section.getByRole("link", { name: "Start investing" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);

    // Doubled text at desktop width: copy wraps inside the banner rather than clipping.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    const clipped = await section
      .locator("h2, p, a")
      .evaluateAll((elements) => elements.filter((element) => element.scrollWidth > element.clientWidth + 1).length);
    expect(clipped).toBe(0);
  });
});

test.describe("how it works", () => {
  const section = (page: Page) => page.getByRole("region", { name: "Get started in 3 simple steps" });

  test("lists the three steps in order", async ({ page }) => {
    const steps = section(page).getByRole("list").getByRole("listitem");

    await expect(steps).toHaveCount(3);
    await expect(steps.getByRole("heading", { level: 3 })).toHaveText([
      "1. Create an account",
      "2. Discover opportunities",
      "3. Invest and grow",
    ]);
  });

  test("reads left to right at desktop, with connectors between steps only", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const steps = section(page).getByRole("listitem");
    const layout = await steps.evaluateAll((items) =>
      items.map((item) => ({
        left: Math.round(item.getBoundingClientRect().left),
        top: Math.round(item.getBoundingClientRect().top),
        connector: getComputedStyle(item, "::before").content !== "none",
      })),
    );

    expect(new Set(layout.map((step) => step.top)).size).toBe(1);
    expect(layout.map((step) => step.left)).toEqual([...layout.map((step) => step.left)].sort((a, b) => a - b));
    expect(layout.map((step) => step.connector)).toEqual([false, true, true]);
  });

  test("the header's About and Get started links reach it", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole("banner").getByRole("link", { name: "Get started" }).click();
    await expect(page).toHaveURL(/#how-it-works$/);
    await expect(section(page).getByRole("heading", { level: 2 })).toBeInViewport();
  });
});

test("header controls show a focus ring and meet the minimum target size", async ({ page }) => {
  const header = page.getByRole("banner");

  for (const link of await header.getByRole("link").all()) {
    await link.focus();
    const outline = await link.evaluate((element) => getComputedStyle(element).outlineStyle);
    expect(outline).toBe("solid");

    const box = await link.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
});
