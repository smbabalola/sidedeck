import { useResource } from "../lib/api";
import { isDayTraderSummary, type Provenance } from "../lib/contracts";
import { Badge, KeyValues, Panel, StateBlock } from "../components/ui";

function text(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

export default function DayTrader() {
  const resource = useResource("/api/day-trader/summary", isDayTraderSummary);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs uppercase tracking-[0.18em] text-accent">Independent module</p>
        <h2 className="mt-1 text-2xl font-semibold">Day Trader</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">Intraday research, run evidence, and SideDeck-controlled proposals. This workspace has no broker or capital controls.</p>
      </div><Badge tone="attention">RESEARCH ONLY</Badge>
    </div>
    <StateBlock resource={resource}>{d => {
      const run = d.runs[0] ?? null;
      const provenance: Provenance = run?.basis.includes("FIXTURE") ? "SYNTHETIC_FIXTURE" : "UNAVAILABLE";
      const plans = Array.isArray(d.plans) ? d.plans : [];
      const opportunities = Array.isArray(d.opportunities) ? d.opportunities : [];
      const simulation = record(d.simulations);
      const simMetrics = Object.entries(simulation).filter(([, v]) =>
        typeof v === "string" || typeof v === "number" || typeof v === "boolean").slice(0, 8);
      return <>
        <div className="grid gap-4 lg:grid-cols-3">
          <Panel title="Module and data status" provenance={provenance} subtitle={run ? `Selected run · ${run.created_at}` : "No saved run is available."}>
            <KeyValues rows={[["Source", `${d.source.name} ${d.source.version}`], ["Pinned commit", d.source.commit.slice(0, 12)], ["Verification", d.source.verification], ["Run basis", provenance], ["Data status", d.data_status], ["Performance", d.performance_status]]}/>
          </Panel>
          <Panel title="Safety boundary" provenance={null} subtitle="Central SideDeck gates remain authoritative.">
            <KeyValues rows={[["Execution", "Disabled"], ["Broker", d.broker_execution], ["Book", d.book], ["Opportunities", opportunities.length], ["Plans", plans.length], ["Rejected", d.rejected.length], ["Stage errors", d.errors.length]]}/>
          </Panel>
          <Panel title="Next acceptance gates" provenance={null} subtitle="Research evidence required before any strategy review.">
            <ul className="space-y-2 text-sm">{d.owner_actions.map(x => <li key={x} className="border-l-2 border-attention/60 pl-3">{x}</li>)}</ul>
          </Panel>
        </div>
          <Panel title="Run history" provenance={provenance} subtitle="Append-only local research records; detailed evidence below is from the latest run.">
          {d.runs.length ? <div className="overflow-x-auto"><table className="w-full min-w-[660px] text-left text-sm"><thead><tr className="border-b border-rule text-xs text-muted"><th className="p-2">Created (UTC)</th><th className="p-2">Run</th><th className="p-2">Basis</th><th className="p-2">Status</th><th className="p-2">Digest</th></tr></thead><tbody>{d.runs.map(r => <tr key={r.run_id} className="border-b border-rule/60"><td className="p-2">{r.created_at}</td><td className="p-2 font-mono">{r.run_id.slice(0, 12)}</td><td className="p-2">{r.basis}</td><td className="p-2">{r.status}</td><td className="p-2 font-mono">{r.report_sha256.slice(0, 12)}…</td></tr>)}</tbody></table></div> : <p className="text-sm text-muted">No persisted research run. Use the offline fixture command to populate this workspace.</p>}
        </Panel>
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel title="Scan watchlist" provenance={provenance} subtitle="Candidates surfaced by the scanner; these are not approved signals.">
            {opportunities.length ? <div className="space-y-2">{opportunities.map((item, i) => { const row = record(item); return <article key={i} className="rounded border border-rule p-3"><div className="flex flex-wrap justify-between gap-2"><strong>{text(row.symbol ?? row.ticker ?? row.canonical_id, `Candidate ${i + 1}`)}</strong><Badge tone="attention">{text(row.status ?? row.score ?? "RESEARCH")}</Badge></div><p className="mt-1 text-xs text-muted">{text(row.reason ?? row.description ?? row.source, "Scanner output; review the full candidate record.")}</p><details className="mt-2"><summary className="cursor-pointer text-xs text-accent">Candidate fields</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted">{JSON.stringify(item, null, 2)}</pre></details></article>; })}</div> : <p className="text-sm text-muted">No saved scan candidates.</p>}
          </Panel>
          <Panel title="Signal decisions and plans" provenance={provenance} subtitle="Decision outcome and reasons are shown for every stored proposal.">
            {plans.length ? <div className="space-y-3">{plans.map((item, i) => { const plan = record(item); const proposal = record(plan.proposal); const decision = record(proposal.sidedeck_decision); return <article key={i} className="rounded border border-rule p-3"><div className="flex flex-wrap justify-between gap-2"><strong>{text(plan.symbol ?? plan.ticker, `Plan ${i + 1}`)}</strong><Badge tone="attention">{text(decision.status ?? plan.result, "NO DECISION")}</Badge></div><KeyValues rows={[["Direction", text(plan.direction ?? proposal.direction)], ["Entry", text(plan.entry)], ["Stop", text(plan.stop)], ["Target", text(plan.target)], ["Decision reasons", text(decision.reasons ?? plan.reason)]]}/><p className="mt-2 text-xs text-muted">Proposal only. Execution permission: none.</p></article>; })}</div> : <p className="text-sm text-muted">No persisted plans.</p>}
          </Panel>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Simulation and backtest evidence" provenance={provenance} subtitle="Fixture and scenario outputs are not genuine performance or admission evidence.">
            {simMetrics.length ? <KeyValues rows={simMetrics.map(([k, v]) => [k.replace(/_/g, " "), text(v)])}/> : <p className="text-sm text-muted">No simulation metrics are available for this run.</p>}
            <p className="mt-3 text-xs text-muted">{text(simulation.label, "No labeled simulation attached.")}</p>
          </Panel>
          <Panel title="Rejected candidates and stage audit" provenance={provenance} subtitle="Failures remain visible so a partial run cannot look complete.">
            <KeyValues rows={[["Rejected", d.rejected.length], ["Stage errors", d.errors.length], ["Report SHA-256", run?.report_sha256 ?? "—"]]}/>
            {[...d.errors, ...d.rejected].slice(0, 10).map((item, i) => <details key={i} className="mt-2 rounded border border-rule p-2 text-xs"><summary className="cursor-pointer">{text(record(item).stage ?? record(item).symbol ?? `Audit item ${i + 1}`)} · {text(record(item).status ?? record(item).result)}</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-muted">{JSON.stringify(item, null, 2)}</pre></details>)}
          </Panel>
        </div>
        <Panel title="11 coordinated capabilities" provenance="UNAVAILABLE" subtitle="Pinned skills run with external network hosts blocked in the SideDeck sandbox.">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{d.capabilities.map(c => <div key={c.id} className="rounded border border-rule p-3"><p className="font-medium">{c.id}</p><p className="mt-1 text-xs text-muted">{c.role}</p></div>)}</div>
          <p className="mt-3 text-xs text-muted">{d.limitations.join(" ")}</p>
        </Panel>
      </>;
    }}</StateBlock>
  </div>;
}
