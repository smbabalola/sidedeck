import { useResource } from "../lib/api";
import { type PipelineDecision, type PipelinePosition, type PipelineStrategy, isPipeline } from "../lib/contracts";
import { num, plainPct, price, when, words } from "../lib/format";
import { Badge, type Column, DataTable, KeyValues, Metric, Panel, StateBlock } from "../components/ui";

const GATE_ORDER = ["ENGINEERING", "REAL_DATA", "STRATEGY_ADMISSION", "AI_RESEARCH", "BROKER", "PAPER_EXECUTION", "FORWARD_TESTING"];
const gateTone = (v: string | null) => (v ?? "").startsWith("VERIFIED") ? "accent" : (v ?? "").startsWith("BLOCKED") || (v ?? "").startsWith("FAILED") ? "blocked" : "neutral";

const strategyColumns: Column<PipelineStrategy>[] = [
  { key: "instrument", header: "Instrument", render: s => <span className="font-medium">{s.instrument}</span>, sortValue: s => s.instrument },
  { key: "strategy", header: "Strategy", render: s => `${s.strategy_id}@${s.version}`, sortValue: s => s.strategy_id },
  { key: "admission", header: "Admission", render: s => <span className="flex flex-wrap gap-1"><Badge tone={s.admission === "ADMITTED" ? "accent" : "neutral"}>{words(s.admission)}</Badge>{s.override && <Badge tone="attention" title="Fixture-only override; not evidence">Fixture override</Badge>}</span>, sortValue: s => s.admission },
  { key: "trades", header: "Trades", align: "right", render: s => s.completed_trades, sortValue: s => s.completed_trades, hideBelow: "sm" },
  { key: "pf", header: "PF", align: "right", render: s => num(s.profit_factor, 2), sortValue: s => (s.profit_factor === null ? null : Number(s.profit_factor)), hideBelow: "md" },
  { key: "oos", header: "OOS trades", align: "right", render: s => s.oos_trades, sortValue: s => s.oos_trades },
  { key: "oospf", header: "OOS PF", align: "right", render: s => num(s.oos_profit_factor, 2), sortValue: s => (s.oos_profit_factor === null ? null : Number(s.oos_profit_factor)), hideBelow: "md" },
  { key: "why", header: "Why", render: s => <span className="text-faint">{s.reasons.map(words).join("; ") || "—"}</span>, hideBelow: "lg" },
];

const decisionColumns: Column<PipelineDecision>[] = [
  { key: "symbol", header: "Symbol", render: d => <span className="font-medium">{d.symbol}</span>, sortValue: d => d.symbol },
  { key: "decision", header: "Decision", render: d => <Badge tone={d.decision === "ELIGIBLE" ? "accent" : d.decision === "REJECTED" ? "blocked" : "neutral"}>{words(d.decision)}</Badge>, sortValue: d => d.decision },
  { key: "direction", header: "Direction", render: d => words(d.direction), sortValue: d => d.direction },
  { key: "strategy", header: "Strategy", render: d => d.strategy.join(", ") || "—", hideBelow: "md" },
  { key: "entry", header: "Ref. close", align: "right", render: d => price(d.reference_close), hideBelow: "sm" },
  { key: "stop", header: "Stop", align: "right", render: d => price(d.stop_loss), hideBelow: "lg" },
  { key: "target", header: "Target", align: "right", render: d => price(d.target), hideBelow: "lg" },
  { key: "qty", header: "Units", align: "right", render: d => num(d.quantity, 4), hideBelow: "xl" },
  { key: "capital", header: "Capital incl. costs", align: "right", render: d => price(d.capital_required_usd), hideBelow: "xl" },
  { key: "why", header: "Reasons", render: d => <span className="text-faint">{d.reasons.map(words).join("; ")}</span>, hideBelow: "md" },
];

