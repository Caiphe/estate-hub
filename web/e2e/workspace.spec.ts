import { expect, test, type Page } from "@playwright/test";

import { E2E_NAME, E2E_USERS, signInFromLoginPage } from "./support";

const SEARCH = { name: "Search staff by name or email" } as const;
const ACCOUNT = { name: `${E2E_NAME}, Administrator, account menu` } as const;

/** Shell behavior for an administrator. One sign-in for the whole file: logins are rate limited. */
test.describe("workspace shell", () => {
  test.describe.configure({ mode: "serial" });

  let page: Page;

  test.beforeAll(async ({ browser }) => {
    // A fixed locale and time zone, so the dashboard date has one right answer.
    page = await browser.newPage({ locale: "en-GB", timezoneId: "Europe/London" });
    await signInFromLoginPage(page, E2E_USERS.shell);
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("the sidebar marks the current section, including nested pages", async () => {
    const nav = page.getByRole("navigation", { name: "Workspace" });
    await expect(nav.getByRole("link")).toHaveText(["Dashboard", "Staff", "Audit log", "Change password"]);
    await expect(nav.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");

    await page.goto("/staff/new");
    await expect(nav.getByRole("link", { name: "Staff" })).toHaveAttribute("aria-current", "page");
    await expect(nav.locator("[aria-current]")).toHaveCount(1);
  });

  test("the dashboard greets by name with the local date, without hydration warnings", async () => {
    const warnings: string[] = [];
    page.on("console", (message) => {
      if (/hydrat|did not match/i.test(message.text())) warnings.push(message.text());
    });
    const heading = page.getByRole("heading", { level: 1 });
    const day = page.locator("main time");

    await page.clock.setFixedTime(new Date("2026-11-04T08:30:00Z"));
    await page.goto("/dashboard");
    await expect(heading).toHaveAccessibleName(`Good morning, ${E2E_NAME}`);
    await expect(heading).toContainText("👋");
    await expect(page.getByText("Here’s what’s happening with your EstateHub team today.")).toBeVisible();
    await expect(day).toHaveText("Wed, 04 Nov 2026");
    await expect(day).toHaveAttribute("datetime", "2026-11-04");

    await page.clock.setFixedTime(new Date("2026-11-04T12:00:00Z"));
    await page.reload();
    await expect(heading).toHaveAccessibleName(`Good afternoon, ${E2E_NAME}`);

    // 23:30 in London is still the 4th, though the next UTC day is close.
    await page.clock.setFixedTime(new Date("2026-11-04T23:30:00Z"));
    await page.reload();
    await expect(heading).toHaveAccessibleName(`Good evening, ${E2E_NAME}`);
    await expect(day).toHaveAttribute("datetime", "2026-11-04");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    expect(warnings).toEqual([]);
  });

  test("the top-bar search opens the staff directory filtered by the term", async () => {
    await page.goto("/dashboard");
    const search = page.getByRole("searchbox", SEARCH);
    await expect(search).toHaveAttribute("placeholder", "Search staff by name or email…");

    await search.fill(`  ${E2E_USERS.shell} `);
    await search.press("Enter");
    await expect(page).toHaveURL(/\/staff\?q=e2e\.shell%40estatehub\.example$/);
    await expect(page.getByLabel("Search name or email")).toHaveValue(E2E_USERS.shell);
    const rows = page.getByRole("table", { name: "Staff accounts" }).getByRole("row");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(1)).toContainText(E2E_USERS.shell);

    // A new search while already on /staff replaces the results.
    await search.fill("no such staff member");
    await search.press("Enter");
    await expect(page).toHaveURL(/\/staff\?q=no\+such\+staff\+member$/);
    await expect(page.getByText("No staff members match these filters.")).toBeVisible();
    await expect(page.getByLabel("Search name or email")).toHaveValue("no such staff member");
  });

  test("⌘K and Ctrl+K focus the search from anywhere", async () => {
    await page.goto("/audit");
    const search = page.getByRole("searchbox", SEARCH);
    await expect(search).not.toBeFocused();

    await page.keyboard.press("Meta+k");
    await expect(search).toBeFocused();
    await search.blur();
    await page.keyboard.press("Control+k");
    await expect(search).toBeFocused();
  });

  test("the account menu shows identity and handles focus, Escape, and dismissal", async () => {
    await page.goto("/dashboard");
    const trigger = page.getByRole("button", ACCOUNT);
    await expect(trigger).toContainText("EA");
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = page.locator(`[id="${await trigger.getAttribute("aria-controls")}"]`);
    await expect(menu).toContainText(E2E_USERS.shell);
    await expect(menu.getByRole("link", { name: "Change password" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(menu.getByRole("button", { name: "Sign out" })).toBeFocused();

    // Escape closes and returns focus to the button.
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    // Opens from the keyboard; a click outside closes it.
    await page.keyboard.press("Enter");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await page.getByRole("heading", { level: 1 }).click();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    // Tabbing out of the menu closes it.
    await trigger.click();
    await page.keyboard.press("Shift+Tab");
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("searchbox", SEARCH)).toBeFocused();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  test("Change password in the account menu opens the password page", async () => {
    const trigger = page.getByRole("button", ACCOUNT);
    await trigger.click();
    await page.locator(`[id="${await trigger.getAttribute("aria-controls")}"]`).getByRole("link", { name: "Change password" }).click();

    await expect(page).toHaveURL(/\/account\/password$/);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(
      page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Change password" }),
    ).toHaveAttribute("aria-current", "page");
  });

  test("Sign out in the account menu ends the session", async () => {
    await page.getByRole("button", ACCOUNT).click();
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
  });
});
