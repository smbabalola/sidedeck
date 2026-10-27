import { defineConfig, devices } from "@playwright/test";

// E2E runs against the Vite dev server with every /api call mocked from tests/fixtures.
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  fullyParallel: true,
  workers: process.env.CI ? 1 : 2,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5199", trace: "retain-on-failure" },
  webServer: { command: "npx vite preview --host 127.0.0.1 --port 5199 --strictPort", url: "http://127.0.0.1:5199", reuseExistingServer: false, timeout: 120_000 },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "tablet", use: { ...devices["Desktop Chrome"], viewport: { width: 834, height: 1112 }, hasTouch: true } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
});
