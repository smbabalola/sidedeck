import { useResource } from "../lib/api";
import { type StrategyEntry, type ValidationDataset, isResearchSummary, isStrategyCatalogue, isStrategyValidation } from "../lib/contracts";
import { num, pct, plainPct, words } from "../lib/format";
import { Badge, type Column, DataTable, KeyValues, Panel, StateBlock } from "../components/ui";

const AGENTS = [
  { id: "tradingagents", name: "TradingAgents", upstream: "TauricResearch/TradingAgents 0.7.0", track: "Swing (2–15 days)", role: "Multi-analyst debate producing buy, hold or sell with a rationale." },
  { id: "ai-trading", name: "BuffettAgent", upstream: "virattt/ai-hedge-fund (pinned commit)", track: "Position (20–180 days)", role: "Fundamental value assessment from SEC-filed figures." },
];
const METHODS = [
  ["20-day closing breakout", "Swing"], ["Bull flag", "Swing"], ["Reclaim of the 20-day average", "Swing"],
  ["RSI(14) oversold", "Swing (neutral only)"], ["Oversold bounce", "Swing"], ["Opening-range breakout (5-minute)", "Day"],
];

export function Agents() {
  const research = useResource("/api/research/summary", isResearchSummary);
  return <div className="space-y-4">
    <div className="grid gap-4 lg:grid-cols-2">
      {AGENTS.map(a => <Panel key={a.id} title={a.name} provenance={research.state === "ready" && research.data.agents.some(x => x.id === a.id) ? "REAL_DATA" : "UNAVAILABLE"} subtitle={a.upstream}>
        <StateBlock resource={research}>{r => {
          const s = r.agents.find(x => x.id === a.id);
          return <>
            <p className="text-sm">{a.role}</p>
            <div className="mt-3"><KeyValues rows={[
              ["Track", a.track], ["Run status", s ? words(s.status) : "Not run"], ["Evidence items", s ? s.evidence_count : "—"],
              ["Valuation inputs", words(r.valuation)], ["Maximum outcome", "Watchlist (agents cannot grant execution)"],
            ]}/></div>
          </>;
        }}</StateBlock>
      </Panel>)}
    </div>
    <Panel title="Day-trader methodologies" provenance={null} subtitle="Deterministic SideDeck rules adapted from the MIT-licensed day-trader skill. No language model runs at trading time.">
      <table className="w-full text-xs"><caption className="sr-only">Native methodology rules</caption>
        <thead><tr className="border-b border-rule text-left text-muted"><th scope="col" className="py-2 font-medium">Rule</th><th scope="col" className="py-2 font-medium">Track</th><th scope="col" className="py-2 font-medium">Version</th></tr></thead>
        <tbody>{METHODS.map(([rule, track]) => <tr key={rule} className="border-b border-rule/60"><td className="py-1.5">{rule}</td><td className="py-1.5">{track}</td><td className="py-1.5 text-muted">dts-2.0.0-native.1</td></tr>)}</tbody>
      </table>
      <p className="mt-3 text-xs text-muted">A matched rule means a chart met a condition. It is never a recommendation and is capped at watchlist by the decision engine.</p>
    </Panel>
    <Panel title="Conclusions and disagreements" provenance="UNAVAILABLE">
      <p className="text-sm text-muted">No agent conclusions are recorded yet. When runs exist, each conclusion shows its instrument, data cutoff, version, evidence digests and any disagreement with other agents or strategies. Live runs need an owner-approved model budget.</p>
    </Panel>
  </div>;
}

export function Strategies() {
  const catalogue = useResource("/api/research/strategies", isStrategyCatalogue);
  const validation = useResource("/api/research/validation", isStrategyValidation);
  const columns: Column<StrategyEntry>[] = [
    { key: "id", header: "Strategy", render: s => <span className="font-medium">{words(s.id)}</span>, sortValue: s => s.id },
    { key: "v", header: "Version", render: s => s.version },
    { key: "hold", header: "Holding period", render: s => `${s.holding_period[0]}–${s.holding_period[1]} days` },
    { key: "params", header: "Parameters", render: s => Object.entries(s.parameters).map(([k, v]) => `${k}=${v}`).join(", ") || "—", hideBelow: "md" },
    { key: "exec", header: "Execution timing", render: s => words(s.execution_assumption), hideBelow: "lg" },
    { key: "acc", header: "Admission", render: s => <Badge tone="attention">{words(s.acceptance)}</Badge> },
  ];
  return <div className="space-y-4">
    <Panel title="Strategy catalogue" provenance={null} subtitle="Versioned, proposal-only strategies. None is admitted for execution.">
      <StateBlock resource={catalogue}>{c => <DataTable rows={c.strategies} columns={columns} rowKey={s => `${s.id}@${s.version}`} caption="Strategy catalogue"/>}</StateBlock>
    </Panel>
    <StateBlock resource={validation} empty={v => (v.datasets.length ? null : "No local validation reports are loaded. Start the service with --strategy-research to show them.")}>{v => <div className="grid gap-4 xl:grid-cols-3">
      {v.datasets.map((d: ValidationDataset) => <Panel key={d.ticker} title={`${d.ticker} validation`} provenance="REAL_DATA" subtitle={`${d.start} to ${d.end}, ${d.observations} daily bars, ${d.feed ?? "feed unknown"} ${d.adjustment ?? ""}`}>
        <table className="w-full text-xs"><caption className="sr-only">{d.ticker} strategy results</caption>
          <thead><tr className="border-b border-rule text-left text-muted"><th scope="col" className="py-1.5 font-medium">Strategy</th><th scope="col" className="py-1.5 text-right font-medium">Trades</th><th scope="col" className="py-1.5 text-right font-medium">Max DD</th><th scope="col" className="py-1.5 font-medium">Result</th></tr></thead>
          <tbody>{d.strategies.map(s => <tr key={s.id} className="border-b border-rule/60">
            <td className="py-1.5">{words(s.id)}</td>
            <td className="py-1.5 text-right tabular-nums">{s.metrics.round_trip_count ?? s.metrics.trade_count ?? "—"}</td>
            <td className="py-1.5 text-right tabular-nums">{plainPct(s.metrics.max_drawdown as string | null)}</td>
            <td className="py-1.5"><Badge tone={s.status === "VERIFIED" ? "gain" : s.status.includes("REJECT") ? "loss" : "attention"}>{words(s.status)}</Badge></td>
          </tr>)}</tbody>
        </table>
        <div className="mt-3"><KeyValues rows={[
          ["Benchmark convention", d.benchmark ? words(d.benchmark.convention) : "Unavailable"],
          ["Price-only return", d.benchmark?.return ? pct(d.benchmark.return) : "Unavailable"],
          ["Total return", d.benchmark ? words(d.benchmark.total_return) : "Unavailable"],
          ["Corporate actions", d.benchmark ? words(d.benchmark.corporate_action_status) : "Not assessed"],
        ]}/></div>
        <p className="mt-2 text-xs text-muted">Screening evidence only; a positive backtest is not an execution approval. Profit factor {num(d.strategies[0]?.metrics.profit_factor as string | null)} shown for the first strategy.</p>
      </Panel>)}
    </div>}</StateBlock>
  </div>;
}
