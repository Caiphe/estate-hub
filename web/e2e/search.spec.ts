import { expect, type Page, test } from "@playwright/test";

/** The results route does not exist yet; answer it with a stub so the URL can be checked. */
async function stubResults(page: Page): Promise<void> {
  await page.route(/\/properties(\?|$)/, (route) =>
    route.fulfill({ contentType: "text/html", body: "<title>Results</title>" }),
  );
}

function searchForm(page: Page) {
  return page.getByRole("search", { name: "Property search" });
}

test.beforeEach(async ({ page }) => {
  await stubResults(page);
});

test("arrow keys switch mode, price bands, and popular links", async ({ page }) => {
  await page.goto("/");
  const form = searchForm(page);

  await form.getByRole("radio", { name: "Buy" }).focus();
  await expect(form.getByRole("radio", { name: "Buy" })).toBeChecked();
  await page.keyboard.press("ArrowRight");

  await expect(form.getByRole("radio", { name: "Rent" })).toBeChecked();
  await expect(form.getByLabel("Price range").locator("option")).toContainText([
    "Any price",
    /^Under R\s10\s000 \/ month$/,
  ]);
  await expect(page.getByRole("link", { name: "Villas" })).toHaveAttribute(
    "href",
    "/properties?listing=rent&type=villa",
  );
});

test("keyboard order runs mode, fields, submit, then popular searches", async ({ page }) => {
  await page.goto("/");
  await searchForm(page).getByRole("radio", { name: "Buy" }).focus();

  const order: string[] = [];
  for (let step = 0; step < 5; step += 1) {
    await page.keyboard.press("Tab");
    order.push(
      await page.evaluate(() => {
        const element = document.activeElement as HTMLElement;
        return element.getAttribute("aria-label") ?? element.id ?? "";
      }),
    );
  }
  expect(order.slice(0, 3)).toEqual(["search-location", "search-type", "search-price"]);
  await expect(page.getByRole("link", { name: "Apartments", exact: true })).toBeFocused();
});

test("an empty search submits the default query", async ({ page }) => {
  await page.goto("/");
  await searchForm(page).getByRole("button", { name: "Search properties" }).click();

  await expect(page).toHaveURL(/\/properties\?listing=sale$/);
});

test("a full search builds a clean, typed URL", async ({ page }) => {
  await page.goto("/");
  const form = searchForm(page);

  await form.getByRole("radio", { name: "Invest" }).check();
  await form.getByLabel("Location").fill("  Victoria Island ");
  await form.getByLabel("Property type").selectOption("commercial");
  await form.getByLabel("Price range").selectOption("over-5m");
  await form.getByLabel("Location").press("Enter");

  await expect(page).toHaveURL(
    /\/properties\?listing=investment&location=Victoria\+Island&type=commercial&price=over-5m$/,
  );
});

test("an invalid location is explained and blocks submission", async ({ page }) => {
  await page.goto("/");
  const form = searchForm(page);
  const location = form.getByLabel("Location");

  await location.fill("Lagos; DROP");
  await form.getByRole("button", { name: "Search properties" }).click();

  await expect(location).toHaveAttribute("aria-invalid", "true");
  await expect(location).toBeFocused();
  await expect(location).toHaveAccessibleDescription(/^Use letters, numbers/);
  await expect(page).toHaveURL(/\/$/);

  await location.fill("Lagos");
  await expect(location).not.toHaveAttribute("aria-invalid");
});

test("the header's Rent link preselects rent", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Rent" }).click();

  await expect(page).toHaveURL(/\/\?listing=rent#search$/);
  await expect(searchForm(page).getByRole("radio", { name: "Rent" })).toBeChecked();
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("the form still submits a GET query the parser accepts", async ({ page }) => {
    await page.goto("/?listing=rent");
    const form = searchForm(page);

    await expect(form.getByRole("radio", { name: "Rent" })).toBeChecked();
    await form.getByLabel("Location").fill("Lekki");
    await form.getByRole("button", { name: "Search properties" }).click();

    await expect(page).toHaveURL(/\/properties\?listing=rent&location=Lekki&type=any&price=any$/);
  });
});
