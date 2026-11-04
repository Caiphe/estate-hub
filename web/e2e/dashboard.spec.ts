import { expect, test, type Page, type Request, type Route } from "@playwright/test";

import { E2E_USERS, adminToken, createStaff, signInFromLoginPage } from "./support";

const CARDS = {
  "Total staff": "",
  "Active staff": "status=active",
  "Disabled staff": "status=disabled",
  Administrators: "role=administrator",
} as const;
type CardLabel = keyof typeof CARDS;

/** A count-only staff query, as the summary cards send them. */
const isCount = (url: URL) => url.pathname === "/api/v1/staff" && url.searchParams.get("limit") === "1";
const COUNT_ROUTE = (url: URL) => isCount(url);

function value(page: Page, label: CardLabel) {
  return page
    .getByRole("region", { name: "Staff summary" })
    .locator("dt", { hasText: new RegExp(`^${label}$`) })
    .locator("xpath=following-sibling::dd[1]");
}

async function shown(page: Page, label: CardLabel): Promise<number> {
  return Number((await value(page, label).textContent())?.replace(/\D/g, ""));
}

async function apiTotal(page: Page, filter: string): Promise<number> {
  const response = await page.request.get(`/api/v1/staff?${filter ? `${filter}&` : ""}limit=1`);
  return ((await response.json()) as { total: number }).total;
}

const page0 = (total: number) => ({ items: [], total, limit: 1, offset: 0 });

const AUDIT_ROUTE = (url: URL) => url.pathname === "/api/v1/audit-events";

function roleRows(page: Page) {
  return page.getByRole("table", { name: "Role assignments by role, largest first" }).locator("tbody tr");
}

function activity(page: Page) {
  return page.getByRole("region", { name: "Recent staff activity" });
}

