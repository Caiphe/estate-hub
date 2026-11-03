import { expect, test } from "@playwright/test";

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

  const image = page.getByRole("img", { name: /villa/ });
  await expect(image).toHaveAttribute("sizes", "(min-width: 60rem) 60vw, 100vw");
  await expect(page.locator('head link[rel="preload"][as="image"]')).toHaveCount(1);
});

test("hero copy stays readable and the layout holds with images blocked", async ({ page, browser }) => {
  const heroBox = await page.locator(".hero").boundingBox();

  const blocked = await browser.newPage({ viewport: page.viewportSize() });
  await blocked.route(/\/_next\/image|\.png$/, (route) => route.abort());
  await blocked.goto("/");

  const heading = blocked.getByRole("heading", { level: 1 });
  await expect(heading).toBeVisible();
  // Copy sits on the wash, never on the image, so the fallback colors are what readers see.
  const colors = await blocked.locator(".hero").evaluate((hero) => ({
    background: getComputedStyle(hero).backgroundColor,
    text: getComputedStyle(hero.querySelector("h1")!).color,
  }));
  expect(colors).toEqual({ background: "rgb(237, 246, 255)", text: "rgb(7, 22, 45)" });
  expect(await blocked.locator(".hero").boundingBox()).toEqual(heroBox);
  await blocked.close();
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
