// Typed contracts for the loopback read-only API. Every payload is validated at
// runtime; a payload that fails validation is treated as an error, never guessed at.

export type Provenance = "REAL_DATA" | "DEMO_BROKER" | "SIMULATION" | "SYNTHETIC_FIXTURE" | "UNAVAILABLE";

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isNumStr = (v: unknown): v is string | null => v === null || (isStr(v) && v.trim() !== "" && v.length < 41 && Number.isFinite(Number(v)));
const isCount = (v: unknown): v is number => isNum(v) && Number.isInteger(v) && v >= 0;
const isCounts = (v: unknown): boolean => isObj(v) && Object.values(v).every(isCount);
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

// --- /api/portfolio/ledgers (SD-079 simulated ledgers) ------------------------------
export type TrackLedger =
  | { track: TrackId; status: "NOT_STARTED" | "UNAVAILABLE" }
  | { track: TrackId; status: "ACTIVE"; virtual_capital: string; cash: string; open_positions: number; open_cost_basis: string; realized_pnl: string; fees: string; entries: number; closes: number };
export type TrackLedgers = { provenance: "SIMULATION"; fill_basis: "SIMULATED_LOCAL"; execution_enabled: false; status: string; reason?: string; tracks: TrackLedger[] };
export function isTrackLedgers(d: unknown): d is TrackLedgers {
  return isObj(d) && d.provenance === "SIMULATION" && d.fill_basis === "SIMULATED_LOCAL" && d.execution_enabled === false
    && isStr(d.status) && isArr(d.tracks) && d.tracks.every(t => isObj(t) && TRACKS.includes(t.track as TrackId)
      && (t.status !== "ACTIVE" || (["virtual_capital", "cash", "open_cost_basis", "realized_pnl", "fees"].every(k => isNumStr(t[k]))
        && isCount(t.open_positions) && isCount(t.entries) && isCount(t.closes))));
}

// --- /api/ops/authorizations (SD-077 ledger) -----------------------------------------
export type AuthorizationUse = { digest_prefix: string; requests: number; outcomes: Record<string, number>; first_at: number; last_at: number };
export type AuthorizationLedger = { status: string; reason?: string; execution_enabled: false; authorizations: AuthorizationUse[] };
export function isAuthorizationLedger(d: unknown): d is AuthorizationLedger {
  return isObj(d) && d.execution_enabled === false && isStr(d.status) && isArr(d.authorizations)
    && d.authorizations.every(a => isObj(a) && isStr(a.digest_prefix) && isCount(a.requests) && isCounts(a.outcomes) && isNum(a.first_at) && isNum(a.last_at));
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
  if (!isStr(d.cutoff) || !/^\d{4}-\d{2}-\d{2}$/.test(d.cutoff) || !isStr(d.generated_at) || !isStr(d.source_id)
    || !isStr(d.data_basis) || !isNum(d.duration_seconds) || !isCount(d.scanned) || !isCount(d.universe_size)
    || !isCounts(d.excluded) || !isStr(d.note)) return false;
  const tracks = d.tracks;
  const candidateOk = (c: unknown) => isObj(c) && isStr(c.canonical_id) && isCount(c.rank) && isNumStr(c.score)
    && isObj(c.components) && Object.values(c.components).every(isNumStr) && isArr(c.missing) && c.missing.every(isStr)
    && typeof c.research === "boolean";
  return d.instruments.every(i => isObj(i) && isStr(i.canonical_id) && isStr(i.ticker) && isStr(i.exchange) && isCount(i.sessions)
      && isStr(i.regime) && isArr(i.event_flags) && NUM_FIELDS.every(f => isNumStr(i[f])))
    && TRACKS.every(t => {
      const tr = tracks[t];
      return isObj(tr) && isArr(tr.candidates) && tr.candidates.every(candidateOk) && isCounts(tr.filtered);
    });
}

