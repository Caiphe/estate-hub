import { expect, test } from "@playwright/test";

test("shows the EstateHub foundation page", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Property, connected." })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open API documentation" })).toBeVisible();
});
