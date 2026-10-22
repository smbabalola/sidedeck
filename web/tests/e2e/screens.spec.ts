import { test } from "@playwright/test";
import { mockApi } from "./mock";

// Visual review aid: SIDEDECK_SCREENSHOTS=<dir> npx playwright test screens
const dir = process.env.SIDEDECK_SCREENSHOTS;
test.skip(!dir, "set SIDEDECK_SCREENSHOTS to a directory to capture screenshots");

for (const route of ["overview", "markets/US%3ASYN007", "tracks/SWING", "tracks/DAY", "agents", "strategies", "portfolio", "operations"]) {
  test(`screenshot ${route}`, async ({ page }, info) => {
    await mockApi(page);
    await page.emulateMedia({ colorScheme: process.env.SIDEDECK_THEME === "light" ? "light" : "dark" });
    await page.goto(`/#/${route}`);
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: `${dir}/${route.replace(/[/%]/g, "_")}-${process.env.SIDEDECK_THEME ?? "dark"}-${info.project.name}.png`, fullPage: info.project.name === "desktop" });
  });
}
