import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test";

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
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
});

test("inline validation runs before contacting the API", async ({ page }) => {
  let requests = 0;
  await page.route("**/auth/token", (route) => (requests++, route.abort()));
  await page.goto("/login");
  const email = page.getByLabel("Email address");
  const password = page.getByLabel("Password", { exact: true });
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page.getByText("Enter your email address.")).toBeVisible();
  await expect(page.getByText("Enter your password.")).toBeVisible();
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await expect(email).toHaveAttribute("aria-describedby", "email-error");
  await expect(password).toHaveAttribute("aria-describedby", "password-error");
  // Focus moves to the first invalid field, so it is announced with its error.
  await expect(email).toBeFocused();

  await email.fill("not-an-email");
  await password.fill("a passphrase");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await expect(password).not.toHaveAttribute("aria-invalid");
  await expect(email).toBeFocused();
  expect(requests).toBe(0);
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
  // The dashboard greeting, not the login page's own "Welcome back".
  await expect(page.getByRole("heading", { name: /^Welcome, / })).toHaveCount(0);
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

test.describe("login form composition", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("button", { name: "Log in" })).toBeEnabled(); // hydrated
  });

  test("fields carry their labels, autocomplete, placeholders, and silent icons", async ({ page }) => {
    const email = page.getByLabel("Email address");
    await expect(email).toHaveAttribute("type", "email");
    await expect(email).toHaveAttribute("autocomplete", "username");
    await expect(email).toHaveAttribute("placeholder", "you@example.com");

    const password = page.getByLabel("Password", { exact: true });
    await expect(password).toHaveAttribute("type", "password");
    await expect(password).toHaveAttribute("autocomplete", "current-password");
    await expect(password).toHaveAttribute("placeholder", "Enter your password");

    const form = page.locator("form");
    // Unnamed inputs: a native fallback submission can never carry credentials.
    await expect(form.locator("input[name]")).toHaveCount(0);
    await expect(form).toHaveAttribute("method", "post");
    await expect(form.locator("label svg, label button")).toHaveCount(0);
    await expect(form.locator("button button")).toHaveCount(0);
    for (const svg of await form.locator("svg").all()) {
      await expect(svg).toHaveAttribute("aria-hidden", "true");
    }
  });

  test("the visibility toggle is keyboard operable and never changes the value", async ({ page }) => {
    const password = page.getByLabel("Password", { exact: true });
    await password.fill("a secret passphrase");
    const toggle = page.getByRole("button", { name: "Show password" });
    await expect(toggle).toHaveAttribute("aria-pressed", "false");

    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(password).toHaveAttribute("type", "text");
    await expect(password).toHaveValue("a secret passphrase");
    const hide = page.getByRole("button", { name: "Hide password" });
    await expect(hide).toHaveAttribute("aria-pressed", "true");
    await expect(hide).toBeFocused();

    await page.keyboard.press("Space");
    await expect(password).toHaveAttribute("type", "password");
    await expect(password).toHaveValue("a secret passphrase");
  });

  test("account help explains who to contact instead of linking to a reset flow", async ({ page }) => {
    const help = page.getByRole("button", { name: "Forgot your password?" });
    const guidance = page.getByText(/Contact your EstateHub administrator/);
    await expect(help).toHaveAttribute("aria-expanded", "false");
    await expect(guidance).toBeHidden();

    await help.focus();
    await page.keyboard.press("Enter");
    await expect(help).toHaveAttribute("aria-expanded", "true");
    await expect(guidance).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);

    await expect(page.getByText("Need access? Contact your administrator.")).toBeVisible();
    await expect(page.getByText(/create an account/i)).toHaveCount(0);
  });

  test("tab order follows the visual order", async ({ page }) => {
    await page.getByLabel("Email address").focus();
    const order = [
      page.getByLabel("Password", { exact: true }),
      page.getByRole("button", { name: "Show password" }),
      page.getByRole("button", { name: "Forgot your password?" }),
      page.getByRole("button", { name: "Log in" }),
    ];
    for (const next of order) {
      await page.keyboard.press("Tab");
      await expect(next).toBeFocused();
    }
  });

  test("submitting shows a pending button and hides the password again", async ({ page }) => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/auth/token", async (route) => {
      await held;
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "invalid_credentials", message: "x", request_id: "r" } }),
      });
    });

    await page.getByLabel("Email address").fill("someone@estatehub.example");
    await page.getByLabel("Password", { exact: true }).fill("a secret passphrase");
    await page.getByRole("button", { name: "Show password" }).click();
    await page.getByRole("button", { name: "Log in" }).click();

    const pending = page.getByRole("button", { name: "Logging in…" });
    await expect(pending).toBeDisabled();
    await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "password");

    release();
    await expect(page.locator("form").getByRole("alert")).toHaveText("Incorrect email or password.");
    await expect(page.getByRole("button", { name: "Log in" })).toBeEnabled();
  });

  test("controls are at least 44px tall and inputs use 16px text on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const control of [
      page.getByLabel("Email address"),
      page.getByLabel("Password", { exact: true }),
      page.getByRole("button", { name: "Show password" }),
      page.getByRole("button", { name: "Forgot your password?" }),
      page.getByRole("button", { name: "Log in" }),
    ]) {
      expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    for (const input of await page.locator("form input").all()) {
      expect(await input.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
    }
  });
});

