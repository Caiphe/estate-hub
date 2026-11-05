import { expect, type Page, test } from "@playwright/test";

/** The widths prompt 11 requires. Layout switches at Tailwind's sm (640), md (768), lg (1024). */
const WIDTHS = [1440, 1024, 768, 390, 320] as const;
const NAV_LABELS = ["Buy", "Rent", "Invest", "Properties", "About"];

/** Distinct row positions of the matched elements, i.e. how many rows they wrap into. */
async function rows(page: Page, selector: ReturnType<Page["locator"]>): Promise<number> {
  const tops = await selector.evaluateAll((elements) =>
    elements.map((element) => Math.round(element.getBoundingClientRect().top)),
  );
  return new Set(tops).size;
}

for (const width of WIDTHS) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("never scrolls sideways, and nothing pokes past the edge", async ({ page }) => {
      await page.goto("/");
      const result = await page.evaluate(() => {
        const viewport = document.documentElement.clientWidth;
        const outside = [...document.querySelectorAll("body *")].filter((element) => {
          if (element.closest("[popover]:not(:popover-open), .sr-only")) return false;
          const box = element.getBoundingClientRect();
          return box.width > 0 && (box.right > viewport + 0.5 || box.left < -0.5);
        });
        return {
          overflow: document.documentElement.scrollWidth - viewport,
          outside: outside.map((element) => element.tagName),
        };
      });
      expect(result).toEqual({ overflow: 0, outside: [] });
    });

    test("keeps every visible control at least 24px square", async ({ page }) => {
      await page.goto("/");
      const tooSmall = await page.evaluate(() =>
        [...document.querySelectorAll("a, button, input, select, label:has(> input[type=radio])")]
          .filter((element) => element.checkVisibility() && !element.closest(".sr-only"))
          .filter((element) => getComputedStyle(element).opacity !== "0")
          .map((element) => ({ element, box: element.getBoundingClientRect() }))
          .filter(({ box }) => box.height > 0 && (box.height < 24 || box.width < 24))
          .map(({ element }) => element.textContent?.trim()),
      );
      expect(tooSmall).toEqual([]);
    });

    test("keeps the search usable with a named submit button", async ({ page }) => {
      await page.goto("/");
      const form = page.getByRole("search", { name: "Property search" });

      for (const label of ["Location", "Property type", "Price range"]) {
        await expect(form.getByLabel(label)).toBeVisible();
      }
      await expect(form.getByRole("button", { name: "Search properties" })).toBeVisible();
      // Tabs stay on one row and inside the form at every width.
      expect(await rows(page, form.getByRole("radio").locator(".."))).toBe(1);
    });

    test(`captures a full-page screenshot`, async ({ page }, testInfo) => {
      await page.goto("/");
      await page.evaluate(() => document.fonts.ready);
      await testInfo.attach(`landing-${width}`, {
        body: await page.screenshot({ fullPage: true, animations: "disabled" }),
        contentType: "image/png",
      });
    });
  });
}

test.describe("header and menu", () => {
  test("desktop shows the bar; narrower widths swap to one menu button", async ({ page }) => {
    for (const [width, desktop] of [[1440, true], [1024, true], [1023, false], [390, false]] as const) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      await expect(page.getByRole("button", { name: "Menu" })).toBeVisible({ visible: !desktop });
      await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(desktop ? 1 : 0);
    }
  });

  test.describe("mobile", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("opens by pointer, lists every link, and dismisses on an outside tap", async ({ page }) => {
      await page.goto("/");
      await page.getByRole("button", { name: "Menu" }).click();

      const navigation = page.getByRole("navigation", { name: "Primary" });
      await expect(navigation.getByRole("link")).toHaveText(NAV_LABELS);
      await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Get started" })).toBeVisible();

      await page.mouse.click(200, 820);
      await expect(navigation).toHaveCount(0);
    });

    test("works from the keyboard and returns focus on Escape", async ({ page }) => {
      await page.goto("/");
      const menuButton = page.getByRole("button", { name: "Menu" });

      await menuButton.focus();
      await page.keyboard.press("Enter");
      await page.keyboard.press("Tab");
      await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Buy" })).toBeFocused();

      await page.keyboard.press("Escape");
      await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
      await expect(menuButton).toBeFocused();
    });

    test("stops the page scrolling behind it", async ({ page }) => {
      await page.goto("/");
      const overflow = () => page.evaluate(() => getComputedStyle(document.documentElement).overflow);

      expect(await overflow()).toBe("visible");
      await page.getByRole("button", { name: "Menu" }).click();
      expect(await overflow()).toBe("hidden");
      await page.keyboard.press("Escape");
      expect(await overflow()).toBe("visible");
    });
  });

  test("menu and search stay usable at 200% zoom (a 1440px window is 720px wide)", async ({ page }) => {
    await page.setViewportSize({ width: 720, height: 450 });
    await page.goto("/");

    await page.getByRole("button", { name: "Menu" }).click();
    await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "About" })).toBeInViewport();
    await page.keyboard.press("Escape");

    const location = page.getByRole("search", { name: "Property search" }).getByLabel("Location");
    await location.fill("Sandton");
    await expect(location).toHaveValue("Sandton");
  });
});

