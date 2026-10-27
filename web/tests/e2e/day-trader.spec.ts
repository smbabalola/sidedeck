import { expect, test } from "@playwright/test";
import { fixture, mockApi } from "./mock";

test("Day Trader desk distinguishes offline research, virtual configuration and simulated P&L", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/day-trader");
  await expect(page.getByRole("heading", { level: 1, name: "Day Trader" })).toBeVisible();
  await expect(page.getByText("Execution locked")).toBeVisible();
  await expect(page.getByText("eToro Demo · NOT RELEASED")).toBeVisible();
  const pipeline = page.getByRole("region", { name: "Autonomous trading pipeline" });
  await expect(pipeline).toBeVisible();
  await expect(pipeline.getByRole("listitem")).toHaveCount(5);
  await expect(pipeline.getByText("Demo transport locked")).toBeVisible();
  await expect(pipeline.getByText("2 of 5 stages implemented offline")).toBeVisible();
  await expect(page.getByRole("region", { name: "DAY simulated accounting" })).toBeVisible();
  await expect(page.getByRole("region", { name: "DAY risk configuration" })).toBeVisible();
  await expect(page.getByText("Research only", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /buy|sell|order|close position|submit|execute|allocate/i })).toHaveCount(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
});

test("Day Trader desk supports watchlist inspection without claiming broker orders", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/day-trader");
  const watchlist = page.getByRole("region", { name: "Candidate watchlist" });
  const inspection = page.getByRole("region", { name: "Selected candidate" });
  await expect(watchlist.getByRole("table", { name: "Day Trader research candidate watchlist" })).toBeVisible();
  await expect(watchlist.getByText("SYNTH", { exact: true })).toBeVisible();
  await expect(inspection.getByText("WATCHLIST")).toBeVisible();
  await expect(inspection.getByText("Price chart unavailable")).toBeVisible();
  await expect(inspection.getByText("Fixture/research only")).toBeVisible();
  await page.getByLabel("Filter research candidates").fill("NOT-FOUND");
  await expect(inspection.getByText(/No candidates match your filter/)).toBeVisible();
  await expect(watchlist.getByRole("row")).toHaveCount(2); // header and no-matches row
  await page.getByLabel("Filter research candidates").fill("SYNTH");
  await expect(inspection.getByText("Price chart unavailable")).toBeVisible();
  await expect(page.getByRole("button", { name: /buy|sell|order|close position|submit|execute|allocate/i })).toHaveCount(0);
});

test("Day Trader symbol filter keeps plan decisions research-only", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/day-trader");
  await page.getByRole("tab", { name: "Opportunities & plans" }).click();
  const watchlist = page.getByRole("region", { name: /Watchlist/ });
  const plans = page.getByRole("region", { name: /Entry \/ exit plans/ });
  await expect(watchlist.getByText("SYNTH", { exact: true })).toBeVisible();
  await expect(plans.getByText("WATCHLIST", { exact: true })).toBeVisible();
  await expect(plans.getByText("No broker order permission.")).toBeVisible();
  await page.getByLabel("Search Day Trader symbols").fill("NOTPRESENT");
  await expect(watchlist.getByText(/No candidates match/)).toBeVisible();
  await expect(plans.getByText(/No plans match/)).toBeVisible();
});

test("Day Trader audit rows are evidence metadata, not historical trade claims", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/day-trader");
  await page.getByRole("tab", { name: "Run history & audit" }).click();
  const history = page.getByRole("table", { name: "Saved Day Trader research runs" });
  await expect(history.getByRole("row")).toHaveCount(3);
  await expect(page.getByText(/historical rows are metadata/)).toBeVisible();
  await page.getByLabel("Find a saved run").fill("run-old-001");
  await expect(history.getByRole("row")).toHaveCount(2);
  await expect(page.getByRole("region", { name: /Rejected/ })).toBeVisible();
});

test("Day Trader readiness has five explicit gates and no broker unlock buttons", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/day-trader");
  const tab = page.getByRole("tab", { name: "Execution readiness" });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("Genuine five-minute data")).toBeVisible();
  await expect(page.getByText("Autonomous eToro Demo execution")).toBeVisible();
  await expect(page.getByText("Not released", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Readiness limits" })).toBeVisible();
  await expect(page.getByRole("button", { name: /unlock|approve|buy|sell|order|close position|submit|execute/i })).toHaveCount(0);
});

test("Day Trader fails closed on forged readiness and never shows success", async ({ page }) => {
  const forged = { ...fixture("day-trader-readiness"), demo_release: "RELEASED" };
  await mockApi(page, { "/api/day-trader/readiness": forged });
  await page.goto("/#/day-trader");
  await page.getByRole("tab", { name: "Execution readiness" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /did not match the expected contract/ })).toBeVisible();
  await expect(page.getByText("Autonomous eToro Demo execution")).toHaveCount(0);
});
