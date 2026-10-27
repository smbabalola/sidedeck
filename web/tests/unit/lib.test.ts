import { describe, expect, it } from "vitest";
import marketScan from "../fixtures/market-scan.json";
import marketTracks from "../fixtures/market-tracks.json";
import releaseGate from "../fixtures/release-gate.json";
import demo from "../fixtures/demo-summary.json";
import dayReadiness from "../fixtures/day-trader-readiness.json";
import marketUk from "../fixtures/market-uk.json";
import { isDayTraderReadiness, isDayTraderSummary, isDemoSummary, isMarketTracks, isReleaseGate, isScanSnapshot, isUkMarkets } from "../../src/lib/contracts";
import { compactUsd, gbp, pct, plainPct, tone, words } from "../../src/lib/format";
import { href, parseRoute } from "../../src/lib/router";

describe("contracts accept real backend payloads and reject unsafe ones", () => {
  it("accepts the generated fixtures", () => {
    expect(isScanSnapshot(marketScan)).toBe(true);
    expect(isMarketTracks(marketTracks)).toBe(true);
    expect(isReleaseGate(releaseGate)).toBe(true);
    expect(isDemoSummary(demo)).toBe(true);
  });
  it("rejects anything that claims execution is enabled", () => {
    expect(isScanSnapshot({ ...marketScan, execution_enabled: true })).toBe(false);
    expect(isMarketTracks({ ...marketTracks, execution_enabled: true })).toBe(false);
    expect(isReleaseGate({ ...releaseGate, overall_status: "GO" })).toBe(false);
    expect(isReleaseGate({ ...releaseGate, paper_order_submission: "ENABLED" })).toBe(false);
    expect(isDemoSummary({ ...demo, execution_enabled: true })).toBe(false);
    const tracks = structuredClone(marketTracks);
    tracks.tracks[0].execution = "ENABLED";
    expect(isMarketTracks(tracks)).toBe(false);
  });
  it("rejects unknown provenance and non-numeric values", () => {
    expect(isScanSnapshot({ ...marketScan, provenance: "LIVE" })).toBe(false);
    const bad = structuredClone(marketScan);
    bad.instruments[0].last_close = "abc";
    expect(isScanSnapshot(bad)).toBe(false);
    expect(isScanSnapshot({ status: "UNAVAILABLE", execution_enabled: false, reason: "none" })).toBe(true);
  });
});

describe("Day Trader contract", () => {
  it("accepts the persisted-run summary with object or array simulations", () => {
    const summary = {
      schema_version: 1, module: "DAY_TRADER", book: "DAY_TRADER_SKILL", mode: "RESEARCH_ONLY",
      enabled: true, execution_enabled: false, broker_execution: "DISABLED", data_status: "NO_SAVED_RUN",
      performance_status: "RESEARCH_ONLY", source: { name: "day-trader-skill", version: "2.0.0", commit: "fixture", license: "MIT", module_version: "1", verification: "verified", origin: "vendored" },
      capabilities: [{ id: "scanner", role: "scan", network_hosts_blocked: [], claude_only_not_used: "not used" }],
      opportunities: [], plans: [], simulations: { status: "EMPTY" }, rejected: [], errors: [], runs: [], latest: null,
      owner_actions: [], limitations: [],
    };
    expect(isDayTraderSummary(summary)).toBe(true);
    expect(isDayTraderSummary({ ...summary, simulations: [] })).toBe(true);
  });
});

describe("Day Trader readiness refuses forged execution states", () => {
  it("validates the exact offline gate sequence", () => {
    expect(isDayTraderReadiness(dayReadiness)).toBe(true);
  });
  it("rejects attempts to claim broker, strategy, or real trading release", () => {
    expect(isDayTraderReadiness({ ...dayReadiness, demo_release: "RELEASED" })).toBe(false);
    expect(isDayTraderReadiness({ ...dayReadiness, execution_enabled: true })).toBe(false);
    expect(isDayTraderReadiness({ ...dayReadiness, real_execution: "ENABLED" })).toBe(false);
    const forged = structuredClone(dayReadiness);
    forged.gates[4].status = "IMPLEMENTED_OFFLINE";
    expect(isDayTraderReadiness(forged)).toBe(false);
    const shortened = structuredClone(dayReadiness);
    shortened.gates.pop();
    expect(isDayTraderReadiness(shortened)).toBe(false);
  });
});

describe("formatting never invents values", () => {
  it("formats signed and plain percentages", () => {
    expect(pct("0.0523")).toBe("+5.2%");
    expect(pct("-0.01")).toBe("-1.0%");
    expect(pct(null)).toBe("—");
    expect(pct("NaN")).toBe("—");
    expect(plainPct("0.1", 0)).toBe("10%");
  });
  it("humanises tokens and keeps acronyms", () => {
    expect(words("NO_GO")).toBe("No go");
    expect(words("OWNER_CSV_IMPORT")).toBe("Owner CSV import");
    expect(words("SECONDS")).toBe("Seconds");
    expect(words(null)).toBe("—");
  });
  it("classifies tone and compacts money", () => {
    expect(tone("0.1")).toBe("gain");
    expect(tone("-0.1")).toBe("loss");
    expect(tone(null)).toBe("unknown");
    expect(compactUsd("53100000")).toBe("$53.1M");
  });
});

describe("router", () => {
  it("parses workspace and detail and falls back to overview", () => {
    expect(parseRoute("#/markets/US%3AMSFT")).toEqual({ workspace: "markets", detail: "US:MSFT" });
    expect(parseRoute("#/nope/x")).toEqual({ workspace: "overview", detail: null });
    expect(href("tracks", "SWING")).toBe("#/tracks/SWING");
  });
});

describe("UK markets contract (SD-097)", () => {
  const clone = () => JSON.parse(JSON.stringify(marketUk));
  it("accepts the generated fixture", () => {
    expect(isUkMarkets(marketUk)).toBe(true);
  });
  it("never accepts upgraded provenance or enabled execution", () => {
    expect(isUkMarkets({ ...clone(), execution_enabled: true })).toBe(false);
    expect(isUkMarkets({ ...clone(), broker_execution: "ENABLED" })).toBe(false);
    const realWithoutScan = clone(); realWithoutScan.genuine.provenance = "REAL_DATA";
    expect(isUkMarkets(realWithoutScan)).toBe(false);
    const fixtureAsReal = clone(); fixtureAsReal.fixture.provenance = "REAL_DATA";
    expect(isUkMarkets(fixtureAsReal)).toBe(false);
    const unavailableWithRows = clone(); unavailableWithRows.genuine.memberships = [{ canonical_id: "UK:X", index_id: "FTSE100", start: "2026-10-22", end: null, basis: "SNAPSHOT" }];
    expect(isUkMarkets(unavailableWithRows)).toBe(false);
    const evidence = clone(); evidence.evidence.provenance = "REAL_DATA";
    expect(isUkMarkets(evidence)).toBe(false);
  });
  it("formats pounds without inventing values", () => {
    expect(gbp("4.5")).toBe("£4.50");
    expect(gbp(null)).toBe("—");
    expect(gbp("abc")).toBe("—");
  });
});
