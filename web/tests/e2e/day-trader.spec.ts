import { expect, test } from "@playwright/test";
import { mockApi } from "./mock";

test("Day Trader shows provenance, decisions and run history without controls", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/day-trader");
  await expect(page.locator("#main").getByRole("heading", { level: 2, name: "Day Trader" })).toBeVisible();
  await expect(page.getByText("UPSTREAM_FIXTURE_UNAPPROVED_SOURCE").first()).toBeVisible();
  await expect(page.getByText("NO_ADMITTED_STRATEGY_SIGNAL")).toBeVisible();
  await expect(page.getByText("Candidate fields")).toBeVisible();
  await expect(page.getByRole("cell", { name: /2026-10-27T13:05:00/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /buy|sell|order|close|execute|allocate/i })).toHaveCount(0);
});
