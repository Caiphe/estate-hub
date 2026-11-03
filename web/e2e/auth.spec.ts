import { expect, test } from "@playwright/test";

import { E2E_NAME, E2E_USERS, signIn, signInFromLoginPage } from "./support";

test("successful sign-in reaches the dashboard", async ({ page }) => {
  await signInFromLoginPage(page, E2E_USERS.login);

  await expect(page.getByRole("heading", { name: `Welcome, ${E2E_NAME}` })).toBeVisible();
  await expect(page.getByText(E2E_USERS.login)).toBeVisible();
  const navigation = page.getByRole("navigation", { name: "Workspace" });
  await expect(navigation.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  // Administrators see permission-gated entries; the pages arrive in a later milestone.
  await expect(navigation.getByText("Staff")).toBeVisible();
  await expect(navigation.getByText("Audit log")).toBeVisible();
});

test("invalid credentials show one generic message", async ({ page }) => {
  await page.goto("/login");
  await signIn(page, "nobody@estatehub.example", "definitely not the password");

  // Scoped to the form: Next.js also renders a route announcer with role="alert".
  await expect(page.locator("form").getByRole("alert")).toHaveText(
    "Incorrect email or password.",
  );
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel("Password")).toHaveValue("");
});

test("inline validation runs before contacting the API", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Enter your email address.")).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveAttribute("aria-invalid", "true");
});

test("a signed-out visit returns to the requested page after sign-in", async ({ page }) => {
  await page.goto("/account/password");
  await expect(page).toHaveURL(/\/login\?next=%2Faccount%2Fpassword$/);

  await signIn(page, E2E_USERS.redirect);

  await expect(page).toHaveURL(/\/account\/password$/);
  await expect(page.getByRole("heading", { name: "Change password" })).toBeVisible();
});

test("an external next parameter is ignored", async ({ page }) => {
  await page.goto("/login?next=https://evil.example/");
  await signIn(page, E2E_USERS.session);

  await expect(page).toHaveURL(/\/dashboard$/);
  // Signed in, /login itself now sends the user to the workspace.
  await page.goto("/login");
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("sign-out returns to login and back does not reveal the workspace", async ({ page }) => {
  await signInFromLoginPage(page, E2E_USERS.logout);
  // Client-side navigation pushes a history entry the back button can return to.
  await page.getByRole("link", { name: "Change password" }).click();
  await expect(page).toHaveURL(/\/account\/password$/);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goBack();
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
  await expect(page.getByText(E2E_USERS.logout)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Welcome/ })).toHaveCount(0);
});

test("an expired access token is refreshed transparently", async ({ page, context }) => {
  await signInFromLoginPage(page, E2E_USERS.refresh);
  await expect(page.getByRole("heading", { name: `Welcome, ${E2E_NAME}` })).toBeVisible();
  // Let in-flight requests finish first. Reloading mid-refresh would discard a rotated
  // cookie, and the API rightly refuses the stale token that remains.
  await page.waitForLoadState("networkidle");
  const before = await context.cookies();
  const oldRefresh = before.find((cookie) => cookie.name === "estatehub_refresh")?.value;
  expect(oldRefresh).toBeTruthy();

  // The browser drops the access cookie when it expires; simulate that.
  await context.clearCookies({ name: "estatehub_access" });
  await page.reload();

  await expect(page.getByRole("heading", { name: `Welcome, ${E2E_NAME}` })).toBeVisible();
  const after = await context.cookies();
  expect(after.find((cookie) => cookie.name === "estatehub_access")).toBeTruthy();
  expect(after.find((cookie) => cookie.name === "estatehub_refresh")?.value).not.toBe(oldRefresh);
});

test("tokens are never readable by page scripts", async ({ page }) => {
  await signInFromLoginPage(page, E2E_USERS.session);

  const readable = await page.evaluate(() => ({
    cookie: document.cookie,
    local: JSON.stringify(window.localStorage),
    session: JSON.stringify(window.sessionStorage),
  }));

  expect(readable.cookie).toContain("estatehub_csrf=");
  expect(readable.cookie).not.toContain("estatehub_access");
  expect(readable.cookie).not.toContain("estatehub_refresh");
  expect(readable.local).toBe("{}");
  expect(readable.session).toBe("{}");
});
