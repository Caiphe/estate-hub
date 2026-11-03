import { expect, type Page } from "@playwright/test";

/** Development-only accounts created by global-setup.ts through the bootstrap CLI. */
export const E2E_PASSWORD = process.env.E2E_PASSWORD ?? "e2e admin passphrase 2026";

export const E2E_USERS = {
  login: "e2e.login@estatehub.example",
  redirect: "e2e.redirect@estatehub.example",
  logout: "e2e.logout@estatehub.example",
  refresh: "e2e.refresh@estatehub.example",
  session: "e2e.session@estatehub.example",
  staffAdmin: "e2e.staff-admin@estatehub.example",
  selfAdmin: "e2e.self-admin@estatehub.example",
  roleAdmin: "e2e.role-admin@estatehub.example",
} as const;

export const E2E_NAME = "E2E Admin";

export async function signIn(page: Page, email: string, password = E2E_PASSWORD): Promise<void> {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function signInFromLoginPage(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await signIn(page, email);
  await expect(page).toHaveURL(/\/dashboard$/);
}