// --- /api/market/uk (SD-097) -----------------------------------------------------------
export type UkSession = { date: string; open_utc: string; close_utc: string; early_close: boolean };
export type UkIdentity = {
  canonical_id: string; tidm: string | null; isin: string | null; name: string | null; quote_unit: string | null;
  source_id: string | null; source_unit: string | null; divisor: string | null; last_bar: string | null;
  retrieved_at: string | null; data_basis: string | null; last_close_gbp: string | null;
};
export type UkScan = {
  cutoff: string; universe: number; scanned: number; excluded: [string, string][]; scan_exclusions: Record<string, number>;
  rankings: Record<TrackId, { rank: number; canonical_id: string; score: string | null }[]>;
  filtered: Record<string, Record<string, number>>; decision_counts: Record<string, number>; signals: number; acceptance: string;
};
export type UkCandidate = { name: string; proposed_tidm: string; result: string; reasons: string[] };
export type UkMarkets = {
  schema_version: 1; market: "UK"; exchange: "LSE"; price_unit: "GBP"; execution_enabled: false; broker_execution: "DISABLED_FOR_UK";
  generated_at: string;
  calendar: {
    id: "XLON"; timezone: string; continuous_hours_local: string; half_day_close_local: string; source_status: string; corroboration: string;
    half_days_uncorroborated: string[]; rule_only_half_days: string[]; status_now: string;
    today: null | { date: string; is_session: boolean; open_utc: string | null; close_utc: string | null; early_close: boolean; closure_reason: string | null };
    next_sessions: UkSession[]; last_completed_session: string | null;
  };
  tracks: { track: TrackId; data_status: string; usable_sources: string[]; mode: string; execution: "DISABLED"; jobs: { job_id: string; enabled: boolean; next_run_utc: string | null }[] }[];
  genuine: {
    provenance: "UNAVAILABLE" | "REAL_DATA"; status: string; blocker?: string | null; cutoff?: string; import_status?: string;
    identities: UkIdentity[]; candidates: UkCandidate[]; rejected: number; warnings: number; scan?: UkScan;
    memberships: { canonical_id: string; index_id: string; start: string; end: string | null; basis: string }[];
  };
  fixture: null | (UkScan & { provenance: "SYNTHETIC_FIXTURE"; identities: UkIdentity[]; listing_rejections: [string, string][] });
  simulation: null | {
    provenance: "SIMULATION"; fill_basis: "SIMULATED_LOCAL"; intent_source: string; instrument: Record<string, string>;
    gbx_to_gbp: Record<string, string>; entry: Record<string, string | null>; exit: Record<string, string | null>;
    reconciliation: { status: string; cash_gbp: string | null; realized_pnl_gbp: string | null; fees_gbp: string | null; open_positions: number };
    scenarios: Record<string, string>;
  };
  report_reason: string | null; authorizations: Record<"A" | "B" | "C", string>;
  evidence: { provenance: "NO_DATA"; admitted_uk_strategies: number; agents: string; note: string };
};
const isPair = (v: unknown) => isArr(v) && v.length === 2 && isStr(v[0]) && isStr(v[1]);
const isOptStr = (v: unknown) => v === null || isStr(v);
const isUkIdentity = (i: unknown) => isObj(i) && isStr(i.canonical_id) && isNumStr(i.last_close_gbp)
  && ["tidm", "isin", "name", "quote_unit", "source_id", "source_unit", "divisor", "last_bar", "retrieved_at", "data_basis"].every(k => isOptStr(i[k]));
const isUkScan = (s: unknown) => isObj(s) && isStr(s.cutoff) && isCount(s.universe) && isCount(s.scanned) && isArr(s.excluded) && s.excluded.every(isPair)
  && isObj(s.rankings) && TRACKS.every(t => isArr((s.rankings as Record<string, unknown>)[t]) && ((s.rankings as Record<string, unknown[]>)[t]).every(r => isObj(r) && isCount(r.rank) && isStr(r.canonical_id) && isNumStr(r.score)))
  && isCounts(s.scan_exclusions) && isObj(s.filtered) && Object.values(s.filtered).every(isCounts) && isCounts(s.decision_counts) && isCount(s.signals) && isStr(s.acceptance);