test.describe("login failure and submission states", () => {
  const serverFailures = [
    { name: "401 credentials", status: 401, message: "Incorrect email or password." },
    { name: "422 validation", status: 422, message: "Incorrect email or password." },
    {
      name: "429 rate limit",
      status: 429,
      headers: { "Retry-After": "120" },
      message: "Too many login attempts. Try again in 2 minutes.",
    },
    { name: "503 unavailable", status: 503, message: "Logging in is temporarily unavailable. Please try again shortly." },
    { name: "500 unexpected", status: 500, message: "Something went wrong. Please try again." },
  ];

  async function submitFilledForm(page: Page): Promise<void> {
    await page.getByLabel("Email address").fill("someone@estatehub.example");
    await page.getByLabel("Password", { exact: true }).fill("a secret passphrase");
    await page.getByRole("button", { name: "Log in" }).click();
  }

  async function expectSafeFailure(page: Page, message: string): Promise<void> {
    const alert = page.locator("form").getByRole("alert");
    await expect(alert).toHaveText(message);
    await expect(alert).toBeFocused();
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
    await expect(page.getByRole("button", { name: "Log in" })).toBeEnabled();
    // The API's own wording, codes, and request ids never reach the page.
    await expect(page.getByText(/internal detail|req-123|rate_limited/)).toHaveCount(0);
    await expect(page).toHaveURL(/\/login$/);
  }

  for (const failure of serverFailures) {
    test(`${failure.name} shows its own safe message`, async ({ page }) => {
      await page.route("**/auth/token", (route) =>
        route.fulfill({
          status: failure.status,
          headers: failure.headers,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "rate_limited", message: "internal detail", fields: {}, request_id: "req-123" },
          }),
        }),
      );
      await page.goto("/login");
      await submitFilledForm(page);
      await expectSafeFailure(page, failure.message);
    });
  }

  test("a network failure says the server could not be reached", async ({ page }) => {
    await page.route("**/auth/token", (route) => route.abort("internetdisconnected"));
    await page.goto("/login");
    await submitFilledForm(page);
    await expectSafeFailure(page, "The server could not be reached. Check your connection and try again.");
  });

  test("a pending submission cannot be repeated", async ({ page }) => {
    let requests = 0;
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/auth/token", async (route) => {
      requests++;
      await held;
      await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
    });
    await page.goto("/login");
    await submitFilledForm(page);
    await expect(page.getByRole("button", { name: "Logging in…" })).toBeDisabled();
    await expect(page.locator("form")).toHaveAttribute("aria-busy", "true");

    await page.getByLabel("Email address").press("Enter");
    await page.locator("form").evaluate((form: HTMLFormElement) => form.requestSubmit());
    release();
    await expect(page.locator("form").getByRole("alert")).toBeVisible();
    expect(requests).toBe(1);
  });

  test("the password-changed notice gives way to a later error", async ({ page }) => {
    await page.route("**/auth/token", (route) => route.fulfill({ status: 401, body: "{}" }));
    await page.goto("/login?changed=1");
    const notice = page.getByRole("status").filter({ hasText: "Your password was changed." });
    await expect(notice).toHaveText("Your password was changed. Log in with your new password.");

    await submitFilledForm(page);
    await expect(page.locator("form").getByRole("alert")).toBeVisible();
    await expect(notice).toHaveCount(0);
  });

  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 390, height: 844 },
  ]) {
    test(`an error keeps the submit button on screen at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.route("**/auth/token", (route) => route.fulfill({ status: 429, body: "{}" }));
      await page.goto("/login");
      const submit = page.getByRole("button", { name: "Log in" });
      const before = (await submit.boundingBox())!;

      await submitFilledForm(page);
      const alert = page.locator("form").getByRole("alert");
      await expect(alert).toBeVisible();
      await expect(submit).toBeInViewport();
      // The button moves by no more than the one panel that appeared.
      const after = (await submit.boundingBox())!;
      expect(Math.abs(after.y - before.y)).toBeLessThanOrEqual((await alert.boundingBox())!.height + 24);
    });
  }
});

test.describe("session loss and redirect safety (stubbed API)", () => {
  const unauthorized = {
    status: 401,
    contentType: "application/json",
    body: JSON.stringify({ error: { code: "token_expired", message: "x", fields: {}, request_id: "r" } }),
  };

  /**
   * Records API calls and page loads so loops and extra requests show up. Page loads are
   * document requests: framenavigated would also count Next's hydration replaceState.
   */
  async function observe(page: Page, respond: (call: string) => Parameters<Route["fulfill"]>[0]) {
    const calls: string[] = [];
    const visits: string[] = [];
    await page.route("**/api/v1/auth/**", (route) => {
      const call = `${route.request().method()} ${new URL(route.request().url()).pathname.replace("/api/v1", "")}`;
      calls.push(call);
      return route.fulfill(respond(call));
    });
    page.on("request", (request) => {
      if (request.resourceType() === "document") visits.push(new URL(request.url()).pathname);
    });
    return { calls, visits };
  }

  async function withStaleCsrfCookie(context: BrowserContext, baseURL: string | undefined) {
    // The CSRF cookie alone lets the proxy render the workspace so the client can refresh.
    await context.addCookies([{ name: "estatehub_csrf", value: "stale", url: baseURL! }]);
  }

  test("a rejected refresh returns to login once, without a loop", async ({ page, context, baseURL }) => {
    await withStaleCsrfCookie(context, baseURL);
    const seen = await observe(page, () => unauthorized);

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    await page.waitForTimeout(1000); // a loop would navigate again within this window

    expect(seen.visits.filter((path) => path === "/login")).toHaveLength(1);
    // Identity and permissions both failed; they shared one refresh. The API already
    // cleared the cookies, so no logout call races another tab.
    expect(seen.calls.filter((call) => call === "POST /auth/refresh")).toHaveLength(1);
    expect(seen.calls).not.toContain("POST /auth/logout");
    await expect(page.getByRole("heading", { name: /^Welcome, / })).toHaveCount(0);
  });

  test("a token still refused after refresh signs out, then returns to login once", async ({
    page,
    context,
    baseURL,
  }) => {
    await withStaleCsrfCookie(context, baseURL);
    const seen = await observe(page, (call) =>
      call === "POST /auth/refresh"
        ? { status: 200, contentType: "application/json", body: "{}" }
        : call === "POST /auth/logout"
          ? { status: 204 }
          : unauthorized,
    );

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
    await page.waitForTimeout(1000);

    expect(seen.visits.filter((path) => path === "/login")).toHaveLength(1);
    expect(seen.calls.filter((call) => call === "POST /auth/logout")).toHaveLength(1);
  });

  for (const next of [
    "//evil.example/",
    "/\\evil.example",
    "https://evil.example/dashboard",
    "javascript:alert(1)",
    "/dashboard/../login",
  ]) {
    test(`login lands on the dashboard for the unsafe next value ${next}`, async ({ page }) => {
      const offsite: string[] = [];
      page.on("request", (request) => {
        if (new URL(request.url()).hostname.includes("evil")) offsite.push(request.url());
      });
      await page.route("**/auth/token", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
      );
      await page.goto(`/login?next=${encodeURIComponent(next)}`);
      await page.getByLabel("Email address").fill("someone@estatehub.example");
      await page.getByLabel("Password", { exact: true }).fill("a passphrase");
      await page.getByRole("button", { name: "Log in" }).click();

      // The full navigation goes to /dashboard; with no real cookie the proxy returns here.
      await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
      expect(offsite).toEqual([]);
    });
  }

  test("login keeps a safe next path, query included", async ({ page }) => {
    await page.route("**/auth/token", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );
    await page.goto(`/login?next=${encodeURIComponent("/account/password?from=menu")}`);
    await page.getByLabel("Email address").fill("someone@estatehub.example");
    await page.getByLabel("Password", { exact: true }).fill("a passphrase");
    await page.getByRole("button", { name: "Log in" }).click();

    await expect(page).toHaveURL(/\/login\?next=%2Faccount%2Fpassword%3Ffrom%3Dmenu$/);
  });
});