const positionColumns: Column<PipelinePosition>[] = [
  { key: "instrument", header: "Instrument", render: p => <span className="font-medium">{p.canonical_id}</span>, sortValue: p => p.canonical_id },
  { key: "strategy", header: "Strategy", render: p => p.strategy, hideBelow: "lg" },
  { key: "opened", header: "Opened", render: p => p.opened, sortValue: p => p.opened },
  { key: "closed", header: "Closed", render: p => p.closed ?? "Open", sortValue: p => p.closed, hideBelow: "sm" },
  { key: "fill", header: "Fill", render: p => words(p.fill_status), hideBelow: "md" },
  { key: "exit", header: "Exit reason", render: p => (p.exit_reason ? words(p.exit_reason) : "—"), sortValue: p => p.exit_reason, hideBelow: "sm" },
  { key: "pnl", header: "Realised P&L (sim.)", align: "right", render: p => price(p.realized_pnl), sortValue: p => (p.realized_pnl === null ? null : Number(p.realized_pnl)) },
];

export default function Engine() {
  const pipeline = useResource("/api/pipeline/latest", isPipeline);
  return <StateBlock resource={pipeline}>{d => {
    if (d.status === "UNAVAILABLE") return <Panel title="Trading engine" provenance="UNAVAILABLE"><p className="text-sm text-muted">{d.reason}</p></Panel>;
    const basis = d.provenance;
    const r = d.replay;
    return <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone="blocked">Broker execution not released</Badge>
        <Badge tone="neutral">Run: {words(d.mode)} · {when(d.generated_at)}</Badge>
        {d.data_freshness.status && <Badge tone={d.data_freshness.status === "CURRENT" ? "neutral" : "attention"}>Data {words(d.data_freshness.status)} (latest {d.data_freshness.latest_session ?? "—"})</Badge>}
      </div>
      <Panel title="Pipeline gates" provenance={null} subtitle="Each gate is reported separately. Green tests are not trading acceptance.">
        <ul className="grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">{GATE_ORDER.map(g => <li key={g} className="min-w-0 rounded border border-rule p-2">
          <p className="font-medium text-ink">{words(g)}</p>
          <p className="mt-1"><Badge tone={gateTone(d.gates[g] ?? null)}>{(d.gates[g] ?? "NOT_ASSESSED").split(" ")[0].replace(/_/g, " ")}</Badge></p>
          <p className="mt-1 text-2xs text-faint">{d.gates[g]}</p>
        </li>)}</ul>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Market opportunities" provenance={basis} subtitle={d.scanner.note ?? "Scanner shortlist (ranking heuristic only)"}>
          <dl className="grid grid-cols-2 gap-4"><Metric label="Scanned" value={d.scanner.scanned}/><Metric label="Shortlist" value={d.scanner.shortlist.length}/></dl>
          <ol className="mt-3 space-y-1 text-xs">{d.scanner.shortlist.map(c => <li key={c.canonical_id} className="flex justify-between gap-2"><span>#{c.rank} {c.canonical_id}</span><span className="tabular-nums text-muted">{num(c.score, 3)}</span></li>)}</ol>
        </Panel>
        <Panel title="AI research" provenance={basis} subtitle="Agents can support a decision; they never grant execution.">
          <ul className="space-y-2 text-xs">{d.agents.map(a => <li key={a.portfolio + (a.instrument ?? "")}>
            <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{a.portfolio === "tradingagents" ? "TradingAgents" : "BuffettAgent"}</span><Badge tone={a.status === "SIGNAL" ? "accent" : "neutral"}>{words(a.status)}</Badge>{a.direction && <Badge>{words(a.direction)}</Badge>}</div>
            <p className="mt-0.5 text-faint">{a.instrument ?? ""} {a.reason}</p>
          </li>)}</ul>
        </Panel>
        <Panel title="Decision" provenance={basis} subtitle={`Cutoff session ${d.cutoff_session ?? "—"}`}>
          {d.no_trade ? <p className="text-sm text-muted">{d.no_trade}</p>
            : <KeyValues rows={d.orders.map((o): [string, string] => [o.canonical_id, `${words(o.status)} · ${num(o.units, 4)} units ≤ ${price(o.limit_price)} · stop ${price(o.stop_price)} · ${o.strategy}`])}/>}
          <p className="mt-3 text-2xs text-faint">Admitted strategies: {d.admitted_strategies.length ? d.admitted_strategies.join(", ") : "none"}</p>
        </Panel>
      </div>
      <Panel title="Strategies and admission" provenance={basis} subtitle="Admission needs SD-022 robustness and at least 30 locked out-of-sample trades. Failures stay research-only.">
        <DataTable rows={d.strategies} columns={strategyColumns} rowKey={s => `${s.instrument}:${s.strategy_id}`} caption="Strategy research and admission per instrument" initialSort={{ key: "instrument", dir: "asc" }}/>
      </Panel>
      <Panel title="Decisions" provenance={basis} subtitle="Eligible, rejected and abstained candidates with reasons.">
        <DataTable rows={d.decisions} columns={decisionColumns} rowKey={x => x.symbol} caption="Decision engine output per instrument" initialSort={{ key: "symbol", dir: "asc" }}/>
        {d.risk.length > 0 && <div className="mt-3"><p className="text-xs font-semibold text-ink">Risk decisions</p>
          <KeyValues rows={d.risk.map((x): [string, string] => [x.canonical_id, `${words(x.decision)}${x.reasons.length ? " · " + x.reasons.map(words).join("; ") : ""}`])}/></div>}
      </Panel>
      {r ? <>
        <Panel title="Forward replay performance" provenance="SIMULATION" subtitle={`${words(r.basis)} · ${r.window.join(" to ")}`}>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
            <Metric label="Closed trades" value={r.closed_trades}/>
            <Metric label="Return" value={plainPct(r.total_return, 2)}/>
            <Metric label="Max drawdown" value={plainPct(r.max_drawdown, 2)}/>
            <Metric label="Benchmark (price only)" value={plainPct(r.benchmark, 2)}/>
            <Metric label="Cash reconciliation" value={words(r.cash_reconciliation)} tone={r.cash_reconciliation === "MATCHED" ? undefined : "attention"}/>
            <Metric label="Kill switch" value={words(r.kill_switch)} tone={r.kill_switch === "CLEAR" ? undefined : "attention"}/>
          </dl>
          {r.halt_reason && <p className="mt-2 text-xs text-attention">{r.halt_reason}</p>}
          <ul className="mt-4 space-y-1 text-xs">{r.by_strategy.map(b => <li key={b.strategy} className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{b.strategy}</span><span className="text-muted">{b.closed_trades} trades · win {plainPct(b.win_rate, 1)} · PF {num(b.profit_factor, 2)} · P&L {price(b.net_pnl_usd)}</span><Badge>{words(b.verdict)}</Badge>
          </li>)}</ul>
        </Panel>
        <Panel title="Positions (simulated ledger)" provenance="SIMULATION" subtitle="Fills are SIMULATED_LOCAL, never broker fills.">
          {r.positions.length ? <DataTable rows={r.positions} columns={positionColumns} rowKey={p => p.ref} caption="Simulated positions and exits" initialSort={{ key: "opened", dir: "desc" }}/>
            : <p className="text-sm text-muted">No positions were opened in the replay window.</p>}
        </Panel>
      </> : <Panel title="Forward replay" provenance="UNAVAILABLE"><p className="text-sm text-muted">This run did not include a replay.</p></Panel>}
      <Panel title="Broker routes" provenance={null} subtitle="Only the labelled local simulation is available. Releases are CLI-only and owner-signed.">
        <KeyValues rows={Object.entries(d.broker_routes).map(([k, v]): [string, string] => [words(k), v ?? "—"])}/>
      </Panel>
    </div>;
  }}</StateBlock>;
}
