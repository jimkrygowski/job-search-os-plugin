import { expect, test, type Page } from "@playwright/test";
import type { Payload } from "../shared/types.ts";

const EMPTY = "http://127.0.0.1:8797/";
const LEGACY = "http://127.0.0.1:8796/";

// Every test fails on a console error, an uncaught exception, a CSP
// violation, or any JavaScript dialog (e.g. from a script in notes.md).
let problems: string[] = [];
test.beforeEach(async ({ page }) => {
  problems = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("dialog", async (d) => { problems.push(`dialog: ${d.message()}`); await d.dismiss(); });
});
test.afterEach(() => expect(problems).toEqual([]));

async function payload(page: Page): Promise<Payload> {
  return (await page.request.get("/api/data")).json();
}

const drawer = (page: Page) => page.locator(".drawer");
const closeButton = (page: Page) => page.getByRole("button", { name: "Close", exact: true });
async function tiles(page: Page): Promise<string[]> {
  await expect(page.locator(".tile-value").first()).toBeVisible();
  return page.locator(".tile-value").allTextContents();
}
const node = (page: Page, label: string) =>
  page.locator(".sankey .node").filter({ has: page.locator(".node-label", { hasText: new RegExp(`^${label}$`) }) });

test.describe("page load", () => {
  test("renders the summary, all three views and the warnings", async ({ page }) => {
    const data = await payload(page);
    await page.goto("/");
    await expect(page).toHaveTitle("Job Search Dashboard");
    const [total, active, , , stalled] = await tiles(page);
    expect(total).toBe(String(data.records.length));
    expect(active).toBe(String(data.records.filter((r) => r.status === "active").length));
    expect(stalled).toBe(String(data.records.filter((r) => r.stalled).length));
    await expect(page.locator("#flow svg.sankey")).toBeVisible();
    await expect(page.locator("#conversion .conv-row")).toHaveCount(data.stages.length - 1);
    await expect(page.locator("#activity svg.activity")).toBeVisible();
    await expect(page.locator(".banner.warn")).toContainText(`${data.warnings.length} data warnings`);
  });

  test("the warnings banner can be dismissed", async ({ page }) => {
    await page.goto("/");
    await page.locator(".banner.warn").getByRole("button", { name: "Dismiss" }).click();
    await expect(page.locator(".banner.warn")).toBeHidden();
  });

  test("an API failure shows an error banner with the detail", async ({ page }) => {
    await page.route("**/api/data", (r) => r.fulfill({ status: 500, contentType: "application/json",
      body: JSON.stringify({ error: "tracker export failed", detail: "Traceback: boom" }) }));
    await page.goto("/");
    await expect(page.getByRole("alert")).toContainText("tracker export failed");
    await expect(page.getByRole("alert")).toContainText("Traceback: boom");
    problems = problems.filter((p) => !p.includes("500")); // the browser logs the failed fetch
  });
});

