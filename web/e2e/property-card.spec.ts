import { expect, type Page, test } from "@playwright/test";

/** Development-only gallery (404 in production builds); see app/dev/property-cards. */
const PREVIEW = "/dev/property-cards";

test.beforeEach(async ({ page }) => {
  // The listing detail route does not exist yet; stub it so navigation can be asserted.
  await page.route(/\/properties\/[^/?]+$/, (route) =>
    route.fulfill({ contentType: "text/html", body: "<title>Listing</title>" }),
  );
  const response = await page.goto(PREVIEW);
  test.skip(response?.status() === 404, "The preview page only exists in development.");
});

function card(page: Page, title: string | RegExp) {
  return page.getByRole("article").filter({ has: page.getByRole("heading", { name: title }) });
}

test("Enter on the title link opens the listing, and the card shows the focus ring", async ({ page }) => {
  const duplex = card(page, "Modern Duplex in Lekki");
  const link = duplex.getByRole("link", { name: "Modern Duplex in Lekki" });

  // Visual order: the favorite toggle (top right of the photo) comes before the title.
  await page.locator("h1").click();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(link).toBeFocused();
  await expect(duplex).toHaveCSS("outline-style", "solid");

  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/properties\/modern-duplex-lekki$/);
});

test("the favorite toggle comes first in tab order and toggles from the keyboard", async ({ page }) => {
  const favorite = card(page, "Modern Duplex in Lekki").getByRole("button", {
    name: "Favorite Modern Duplex in Lekki",
  });

  await page.locator("h1").click();
  await page.keyboard.press("Tab");
  await expect(favorite).toBeFocused();
  await expect(favorite).toHaveAccessibleDescription("Favorites last for this visit only and are not saved.");

  await page.keyboard.press("Space");
  await expect(favorite).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Enter");
  await expect(favorite).toHaveAttribute("aria-pressed", "false");
  await expect(page).toHaveURL(new RegExp(`${PREVIEW}$`));
});

test("a click anywhere on the card opens it, but the favorite click does not", async ({ page }) => {
  const plaza = card(page, "Victoria Commercial Plaza");

  await plaza.getByRole("button", { name: /^Favorite/ }).click();
  await expect(page).toHaveURL(new RegExp(`${PREVIEW}$`));

  // A real pointer click over the price: the stretched title link covers the card body.
  const price = (await plaza.getByText(/^R\s12\s000\s000$/).boundingBox())!;
  await page.mouse.click(price.x + price.width / 2, price.y + price.height / 2);
  await expect(page).toHaveURL(/\/properties\/victoria-commercial-plaza$/);
});

test("long text clamps without hiding the price", async ({ page }) => {
  const long = card(page, /^Expansive Five-Bedroom/);
  const heading = long.getByRole("heading");

  await expect(long.getByText(/^R\s4\s500\s000$/)).toBeVisible();
  const clamped = await heading.evaluate((element) => element.scrollHeight > element.clientHeight);
  expect(clamped).toBe(true);
});

test("a failed photo falls back to a labelled placeholder", async ({ page }) => {
  const broken = card(page, "Listing with a Missing Photo");

  await expect(broken.getByRole("img", { name: "Front of the listing" })).toContainText("Photo unavailable");
});

test("cards in a row share one height and one image height", async ({ page }) => {
  const sizes = await page.getByRole("article").evaluateAll((articles) =>
    articles.slice(0, 3).map((article) => ({
      card: Math.round(article.getBoundingClientRect().height),
      image: Math.round(article.firstElementChild!.getBoundingClientRect().height),
    })),
  );

  expect(new Set(sizes.map((size) => size.card)).size).toBe(1);
  expect(new Set(sizes.map((size) => size.image)).size).toBe(1);
});