test.describe("section recomposition", () => {
  test("hero stacks copy, search, then photograph below desktop", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const top = async (locator: ReturnType<Page["locator"]>) => (await locator.boundingBox())!.y;

    const heading = await top(page.getByRole("heading", { level: 1 }));
    const search = await top(page.getByRole("search", { name: "Property search" }));
    const photo = await top(page.getByRole("img", { name: /family/ }));
    expect(heading).toBeLessThan(search);
    expect(search).toBeLessThan(photo);
  });

  test("value strip: four across, two on tablet, one on mobile", async ({ page }) => {
    const items = page.getByRole("region", { name: "Why EstateHub" }).getByRole("listitem");
    for (const [width, expectedRows] of [[1440, 1], [768, 2], [390, 4]] as const) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      expect(await rows(page, items)).toBe(expectedRows);
    }
  });

  test("value strip reveals on entry and stays still for reduced motion", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 400 });
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.goto("/");

    const region = page.getByRole("region", { name: "Why EstateHub" });
    const list = region.getByRole("list");
    await expect(list).toHaveAttribute("data-motion", "pending");
    await list.scrollIntoViewIfNeeded();
    await expect(list).toHaveAttribute("data-motion", "entered");

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.reload();
    await expect(list).not.toHaveAttribute("data-motion");
    await expect(region.getByText("Verified properties")).toBeVisible();
  });

  test("featured cards: three, two, then one per row", async ({ page }) => {
    const cards = page.getByRole("region", { name: "Discover our handpicked properties" }).getByRole("article");
    for (const [width, expectedRows] of [[1440, 1], [768, 2], [390, 3]] as const) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      expect(await rows(page, cards)).toBe(expectedRows);
    }
  });

  test("investment banner stacks copy before the photograph", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const banner = page.getByRole("region", { name: "Grow your wealth through real estate" });

    const action = (await banner.getByRole("link", { name: "Start investing" }).boundingBox())!;
    const photo = (await banner.locator("img").boundingBox())!;
    expect(action.y + action.height).toBeLessThanOrEqual(photo.y);
  });

  test("process steps stack vertically with vertical connectors", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const steps = page.getByRole("region", { name: "Get started in 3 simple steps" }).getByRole("listitem");

    expect(await rows(page, steps)).toBe(3);
    const connectors = await steps.evaluateAll((items) =>
      items.map((item) => {
        const rule = getComputedStyle(item, "::before");
        return rule.content === "none" ? null : { width: rule.width, height: rule.height };
      }),
    );
    expect(connectors).toEqual([null, { width: "1px", height: "24px" }, { width: "1px", height: "24px" }]);
  });

  test("footer keeps every group visible, two per row on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const footer = page.getByRole("contentinfo");

    for (const group of ["Platform", "Company", "Support"]) {
      await expect(footer.getByRole("navigation", { name: group })).toBeVisible();
    }
    const [platform, company] = await Promise.all(
      ["Platform", "Company"].map((name) => footer.getByRole("navigation", { name }).boundingBox()),
    );
    expect(platform!.y).toBe(company!.y);
    await expect(footer.getByRole("form", { name: "Newsletter sign-up" }).getByLabel("Email address")).toBeVisible();
  });
});