test.describe("drill-down drawer", () => {
  test("clicking a Sankey node lists its opportunities", async ({ page }) => {
    await page.goto("/");
    const node = page.locator(".sankey .node", { hasText: "Rejected" });
    const count = Number(await node.locator(".node-count").textContent());
    await node.click();
    await expect(drawer(page)).toBeVisible();
    await expect(page.locator("#drawer-title")).toHaveText(`Rejected (${count})`);
    await expect(page.locator(".opp-list li")).toHaveCount(count);
  });

  test("the × button closes the drawer and the scrim", async ({ page }) => {
    await page.goto("/");
    await page.locator(".sankey .node").first().click();
    await expect(drawer(page)).toBeVisible();
    await closeButton(page).click();
    await expect(drawer(page)).toBeHidden();
    await expect(page.locator(".scrim")).toBeHidden();
  });

  test("Escape and clicking the scrim also close it", async ({ page }) => {
    await page.goto("/");
    await page.locator(".sankey .node").first().click();
    await page.keyboard.press("Escape");
    await expect(drawer(page)).toBeHidden();
    await page.locator(".sankey .node").first().click();
    await page.locator(".scrim").click({ position: { x: 20, y: 20 } });
    await expect(drawer(page)).toBeHidden();
  });

  test("the drawer reopens after being closed, with fresh content", async ({ page }) => {
    await page.goto("/");
    await page.locator(".sankey .node", { hasText: "Rejected" }).click();
    await closeButton(page).click();
    await page.locator(".sankey .node", { hasText: "Accepted" }).click();
    await expect(drawer(page)).toBeVisible();
    await expect(page.locator("#drawer-title")).toHaveText("Accepted (1)");
  });

  test("clicking a Sankey link lists the opportunities on it", async ({ page }) => {
    await page.goto("/");
    await page.locator(".sankey .link").first().click({ force: true });
    await expect(drawer(page)).toBeVisible();
    await expect(page.locator(".opp-list li").first()).toBeVisible();
    expect(await page.locator("#drawer-title").textContent()).toContain("→");
  });

  test("a conversion row opens the opportunities that reached that stage", async ({ page }) => {
    await page.goto("/");
    await page.locator(".conv-row").nth(1).click();
    await expect(page.locator("#drawer-title")).toContainText("Reached Applied");
  });

  test("an opportunity shows its fields, timeline and notes; back returns to the list", async ({ page }) => {
    await page.goto("/");
    await page.locator(".sankey .node", { hasText: "Accepted" }).click();
    await page.locator(".opp").first().click();
    await expect(page.locator("#drawer-title")).toHaveText("Acme Robotics — VP Engineering");
    await expect(page.locator(".fields")).toContainText("Closed: Accepted");
    await expect(page.locator(".timeline li")).toHaveCount(7); // 6 stages + closed
    await expect(page.locator(".notes h4")).toHaveText("Interview Review (2026-06-28)");
    await expect(page.locator(".notes a")).toHaveAttribute("rel", "noopener noreferrer");
    await page.getByRole("button", { name: "← All in this group" }).click();
    await expect(page.locator("#drawer-title")).toHaveText("Accepted (1)");
  });

  test("hostile notes render as inert text", async ({ page }) => {
    await page.goto("/");
    await page.locator(".sankey .node", { hasText: "Rejected" }).click();
    await page.locator(".opp", { hasText: "Bluefin Health" }).click();
    const notes = page.locator(".notes");
    await expect(notes).toContainText("<script>alert('xss')</script>");
    await expect(notes.locator("script, img")).toHaveCount(0);
    await expect(notes.locator("a")).toHaveCount(0); // javascript: link is not linked
  });

  test("an opportunity with no notes.md says so", async ({ page }) => {
    await page.route("**/api/notes/**", (r) => r.fulfill({ status: 404, body: "" }));
    await page.goto("/");
    await page.locator(".sankey .node", { hasText: "Accepted" }).click();
    await page.locator(".opp").first().click();
    await expect(page.locator(".notes")).toContainText("No notes.md");
    problems = problems.filter((p) => !p.includes("404"));
  });
});

test.describe("keyboard", () => {
  test("a node is reachable and opens with Enter; focus is trapped, then returned", async ({ page }) => {
    await page.goto("/");
    const node = page.locator(".sankey .node").first();
    await node.focus();
    await page.keyboard.press("Enter");
    await expect(drawer(page)).toBeVisible();
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => !!document.activeElement?.closest(".drawer"))).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(drawer(page)).toBeHidden();
    await expect(node).toBeFocused();
  });

  test("focusing an activity column shows its tooltip", async ({ page }) => {
    await page.goto("/");
    await page.locator(".activity .hit").first().focus();
    await expect(page.locator(".tooltip")).toBeVisible();
    await expect(page.locator(".tooltip")).toContainText("Week of");
    await page.locator(".activity .hit").first().blur();
    await expect(page.locator(".tooltip")).toBeHidden();
  });
});

