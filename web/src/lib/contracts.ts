// Typed contracts for the loopback read-only API. Every payload is validated at
// runtime; a payload that fails validation is treated as an error, never guessed at.

export type Provenance = "REAL_DATA" | "DEMO_BROKER" | "SIMULATION" | "SYNTHETIC_FIXTURE" | "UNAVAILABLE";

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isNumStr = (v: unknown): v is string | null => v === null || (isStr(v) && v.length < 41 && Number.isFinite(Number(v)));
const isArr = Array.isArray;

// --- /api/demo/summary ---------------------------------------------------------------
export type Book = { id: string; positions: number | null; allocation_status: string };
export type DemoSummary = {
  schema_version: 1; source: "LOCAL_BASELINE_ONLY"; execution_enabled: false;
  baseline_status: string; captured_at: string | null; protected_positions: number | null;
  reconciliation_status: string; available_cash_usd_status: string; unrealized_pnl_status: string;
  books: Book[];
  fresh_snapshot: null | { observed_at: string; reconciliation_status: string; discrepancy_count: number | null; available_cash_usd_status: string; books: Book[] };
};
export function isDemoSummary(d: unknown): d is DemoSummary {
  return isObj(d) && d.schema_version === 1 && d.source === "LOCAL_BASELINE_ONLY" && d.execution_enabled === false
    && isArr(d.books) && d.books.every(b => isObj(b) && isStr(b.id) && (b.positions === null || isNum(b.positions)));
}

// --- /api/research/summary -----------------------------------------------------------
export type ResearchSummary = { status: string; valuation: string; execution_enabled: false; agents: { id: string; status: string; evidence_count: number }[] };
export function isResearchSummary(d: unknown): d is ResearchSummary {
  return isObj(d) && d.execution_enabled === false && isStr(d.status) && isArr(d.agents)
    && d.agents.every(a => isObj(a) && isStr(a.id) && isStr(a.status) && isNum(a.evidence_count));
}

// --- /api/research/strategies --------------------------------------------------------
export type StrategyEntry = { id: string; version: string; parameters: Record<string, string>; holding_period: [number, number]; execution_assumption: string; acceptance: string };
export type StrategyCatalogue = { execution_enabled: false; strategies: StrategyEntry[] };
export function isStrategyCatalogue(d: unknown): d is StrategyCatalogue {
  return isObj(d) && d.execution_enabled === false && isArr(d.strategies)
    && d.strategies.every(s => isObj(s) && isStr(s.id) && isStr(s.version) && isArr(s.holding_period));
}

// --- /api/research/validation --------------------------------------------------------
export type ValidationDataset = {
  ticker: string; instrument_id: string | null; start: string; end: string; observations: number;
  provenance: string | null; feed: string | null; adjustment: string | null;
  strategies: { id: string; status: string; metrics: Record<string, string | number | null> }[];
  benchmark?: { convention: string; total_return: string; return: string | null; max_drawdown: string | null; corporate_action_status: string };
};
export type StrategyValidation = { execution_enabled: false; status: string; datasets: ValidationDataset[] };
export function isStrategyValidation(d: unknown): d is StrategyValidation {
  return isObj(d) && d.execution_enabled === false && isArr(d.datasets)
    && d.datasets.every(x => isObj(x) && isStr(x.ticker) && isArr(x.strategies));
}

// --- /api/research/release-gate ------------------------------------------------------
export type EtoroDemoStatus = { broker_priority: string; secondary_broker: string; execution_release: string; real_execution: string; transport: string; baseline: string; ownership: string; agent_portfolios: string; open_risks: string[] };
export type ReleaseGate = {
  overall_status: "NO_GO"; release_enabled: false; paper_order_submission: "DISABLED"; broker_execution: "DISABLED";
  engineering_rehearsal: string; human_approval: string; account_mapping: string; broker_reconciliation: string;
  kill_switch: string; protected_baseline: string; blocking_controls: string[];
  rehearsal: { status: string; broker_execution: "DISABLED"; final_state?: string | null; event_count?: number | null };
  etoro_demo?: EtoroDemoStatus;
};
export function isReleaseGate(d: unknown): d is ReleaseGate {
  return isObj(d) && d.overall_status === "NO_GO" && d.release_enabled === false && d.paper_order_submission === "DISABLED"
    && d.broker_execution === "DISABLED" && isArr(d.blocking_controls) && d.blocking_controls.every(isStr) && isObj(d.rehearsal);
}

