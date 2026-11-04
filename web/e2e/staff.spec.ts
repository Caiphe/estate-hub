import { expect, test } from "@playwright/test";

import {
  E2E_USERS,
  MEMBER_PASSWORD,
  greeting,
  adminToken,
  createStaff,
  signInAs,
  signInFromLoginPage,
} from "./support";

const runId = Date.now().toString(36);

test.describe("administrator staff management", () => {
  test.describe.configure({ mode: "serial" });

  const memberEmail = `e2e.member.${runId}@estatehub.example`;
  let memberId = "";

  test("creates a staff member, assigns roles, the member signs in, then is disabled", async ({
    page,
    browser,
  }) => {
    await signInFromLoginPage(page, E2E_USERS.staffAdmin);
    await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Staff" }).click();
    await expect(page.getByRole("heading", { name: "Staff", level: 1 })).toBeVisible();

    // Create.
    await page.getByRole("link", { name: "Add staff member" }).click();
    await expect(page).toHaveURL(/\/staff\/new$/);
    // The submit button is enabled once the form is interactive.
    await expect(page.getByRole("button", { name: "Create staff member" })).toBeEnabled();
    await page.getByLabel("Email", { exact: true }).fill(memberEmail);
    await page.getByLabel("Full name").fill("E2E Member");
    await page.getByLabel("Initial password").fill(MEMBER_PASSWORD);
    await page.getByRole("checkbox", { name: "Agent" }).check();
    await page.getByRole("button", { name: "Create staff member" }).click();

    await expect(page).toHaveURL(/\/staff\/[0-9a-f-]{36}\?created=1$/);
    await expect(page.getByRole("status")).toHaveText("Staff member created.");
    memberId = new URL(page.url()).pathname.split("/").pop() ?? "";
    await expect(page.getByRole("heading", { name: "E2E Member", level: 1 })).toBeVisible();
    // The initial password is never displayed again.
    await expect(page.getByText(MEMBER_PASSWORD)).toHaveCount(0);

    // Assign an extra role (adding needs no confirmation).
    await page.getByRole("checkbox", { name: "Manager" }).check();
    await page.getByRole("button", { name: "Save roles" }).click();
    await expect(page.getByRole("status")).toContainText("Roles saved");
    await expect(page.getByRole("definition").filter({ hasText: "Agent, Manager" })).toBeVisible();

    // The member signs in and sees what their roles allow.
    const memberContext = await browser.newContext();
    const memberPage = await memberContext.newPage();
    await signInAs(memberPage, memberEmail, MEMBER_PASSWORD);
    await expect(memberPage.getByRole("heading", { name: greeting("E2E Member") })).toBeVisible();
    const memberNav = memberPage.getByRole("navigation", { name: "Workspace" });
    await expect(memberNav.getByRole("link", { name: "Staff" })).toBeVisible();
    await expect(memberNav.getByRole("link", { name: "Audit log" })).toHaveCount(0);

    // Disable, with confirmation; the member's session ends.
    await page.getByRole("button", { name: "Disable account" }).click();
    const dialog = page.getByRole("dialog", { name: "Disable this account?" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
    await dialog.getByRole("button", { name: "Disable account" }).click();
    await expect(page.getByRole("status")).toContainText("Account disabled");
    await expect(page.getByText("disabled", { exact: true })).toBeVisible();

    await memberPage.reload();
    await expect(memberPage).toHaveURL(/\/login/);
    await expect(memberPage.getByRole("heading", { name: greeting("E2E Member") })).toHaveCount(0);
    await memberContext.close();
  });

  test("the audit log shows the events from that flow", async ({ page }) => {
    expect(memberId).not.toBe("");
    await signInFromLoginPage(page, E2E_USERS.staffAdmin);
    await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Audit log" }).click();

    await page.getByLabel("Staff member ID").fill(memberId);
    await page.getByRole("button", { name: "Apply filters" }).click();

    const rows = page.getByRole("table", { name: "Audit events" }).getByRole("row");
    await expect(rows.filter({ hasText: "staff.created" })).toHaveCount(1);
    await expect(rows.filter({ hasText: "staff.roles_changed" })).toHaveCount(1);
    await expect(rows.filter({ hasText: "staff.disabled" })).toHaveCount(1);
    await expect(rows.filter({ hasText: "auth.login_succeeded" })).toHaveCount(1);
    // JSONB does not preserve key order, so check each part of the metadata.
    const rolesChanged = rows.filter({ hasText: "staff.roles_changed" });
    await expect(rolesChanged).toContainText('"before":["agent"]');
    await expect(rolesChanged).toContainText('"after":["agent","manager"]');
    await expect(page.getByText(MEMBER_PASSWORD)).toHaveCount(0);
  });
});

test("administrator lock-out protection is explained", async ({ page }) => {
  await signInFromLoginPage(page, E2E_USERS.selfAdmin);
  await page.goto("/staff");
  await page.getByLabel("Search name or email").fill(E2E_USERS.selfAdmin);
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("table").getByRole("link").first().click();
  await expect(page).toHaveURL(/\/staff\/[0-9a-f-]{36}$/);

  await page.getByRole("button", { name: "Disable my account" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Disable account" }).click();
  const message = "You cannot disable your own account or remove your own administrator role.";
  await expect(page.locator("main").getByRole("alert")).toHaveText(message);

  await page.getByRole("checkbox", { name: "Administrator" }).uncheck();
  await page.getByRole("checkbox", { name: "Manager" }).check();
  await page.getByRole("button", { name: "Save roles" }).click();
  const confirm = page.getByRole("dialog", { name: "Remove roles?" });
  await expect(confirm).toContainText("Administrator");
  await confirm.getByRole("button", { name: "Remove roles" }).click();
  await expect(page.locator("main").getByRole("alert")).toHaveText(message);
  await expect(page.getByRole("definition").filter({ hasText: "Administrator" })).toBeVisible();
});

test("duplicate emails are reported on the email field", async ({ page }) => {
  await signInFromLoginPage(page, E2E_USERS.staffAdmin);
  await page.goto("/staff/new");
  await expect(page.getByRole("button", { name: "Create staff member" })).toBeEnabled();
  await page.getByLabel("Email", { exact: true }).fill(E2E_USERS.selfAdmin.toUpperCase());
  await page.getByLabel("Full name").fill("Duplicate");
  await page.getByLabel("Initial password").fill("duplicate passphrase");
  await page.getByRole("checkbox", { name: "Agent" }).check();
  await page.getByRole("button", { name: "Create staff member" }).click();

  await expect(page.getByText("A staff member with this email already exists.")).toBeVisible();
  await expect(page.getByLabel("Email", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByLabel("Initial password")).toHaveValue("");
});

test.describe("roles without staff administration", () => {
  test("a manager sees a read-only staff directory", async ({ page, request }) => {
    const token = await adminToken(request, E2E_USERS.roleAdmin);
    const manager = await createStaff(request, token, "manager");
    const other = await createStaff(request, token, "agent");

    await signInAs(page, manager.email, MEMBER_PASSWORD);
    const nav = page.getByRole("navigation", { name: "Workspace" });
    await expect(nav.getByRole("link", { name: "Audit log" })).toHaveCount(0);
    // staff:read brings the top-bar staff search and the staff panels, but not the audit feed.
    await expect(page.getByRole("search", { name: "Staff" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Role assignments" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Recent staff activity" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Manager, account menu$/ })).toBeVisible();
    await nav.getByRole("link", { name: "Staff" }).click();
    await expect(page.getByRole("heading", { name: "Staff", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Add staff member" })).toHaveCount(0);

    await page.goto(`/staff/${other.id}`);
    await expect(page.getByRole("heading", { name: "E2E agent", level: 1 })).toBeVisible();
    for (const control of ["Save profile", "Save roles", "Disable account", "Sign out everywhere"]) {
      await expect(page.getByRole("button", { name: control })).toHaveCount(0);
    }

    await page.goto("/staff/new");
    await expect(page.getByRole("heading", { name: "Access denied" })).toBeVisible();
    await page.goto("/audit");
    await expect(page.getByRole("heading", { name: "Access denied" })).toBeVisible();
  });

  for (const role of ["agent", "accountant"]) {
    test(`an ${role} cannot reach staff management or the audit log`, async ({ page, request }) => {
      const token = await adminToken(request, E2E_USERS.roleAdmin);
      const user = await createStaff(request, token, role);

      await signInAs(page, user.email, MEMBER_PASSWORD);
      // No staff summaries, so the dashboard explains their own access instead.
      await expect(page.getByRole("heading", { name: greeting(`E2E ${role}`) })).toBeVisible();
      const account = page.getByRole("region", { name: "Your account" });
      await expect(account).toContainText(user.email);
      await expect(account).toContainText(role === "agent" ? "Agent" : "Accountant");
      for (const region of ["Staff summary", "Role assignments", "Recent staff activity"]) {
        await expect(page.getByRole("region", { name: region })).toHaveCount(0);
      }
      const nav = page.getByRole("navigation", { name: "Workspace" });
      await expect(nav.getByRole("link", { name: "Staff" })).toHaveCount(0);
      await expect(nav.getByRole("link", { name: "Audit log" })).toHaveCount(0);
      await expect(page.getByRole("search", { name: "Staff" })).toHaveCount(0);

      for (const path of ["/staff", `/staff/${user.id}`, "/staff/new", "/audit"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { name: "Access denied" })).toBeVisible();
        await expect(page.getByRole("table")).toHaveCount(0);
      }
    });
  }
});