export function isUkMarkets(d: unknown): d is UkMarkets {
  if (!isObj(d) || d.schema_version !== 1 || d.market !== "UK" || d.execution_enabled !== false || d.broker_execution !== "DISABLED_FOR_UK" || d.price_unit !== "GBP") return false;
  const c = d.calendar, g = d.genuine, f = d.fixture, s = d.simulation;
  if (!isObj(c) || c.id !== "XLON" || !isStr(c.source_status) || !isStr(c.status_now) || !isArr(c.next_sessions) || !isArr(c.half_days_uncorroborated)) return false;
  if (!isArr(d.tracks) || d.tracks.length !== 3 || !d.tracks.every(t => isObj(t) && TRACKS.includes(t.track as TrackId) && t.execution === "DISABLED" && isArr(t.jobs) && isStr(t.data_status))) return false;
  if (!isObj(g) || (g.provenance !== "UNAVAILABLE" && g.provenance !== "REAL_DATA") || !isStr(g.status) || !isArr(g.identities) || !g.identities.every(isUkIdentity)
    || !isArr(g.candidates) || !g.candidates.every(x => isObj(x) && isStr(x.name) && isStr(x.result) && isArr(x.reasons) && x.reasons.every(isStr))) return false;
  if (g.provenance === "REAL_DATA" && !isUkScan(g.scan)) return false;
  if (!isArr(g.memberships) || !g.memberships.every(m => isObj(m) && isStr(m.canonical_id) && isStr(m.index_id) && isStr(m.start) && isOptStr(m.end) && isStr(m.basis))) return false;
  if (g.provenance === "UNAVAILABLE" && g.memberships.length > 0) return false;
  if (g.provenance === "UNAVAILABLE" && g.identities.length > 0) return false;
  if (f !== null && !(isObj(f) && f.provenance === "SYNTHETIC_FIXTURE" && isUkScan(f) && isArr(f.identities) && f.identities.every(isUkIdentity))) return false;
  if (s !== null && !(isObj(s) && s.provenance === "SIMULATION" && s.fill_basis === "SIMULATED_LOCAL" && isObj(s.reconciliation) && isObj(s.scenarios))) return false;
  const e = d.evidence;
  if (!isObj(e) || e.provenance !== "NO_DATA" || !isCount(e.admitted_uk_strategies) || !isStr(e.agents)) return false;
  return isObj(d.authorizations) && isOptStr(d.report_reason);
}

// --- /api/pipeline/latest (SD-103/SD-104 integrated pipeline) ---------------------------
export type PipelineStrategy = {
  instrument: string; strategy_id: string; version: string; admission: string; admission_without_override: string | null; override: string | null;
  reasons: string[]; entry: string; exit: string; stop_loss: string; target: string; holding_period_sessions: number[];
  completed_trades: number; profit_factor: string | null; max_drawdown: string | null; oos_trades: number; oos_profit_factor: string | null; oos_ending_equity: string | null;
};
export type PipelineDecision = {
  symbol: string; direction: string; decision: string; strategy: string[]; reference_close: string | null; stop_loss: string | null; target: string | null;
  quantity: string | null; capital_required_usd: string | null; risk_reward: string | null; holding_period: string | null; reasons: string[];
};
export type PipelinePosition = {
  ref: string; canonical_id: string; strategy: string; opened: string; closed: string | null; fill_status: string; units: string | null;
  entry_price: string | null; exit_price: string | null; exit_reason: string | null; realized_pnl: string | null;
};
export type PipelineReplay = {
  provenance: "SIMULATION"; fill_basis: "SIMULATED_LOCAL"; basis: string; window: string[]; closed_trades: number; open_positions: number;
  total_return: string | null; max_drawdown: string | null; realized_pnl_usd: string | null; fees_usd: string | null; benchmark: string | null;
  cash_reconciliation: string; kill_switch: string; halt_reason: string | null;
  by_strategy: { strategy: string; closed_trades: number; win_rate: string | null; profit_factor: string | null; net_pnl_usd: string | null; verdict: string }[];
  positions: PipelinePosition[];
};
export type Pipeline =
  | { schema_version: 1; status: "UNAVAILABLE"; reason: string; execution_enabled: false; provenance: "UNAVAILABLE" }
  | {
    schema_version: 1; status: "AVAILABLE"; execution_enabled: false; provenance: "REAL_DATA" | "SYNTHETIC_FIXTURE"; mode: string; generated_at: string;
    cutoff_session: string | null; admission_through: string | null; data_freshness: Record<string, string | null>;
    market_data: { canonical_id: string; first: string; last: string; sessions: number; limitations: string[] }[];
    excluded_instruments: Record<string, string | null>;
    scanner: { status: string; scanned: number; shortlist: { canonical_id: string; rank: number; score: string | null }[]; filtered: [string, string][]; note: string | null };
    strategies: PipelineStrategy[];
    agents: { portfolio: string; instrument: string | null; status: string; reason: string; direction: string | null; model: string | null }[];
    decisions: PipelineDecision[];
    risk: { canonical_id: string; decision: string; reasons: string[]; capital_required_usd: string | null }[];
    orders: { intent_id: string; canonical_id: string; units: string | null; limit_price: string | null; stop_price: string | null; strategy: string; broker_route: string; status: string }[];
    no_trade: string | null; admitted_strategies: string[]; broker_routes: Record<string, string | null>; gates: Record<string, string | null>;
    replay: PipelineReplay | null;
  };