/** Summary cards for an administrator. One sign-in for the whole file: logins are rate limited. */
test.describe("staff summary cards", () => {
  test.describe.configure({ mode: "serial" });

  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage({ locale: "en-GB" });
    await signInFromLoginPage(page, E2E_USERS.dashboard);
  });

  test.afterAll(async () => {
    await page.close();
  });

  test.afterEach(async () => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("cards and role assignments send count-only queries with their filters", async () => {
    const searches = new Set<string>();
    const onRequest = (request: Request) => {
      const url = new URL(request.url());
      if (isCount(url)) searches.add(url.search);
    };
    page.on("request", onRequest);
    await page.goto("/dashboard");
    for (const label of Object.keys(CARDS) as CardLabel[]) {
      await expect(value(page, label)).toHaveText(/^\d[\d,]*$/);
    }

    await expect(roleRows(page)).toHaveCount(4);
    page.off("request", onRequest);

    expect([...searches].sort()).toEqual(
      [
        "?limit=1",
        "?status=active&limit=1",
        "?status=disabled&limit=1",
        "?role=administrator&limit=1",
        "?role=manager&limit=1",
        "?role=agent&limit=1",
        "?role=accountant&limit=1",
      ].sort(),
    );
    // No invented trends.
    await expect(page.getByRole("region", { name: "Staff summary" })).not.toContainText(/%|last month/);
  });

  test("totals match the API", async () => {
    // Other specs create staff in parallel; reload until a page load agrees with the API.
    await expect(async () => {
      await page.goto("/dashboard");
      for (const [label, filter] of Object.entries(CARDS) as Array<[CardLabel, string]>) {
        await expect(value(page, label)).toHaveText(/^\d[\d,]*$/);
        expect(await shown(page, label)).toBe(await apiTotal(page, filter));
      }
    }).toPass({ timeout: 15_000 });
  });

  test("zero totals show as zero", async () => {
    await page.route(COUNT_ROUTE, (route) => route.fulfill({ json: page0(0) }));
    await page.goto("/dashboard");
    for (const label of Object.keys(CARDS) as CardLabel[]) {
      await expect(value(page, label)).toHaveText("0");
    }
    const roles = page.getByRole("region", { name: "Role assignments" });
    await expect(roles).toContainText("No roles are assigned yet.");
    await expect(roles).not.toContainText("NaN");
    await expect(roleRows(page).locator("td:last-child")).toHaveText(["—", "—", "—", "—"]);
  });

  test("one failing card offers a retry without affecting the others", async () => {
    await page.route(COUNT_ROUTE, (route: Route) =>
      new URL(route.request().url()).searchParams.get("status") === "disabled"
        ? route.fulfill({ status: 500, json: { error: { code: "internal_error", message: "x", fields: {}, request_id: "r" } } })
        : route.continue(),
    );
    await page.goto("/dashboard");
    await expect(value(page, "Disabled staff")).toContainText("Unavailable");
    for (const label of ["Total staff", "Active staff", "Administrators"] as const) {
      await expect(value(page, label)).toHaveText(/^\d[\d,]*$/);
    }

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.getByRole("button", { name: "Retry Disabled staff" }).click();
    await expect(value(page, "Disabled staff")).toHaveText(/^\d[\d,]*$/);
    await expect(page.getByRole("button", { name: /^Retry / })).toHaveCount(0);
  });

  test("a forbidden count says so, with nothing to retry", async () => {
    await page.route(COUNT_ROUTE, (route: Route) =>
      new URL(route.request().url()).searchParams.get("role") === "administrator"
        ? route.fulfill({
            status: 403,
            json: { error: { code: "permission_denied", message: "x", fields: {}, request_id: "r" } },
          })
        : route.continue(),
    );
    await page.goto("/dashboard");
    await expect(value(page, "Administrators")).toHaveText("No access");
    await expect(page.getByRole("button", { name: "Retry Administrators" })).toHaveCount(0);
    await expect(value(page, "Total staff")).toHaveText(/^\d[\d,]*$/);
  });

  test("role assignments match the API, largest first, with shares of all assignments", async () => {
    await expect(async () => {
      await page.goto("/dashboard");
      await expect(roleRows(page)).toHaveCount(4);
      const rows = await roleRows(page).evaluateAll((trs) =>
        trs.map((tr) => [...tr.querySelectorAll("th, td")].map((cell) => cell.textContent!.trim())),
      );
      const expected = await Promise.all(
        ["administrator", "manager", "agent", "accountant"].map(async (role) => apiTotal(page, `role=${role}`)),
      );
      const shown = Object.fromEntries(rows.map(([role, count]) => [role.toLowerCase(), Number(count.replace(/\D/g, ""))]));
      expect(shown).toEqual({ administrator: expected[0], manager: expected[1], agent: expected[2], accountant: expected[3] });
      const counts = rows.map(([, count]) => Number(count.replace(/\D/g, "")));
      expect(counts).toEqual([...counts].sort((a, b) => b - a));
      const total = counts.reduce((sum, count) => sum + count, 0);
      await expect(page.getByRole("region", { name: "Role assignments" })).toContainText(
        `${total.toLocaleString("en-GB")} role assignments across ${(await apiTotal(page, "")).toLocaleString("en-GB")} staff members.`,
      );
      for (const [, count, share] of rows) {
        const expectedShare = Number(count.replace(/\D/g, "")) / total;
        expect(Number(share.replace("%", ""))).toBeCloseTo(expectedShare * 100, 0);
      }
    }).toPass({ timeout: 15_000 });
  });

  test("recent activity lists the newest audit events with readable labels and no metadata", async () => {
    await expect(async () => {
      await page.goto("/dashboard");
      const items = activity(page).getByRole("listitem");
      await expect(items.first()).toBeVisible();
      const response = await page.request.get("/api/v1/audit-events?limit=6");
      const latest = ((await response.json()) as { items: Array<{ event_code: string }> }).items;
      await expect(items).toHaveCount(latest.length);
      await expect(items.locator("code")).toHaveText(latest.map((item) => `Event code ${item.event_code}`));
    }).toPass({ timeout: 15_000 });

    await expect(activity(page).getByRole("listitem").first().locator("time")).toHaveAttribute("datetime", /^\d{4}-/);
    await expect(activity(page)).not.toContainText(/client_ip_prefix|session_family_id|email_fingerprint|\{"/);
    // Every actor here is a real staff member, so each name resolves.
    await expect(activity(page)).not.toContainText("unknown staff member");
    await activity(page).getByRole("link", { name: "View full audit log" }).click();
    await expect(page.getByRole("heading", { name: "Audit log", level: 1 })).toBeVisible();
  });

  test("recent activity shows its own empty and error states", async () => {
    await page.route(AUDIT_ROUTE, (route) => route.fulfill({ json: { items: [], total: 0, limit: 6, offset: 0 } }));
    await page.goto("/dashboard");
    await expect(activity(page)).toContainText("No staff activity has been recorded yet.");

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.route(AUDIT_ROUTE, (route) => route.fulfill({ status: 500, body: "x" }));
    await page.goto("/dashboard");
    await expect(activity(page).getByRole("alert")).toContainText("Recent activity could not be loaded.");
    // The rest of the dashboard is unaffected.
    await expect(roleRows(page)).toHaveCount(4);

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await activity(page).getByRole("button", { name: "Try again" }).click();
    await expect(activity(page).getByRole("listitem").first()).toBeVisible();
  });

  test("leaving the dashboard cancels counts still in flight", async () => {
    await page.route(COUNT_ROUTE, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue().catch(() => {});
    });
    const finished: string[] = [];
    const failed: string[] = [];
    page.on("requestfinished", (request) => {
      if (isCount(new URL(request.url()))) finished.push(request.url());
    });
    page.on("requestfailed", (request) => {
      if (isCount(new URL(request.url()))) failed.push(request.failure()?.errorText ?? "");
    });

    await page.goto("/dashboard");
    await expect(value(page, "Total staff")).toHaveText("Loading");
    await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Audit log" }).click();
    await expect(page.getByRole("heading", { name: "Audit log", level: 1 })).toBeVisible();
    await page.waitForTimeout(2500);

    expect(finished).toEqual([]);
    expect(failed.length).toBeGreaterThanOrEqual(4);
    page.removeAllListeners("requestfinished");
    page.removeAllListeners("requestfailed");
  });

  test("totals reflect a staff member created and disabled in the workspace", async ({ request }) => {
    await page.goto("/dashboard");
    await expect(value(page, "Disabled staff")).toHaveText(/^\d[\d,]*$/);
    const before = { total: await shown(page, "Total staff"), disabled: await shown(page, "Disabled staff") };

    const member = await createStaff(request, await adminToken(request, E2E_USERS.dashboard), "agent");
    await page.goto(`/staff/${member.id}`);
    await page.getByRole("button", { name: "Disable account" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Disable account" }).click();
    await expect(page.getByRole("status")).toContainText("Account disabled");

    await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Dashboard" }).click();
    await expect(value(page, "Disabled staff")).toHaveText(/^\d[\d,]*$/);
    // At least: other specs may add staff in parallel, but nothing here removes any.
    expect(await shown(page, "Total staff")).toBeGreaterThanOrEqual(before.total + 1);
    expect(await shown(page, "Disabled staff")).toBeGreaterThanOrEqual(before.disabled + 1);
  });
});