test.describe("filters", () => {
  test("status filter updates every view and the URL", async ({ page }) => {
    const data = await payload(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Closed", exact: true }).click();
    await expect(page).toHaveURL(/#status=closed$/);
    const [total, active] = await tiles(page);
    expect(total).toBe(String(data.records.filter((r) => r.status === "closed").length));
    expect(active).toBe("0");
    await expect(page.locator(".sankey .node", { hasText: "Still in" })).toHaveCount(0);
  });

  test("source chips combine with OR and 'All sources' clears them", async ({ page }) => {
    const data = await payload(page);
    const count = (srcs: string[]) => String(data.records.filter((r) => srcs.includes(r.source || "Unknown")).length);
    await page.goto("/");
    await page.getByRole("button", { name: "Referral", exact: true }).click();
    expect((await tiles(page))[0]).toBe(count(["Referral"]));
    await page.getByRole("button", { name: "Job Alert", exact: true }).click();
    expect((await tiles(page))[0]).toBe(count(["Referral", "Job Alert"]));
    await expect(page.getByRole("button", { name: "Referral", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "All sources" }).click();
    expect((await tiles(page))[0]).toBe(String(data.records.length));
  });

  test("a bookmarked URL restores its filters", async ({ page }) => {
    await page.goto("/#status=active&sources=Referral");
    await expect(page.getByRole("button", { name: "Active", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Referral", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Recruiter Inbound", exact: true })).toHaveAttribute("aria-pressed", "false");
  });

  test("a filter that matches nothing says so, and can be undone", async ({ page }) => {
    await page.goto("/#range=30&sources=Referral&status=closed");
    await expect(page.getByRole("heading", { name: "Nothing matches these filters" })).toBeVisible();
    await page.getByRole("button", { name: "All time" }).click();
    await expect(page.locator("#flow")).toBeVisible();
  });
});

test.describe("table views", () => {
  for (const id of ["flow", "conversion", "activity"]) {
    test(`${id} toggles to a table and back`, async ({ page }) => {
      await page.goto("/");
      const section = page.locator(`#${id}`);
      await section.getByRole("button", { name: "Show as table" }).click();
      await expect(section.locator("table tbody tr").first()).toBeVisible();
      await expect(section.locator("svg")).toHaveCount(0);
      await section.getByRole("button", { name: "Show as chart" }).click();
      await expect(section.locator("table")).toHaveCount(0);
    });
  }
});

test.describe("layout and themes", () => {
  test("no horizontal page overflow at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator("#flow")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("resizing re-renders the Sankey at the new width", async ({ page }) => {
    await page.goto("/");
    const before = Number(await page.locator("svg.sankey").getAttribute("width"));
    await page.setViewportSize({ width: 900, height: 900 });
    await expect.poll(async () => Number(await page.locator("svg.sankey").getAttribute("width"))).toBeLessThan(before);
  });

  for (const colorScheme of ["light", "dark"] as const) {
    test(`${colorScheme} theme uses its own surface and ink`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      await page.goto("/");
      const [bg, ink] = await page.evaluate(() => {
        const s = getComputedStyle(document.body);
        return [s.backgroundColor, s.color];
      });
      expect(bg).toBe(colorScheme === "light" ? "rgb(249, 249, 247)" : "rgb(13, 13, 13)");
      expect(ink).toBe(colorScheme === "light" ? "rgb(11, 11, 11)" : "rgb(255, 255, 255)");
    });
  }
});

test.describe("other workspaces", () => {
  test("an empty workspace shows the empty state", async ({ page }) => {
    await page.goto(EMPTY);
    await expect(page.getByRole("heading", { name: "No opportunities yet" })).toBeVisible();
    await expect(page.locator(".tile")).toHaveCount(0);
  });

  test("a v0.1 workspace renders with legacy stages mapped and the history banner", async ({ page }) => {
    await page.goto(LEGACY);
    await expect(page.locator(".banner.info")).toContainText("History isn't recorded yet");
    await expect(node(page, "Recruiter Screen")).toHaveCount(1);
    await expect(node(page, "Interview Loop")).toHaveCount(1);
    await expect(page.locator(".sankey .link.inferred").first()).toBeVisible();
    await page.locator(".banner.info").getByRole("button", { name: "Dismiss" }).click();
    await expect(page.locator(".banner.info")).toBeHidden();
  });
});
