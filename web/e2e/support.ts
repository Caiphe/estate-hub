import { expect, type APIRequestContext, type Page } from "@playwright/test";

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
  shell: "e2e.shell@estatehub.example",
  dashboard: "e2e.dashboard@estatehub.example",
} as const;

export const E2E_NAME = "E2E Admin";

/** Any dashboard greeting. */
export const ANY_GREETING = /^Good (morning|afternoon|evening), /;

/** The dashboard heading for `name` at whatever time the test runs. */
export function greeting(name: string): RegExp {
  return new RegExp(`^Good (morning|afternoon|evening), ${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);
}

export async function signIn(page: Page, email: string, password = E2E_PASSWORD): Promise<void> {
  await page.getByLabel("Email address").fill(email);
  // Exact: the visibility toggle's name, "Show password", also contains the word.
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
}

export async function signInFromLoginPage(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await signIn(page, email);
  await expect(page).toHaveURL(/\/dashboard$/);
}

/** Password for staff members the tests create through the API. */
export const MEMBER_PASSWORD = "member passphrase for e2e";

export async function adminToken(request: APIRequestContext, email: string): Promise<string> {
  const response = await request.post("/api/v1/auth/token", {
    form: { username: email, password: E2E_PASSWORD },
  });
  expect(response.status()).toBe(200);
  return ((await response.json()) as { access_token: string }).access_token;
}

/** Create a staff member through the API as an administrator (bearer, so no CSRF). */
export async function createStaff(
  request: APIRequestContext,
  token: string,
  role: string,
): Promise<{ id: string; email: string }> {
  const unique = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const email = `e2e.${role}.${unique}@estatehub.example`;
  const response = await request.post("/api/v1/staff", {
    headers: { Authorization: `Bearer ${token}` },
    data: { email, full_name: `E2E ${role}`, password: MEMBER_PASSWORD, roles: [role] },
  });
  expect(response.status(), await response.text()).toBe(201);
  return { id: ((await response.json()) as { id: string }).id, email };
}

export async function signInAs(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await signIn(page, email, password);
  await expect(page).toHaveURL(/\/dashboard$/);
}
