import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";

const dir = fileURLToPath(new URL("../fixtures/", import.meta.url));
const load = (name: string) => JSON.parse(readFileSync(dir + name + ".json", "utf-8"));
export const ROUTES: Record<string, string> = {
  "/api/demo/summary": "demo-summary", "/api/research/release-gate": "release-gate",
  "/api/research/summary": "research-summary", "/api/research/strategies": "strategies",
  "/api/research/validation": "validation", "/api/market/tracks": "market-tracks", "/api/market/scan": "market-scan",
  "/api/portfolio/ledgers": "portfolio-ledgers", "/api/ops/authorizations": "ops-authorizations",
  "/api/market/uk": "market-uk", "/api/pipeline/latest": "pipeline-latest", "/api/pipeline/history": "pipeline-history",
  "/api/day-trader/summary": "day-trader-summary",
  "/api/day-trader/readiness": "day-trader-readiness",
};

/** Mock every API route. ``overrides`` maps a path to a payload, or to a number for an HTTP error. */
export async function mockApi(page: Page, overrides: Record<string, unknown> = {}) {
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") return route.fulfill({ status: 405 });
    if (path in overrides) {
      const o = overrides[path];
      return typeof o === "number" ? route.fulfill({ status: o, body: "{}" }) : route.fulfill({ json: o });
    }
    const name = ROUTES[path];
    return name ? route.fulfill({ json: load(name) }) : route.fulfill({ status: 404, body: "{}" });
  });
}
export const fixture = load;