// --- /api/market/tracks --------------------------------------------------------------
export type TrackId = "DAY" | "SWING" | "POSITION";
export const TRACKS: TrackId[] = ["DAY", "SWING", "POSITION"];
export type RiskBudget = { risk_per_trade_pct: string; max_positions: number; max_drawdown_pct: string; max_daily_loss_pct: string; max_orders_per_day: number; exit_policy: string; virtual_capital: string; basis: string };
export type MarketTrack = {
  track: TrackId; mode: string; horizon_trading_days: [number, number]; data_status: string; usable_sources: string[];
  filters: { min_price: string; min_dollar_adv: string; min_sessions: number; spread_required: boolean };
  shortlist_sizes: { quant: number; research: number }; jobs: { job_id: string; next_run_utc: string }[];
  execution: "DISABLED"; risk_budget: RiskBudget;
};
export type MarketTracks = {
  execution_enabled: false; generated_at: string;
  universe: { status: string; instruments?: number; history_basis?: string; retrieved_at?: string; reason?: string };
  price_coverage: { status: string; counts?: Record<string, number>; benchmark_status?: string; reason?: string };
  tracks: MarketTrack[]; decision_engine: { execution_permission: string; agent_only_cap: string };
};
export function isMarketTracks(d: unknown): d is MarketTracks {
  return isObj(d) && d.execution_enabled === false && isArr(d.tracks) && d.tracks.length === 3
    && d.tracks.every(t => isObj(t) && t.execution === "DISABLED" && TRACKS.includes(t.track as TrackId)
      && isObj(t.risk_budget) && isArr(t.jobs) && isObj(t.filters))
    && isObj(d.universe) && isObj(d.price_coverage) && isObj(d.decision_engine);
}

// --- /api/market/scan ----------------------------------------------------------------
export type ScanInstrument = {
  canonical_id: string; ticker: string; exchange: string; sessions: number; regime: string;
  breakout_20: boolean; sweep_reversal_20: boolean; above_sma200: boolean | null; event_flags: string[];
  last_close: string | null; ret_5: string | null; ret_20: string | null; ret_60: string | null; ret_126: string | null;
  rs_60: string | null; atr_pct: string | null; vol20: string | null; dollar_adv20: string | null;
  unusual_volume: string | null; gap_pct: string | null;
};
export type ScanCandidate = { canonical_id: string; rank: number; score: string | null; components: Record<string, string | null>; missing: string[]; research: boolean };
export type LoadedScan = {
  status: "LOADED"; execution_enabled: false; provenance: "REAL_DATA" | "SYNTHETIC_FIXTURE"; source_id: string;
  data_basis: string; generated_at: string; cutoff: string; universe_size: number; scanned: number;
  excluded: Record<string, number>; duration_seconds: number; instruments: ScanInstrument[];
  tracks: Record<TrackId, { candidates: ScanCandidate[]; filtered: Record<string, number> }>; note: string;
};
export type ScanSnapshot = { status: "UNAVAILABLE"; execution_enabled: false; reason: string } | LoadedScan;
const NUM_FIELDS = ["last_close", "ret_5", "ret_20", "ret_60", "ret_126", "rs_60", "atr_pct", "vol20", "dollar_adv20", "unusual_volume", "gap_pct"] as const;
export function isScanSnapshot(d: unknown): d is ScanSnapshot {
  if (!isObj(d) || d.execution_enabled !== false) return false;
  if (d.status === "UNAVAILABLE") return isStr(d.reason);
  if (d.status !== "LOADED" || (d.provenance !== "REAL_DATA" && d.provenance !== "SYNTHETIC_FIXTURE")) return false;
  if (!isArr(d.instruments) || !isObj(d.tracks)) return false;
  const tracks = d.tracks;
  return d.instruments.every(i => isObj(i) && isStr(i.canonical_id) && isStr(i.exchange) && NUM_FIELDS.every(f => isNumStr(i[f])))
    && TRACKS.every(t => isObj(tracks[t]) && isArr((tracks[t] as Record<string, unknown>).candidates));
}