test.describe("login page recomposition", () => {
  // Wide desktop splits 55/45 like the reference; tablets and compact desktops give the form
  // 55%; phones stack a short image band above the form.
  const LAYOUTS = [
    { width: 1536, height: 1024, split: 55, copy: true, points: true },
    { width: 1280, height: 800, split: 55, copy: true, points: true },
    { width: 1024, height: 768, split: 45, copy: true, points: false },
    { width: 768, height: 1024, split: 45, copy: false, points: false },
    { width: 390, height: 844, split: 0, copy: false, points: false },
    { width: 320, height: 640, split: 0, copy: false, points: false },
  ];

  for (const { width, height, split, copy, points } of LAYOUTS) {
    test(`${width}×${height}: ${split ? `${split}/${100 - split} split` : "stacked"}, no sideways scroll`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height });
      await page.goto("/login");
      await expect(page.getByRole("button", { name: "Log in" })).toBeEnabled();

      const layout = await page.evaluate(() => {
        const viewport = document.documentElement.clientWidth;
        const panel = document.querySelector("main > section")!.getBoundingClientRect();
        return {
          overflow: document.documentElement.scrollWidth - viewport,
          panelStart: Math.round((panel.left / viewport) * 100),
        };
      });
      expect(layout).toEqual({ overflow: 0, panelStart: split });

      const statement = page.getByRole("complementary").getByText("Buy, rent, invest");
      await expect(statement).toBeVisible({ visible: copy });
      await expect(page.getByRole("complementary").getByRole("list")).toBeVisible({ visible: points });

      // The heading and both fields are on the first screen; nothing hides the guidance.
      await expect(page.getByRole("heading", { name: "Welcome back" })).toBeInViewport();
      await expect(page.getByLabel("Password", { exact: true })).toBeInViewport();
      await expect(page.getByText("Need access? Contact your administrator.")).toBeVisible();

      await testInfo.attach(`login-${width}x${height}`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: "image/png",
      });
    });
  }

  test("short landscape scrolls the page and keeps every control reachable", async ({ page }) => {
    await page.setViewportSize({ width: 844, height: 390 });
    await page.goto("/login");
    const submit = page.getByRole("button", { name: "Log in" });
    await expect(submit).toBeEnabled();

    expect(await page.evaluate(() => document.documentElement.scrollHeight > innerHeight)).toBe(true);
    await submit.scrollIntoViewIfNeeded();
    await expect(submit).toBeInViewport();
    await expect(page.getByText("Need access? Contact your administrator.")).toBeVisible();
  });

  test("200% zoom reflows without sideways scroll and the form stays usable", async ({ browser }) => {
    // 1536×1024 at 200% is a 768×512 CSS viewport at 2× density.
    const context = await browser.newContext({ viewport: { width: 768, height: 512 }, deviceScaleFactor: 2 });
    const page = await context.newPage();
    await page.goto("/login");
    const submit = page.getByRole("button", { name: "Log in" });
    await expect(submit).toBeEnabled();

    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);
    await page.getByLabel("Email address").fill("someone@estatehub.example");
    await submit.click();
    // The field error appears beside its input, unclipped, and the button stays reachable.
    await expect(page.getByText("Enter your password.")).toBeVisible();
    await submit.scrollIntoViewIfNeeded();
    await expect(submit).toBeInViewport();
    await context.close();
  });
});

test.describe("login page screenshots", () => {
  for (const [name, viewport] of [
    ["desktop", { width: 1536, height: 1024 }],
    ["tablet", { width: 768, height: 1024 }],
    ["mobile", { width: 390, height: 844 }],
  ] as const) {
    test(`${name} matches its baseline`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/login");
      await expect(page.getByRole("button", { name: "Log in" })).toBeEnabled();
      await page.evaluate(async () => {
        await document.fonts.ready;
        await Promise.all([...document.images].map((image) => image.decode()));
      });
      // Baselines are per platform (Playwright suffixes them, e.g. -chromium-darwin).
      await expect(page).toHaveScreenshot(`login-${name}.png`, {
        fullPage: true,
        animations: "disabled",
        maxDiffPixelRatio: 0.01,
      });
    });
  }
});