const isStrs = (v: unknown) => isArr(v) && v.every(isStr);
const isOptS = (v: unknown) => v === null || isStr(v);
export function isPipeline(d: unknown): d is Pipeline {
  if (!isObj(d) || d.schema_version !== 1 || d.execution_enabled !== false) return false;
  if (d.status === "UNAVAILABLE") return d.provenance === "UNAVAILABLE" && isStr(d.reason);
  if (d.status !== "AVAILABLE" || (d.provenance !== "REAL_DATA" && d.provenance !== "SYNTHETIC_FIXTURE")) return false;
  const sc = d.scanner;
  if (!isObj(sc) || !isStr(sc.status) || !isCount(sc.scanned) || !isArr(sc.shortlist)
    || !sc.shortlist.every(c => isObj(c) && isStr(c.canonical_id) && isCount(c.rank) && isNumStr(c.score))) return false;
  if (!isArr(d.strategies) || !d.strategies.every(s => isObj(s) && isStr(s.instrument) && isStr(s.strategy_id) && isStr(s.admission)
    && isStrs(s.reasons) && isCount(s.completed_trades) && isCount(s.oos_trades) && isNumStr(s.profit_factor) && isNumStr(s.oos_profit_factor)
    && isOptS(s.override))) return false;
  if (!isArr(d.agents) || !d.agents.every(a => isObj(a) && isStr(a.portfolio) && isStr(a.status) && isStr(a.reason))) return false;
  if (!isArr(d.decisions) || !d.decisions.every(x => isObj(x) && isStr(x.symbol) && isStr(x.decision) && isStr(x.direction) && isStrs(x.strategy)
    && isStrs(x.reasons) && ["reference_close", "stop_loss", "target", "quantity", "capital_required_usd", "risk_reward"].every(k => isNumStr(x[k])))) return false;
  if (!isArr(d.risk) || !isArr(d.orders) || !d.orders.every(o => isObj(o) && isStr(o.intent_id) && isStr(o.status) && o.status === "PROPOSED_NOT_SUBMITTED")) return false;
  if (!isOptS(d.no_trade) || !isStrs(d.admitted_strategies) || !isObj(d.gates) || !isObj(d.broker_routes) || !isArr(d.market_data)) return false;
  const r = d.replay;
  if (r === null) return true;
  return isObj(r) && r.provenance === "SIMULATION" && r.fill_basis === "SIMULATED_LOCAL" && isCount(r.closed_trades) && isCount(r.open_positions)
    && isNumStr(r.total_return) && isNumStr(r.max_drawdown) && isStr(r.cash_reconciliation) && isStr(r.kill_switch)
    && isArr(r.by_strategy) && r.by_strategy.every(b => isObj(b) && isStr(b.strategy) && isCount(b.closed_trades) && isNumStr(b.profit_factor) && isStr(b.verdict))
    && isArr(r.positions) && r.positions.every(p => isObj(p) && isStr(p.ref) && isStr(p.canonical_id) && isStr(p.strategy) && isNumStr(p.realized_pnl));
}
