import { expect, test as base } from "@playwright/test";
import { fixture, mockApi } from "./mock";

const WORKSPACES = ["Overview", "Markets", "Trading tracks", "Agents", "Strategies", "Portfolio", "Operations"];

// Every test mocks the API and fails on any uncaught page error.
const test = base.extend<{ pageErrors: string[] }>({
  pageErrors: async ({ page }, use) => {
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await mockApi(page);
    await use(errors);
    expect(errors).toEqual([]);
  },
});

async function openNav(page: import("@playwright/test").Page) {
  const button = page.getByRole("button", { name: "Open navigation" });
  if (await button.isVisible()) await button.click();
}

test("every workspace renders without horizontal page overflow", async ({ page, pageErrors }) => {
  for (const [i, name] of WORKSPACES.entries()) {
    await page.goto("/");
    await openNav(page);
    await page.getByRole("link", { name, exact: true }).first().click();
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    expect(overflow, `${name} overflows horizontally`).toBe(false);
    expect(i).toBeGreaterThanOrEqual(0);
  }
});

test("execution lock and synthetic provenance are always visible", async ({ page, pageErrors }) => {
  await page.goto("/#/markets");
  await expect(page.getByRole("status").filter({ hasText: /Execution no go/i }).first()).toBeAttached();
  await expect(page.getByText(/not market data/i)).toBeVisible();
  await expect(page.getByText("Synthetic fixture").first()).toBeVisible();
  await expect(page.getByText("Real data")).toHaveCount(0);
});

test("no order, close or capital controls exist anywhere", async ({ page, pageErrors }) => {
  for (const ws of ["overview", "markets", "tracks", "agents", "strategies", "portfolio", "operations"]) {
    await page.goto(`/#/${ws}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: /buy|sell|order|close position|submit|execute|allocate/i })).toHaveCount(0);
  }
});

test("markets search, sort and keyboard drilldown", async ({ page, pageErrors }) => {
  await page.goto("/#/markets");
  const table = page.getByRole("table", { name: "Scanner results" });
  await expect(table.getByRole("row")).not.toHaveCount(1);
  await page.getByLabel("Search").fill("SYN007");
  await expect(table.getByRole("row")).toHaveCount(2);
  const row = table.getByRole("row").nth(1);
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/markets\/US%3ASYN007$/);
  await expect(page.getByText("US:SYN007 ·", { exact: false })).toBeVisible();
  await page.getByLabel("Search").fill("");
  const sortButton = table.getByRole("button", { name: /20d/ });
  await sortButton.click();
  await expect(table.getByRole("columnheader", { name: /20d/ })).toHaveAttribute("aria-sort", /descending/);
});

test("tracks tabs are keyboard operable and show risk budgets as configuration", async ({ page, pageErrors }) => {
  await page.goto("/#/tracks/SWING");
  const tab = page.getByRole("tab", { name: /Swing/ });
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await tab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/#\/tracks\/POSITION$/);
  await expect(page.getByText(/Not an authorization and not allocated capital/)).toBeVisible();
  await page.goto("/#/tracks/DAY");
  await expect(page.getByText(/spread data is required/)).toBeVisible();
});

test("API errors and contract violations show an error, never stale or guessed data", async ({ page, pageErrors }) => {
  void pageErrors;
  await page.unroute("**/api/**");
  const scan = fixture("market-scan");
  await mockApi(page, { "/api/market/scan": { ...scan, execution_enabled: true }, "/api/market/tracks": 503 });
  await page.goto("/#/markets");
  await expect(page.getByRole("alert").filter({ hasText: /did not match the expected contract/ }).first()).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: /answered 503/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).first().click();
});

test("theme toggle switches and persists", async ({ page, pageErrors }) => {
  await page.goto("/#/overview");
  const html = page.locator("html");
  const before = await html.getAttribute("data-theme");
  await page.getByRole("button", { name: /Switch to (light|dark) theme/ }).click();
  await expect(html).not.toHaveAttribute("data-theme", before ?? "");
  await page.reload();
  await expect(html).not.toHaveAttribute("data-theme", before ?? "");
});
