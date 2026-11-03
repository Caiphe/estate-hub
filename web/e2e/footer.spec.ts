import { expect, type Page, test } from "@playwright/test";

function newsletter(page: Page) {
  return page.getByRole("contentinfo").getByRole("form", { name: "Newsletter sign-up" });
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("the footer is a landmark with labelled link groups", async ({ page }) => {
  const footer = page.getByRole("contentinfo");

  for (const group of ["Platform", "Company", "Support"]) {
    await expect(footer.getByRole("navigation", { name: group })).toBeVisible();
  }
  await expect(footer.getByRole("navigation", { name: "Platform" }).getByRole("link")).toHaveText([
    "Buy property",
    "Rent property",
    "Invest",
  ]);
  await expect(footer.getByText("Terms of service")).toBeVisible();
  await expect(footer.getByRole("link", { name: "Terms of service" })).toHaveCount(0);
});

test("an invalid email is explained through the live region", async ({ page }) => {
  const form = newsletter(page);
  const email = form.getByLabel("Email address");

  await form.getByRole("button", { name: "Subscribe" }).click();
  await expect(form.getByRole("status")).toHaveText("Enter your email address.");
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await expect(email).toBeFocused();

  await email.fill("reader@example");
  await email.press("Enter");
  await expect(email).toHaveAccessibleDescription("Enter a valid email address, like name@example.com.");
});

test("a valid email shows submitting, then an honest not-saved result", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(`${request.url()} ${request.postData() ?? ""}`));
  const form = newsletter(page);
  const email = form.getByLabel("Email address");

  await email.fill("  reader@example.com  ");
  await form.getByRole("button", { name: "Subscribe" }).click();

  await expect(form.getByRole("button", { name: "Subscribing…" })).toBeDisabled();
  await expect(email).toHaveValue("reader@example.com");
  await expect(form.getByRole("status")).toContainText("your address hasn't been saved");
  await expect(email).toHaveValue("");
  await expect(email).not.toHaveAttribute("aria-invalid");
  // The mock keeps the address in the browser: it is never sent anywhere.
  expect(requests.filter((entry) => entry.includes("reader@example.com"))).toEqual([]);
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("the subscribe button stays disabled", async ({ page }) => {
    await expect(newsletter(page).getByRole("button", { name: "Subscribe" })).toBeDisabled();
  });
});
