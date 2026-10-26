import { useResource } from "../lib/api";
import { isDayTraderSummary } from "../lib/contracts";
import { Badge, KeyValues, Panel, StateBlock } from "../components/ui";

export default function DayTrader() {
  const resource = useResource("/api/day-trader/summary", isDayTraderSummary);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs uppercase tracking-[0.18em] text-accent">Independent module</p>
        <h2 className="mt-1 text-2xl font-semibold">Day Trader</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">Pinned upstream skills, isolated research, and SideDeck-controlled proposals. This workspace has no broker or capital controls.</p>
      </div><Badge tone="attention">RESEARCH ONLY</Badge>
    </div>
    <StateBlock resource={resource}>{d => <>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Module status" provenance={d.latest ? "SYNTHETIC_FIXTURE" : "UNAVAILABLE"} subtitle={d.latest ? `Saved run · ${d.data_status}` : "No saved run is available."}>
          <KeyValues rows={[["Source", `${d.source.name} ${d.source.version}`], ["Pinned commit", d.source.commit.slice(0, 12)], ["License", d.source.license], ["Verification", d.source.verification], ["Performance", d.performance_status]]}/>
        </Panel>
        <Panel title="Safety boundary" provenance={null} subtitle="Central SideDeck gates remain authoritative.">
          <KeyValues rows={[["Execution", "Disabled"], ["Broker", d.broker_execution], ["Virtual book", d.book], ["Opportunities", d.opportunities.length], ["Plans", d.plans.length], ["Rejected", d.rejected.length], ["Errors", d.errors.length]]}/>
        </Panel>
        <Panel title="Owner actions" provenance={null} subtitle="Required before acceptance can advance.">
          <ul className="space-y-2 text-sm">{d.owner_actions.map(x => <li key={x} className="border-l-2 border-attention/60 pl-3">{x}</li>)}</ul>
        </Panel>
      </div>
      <Panel title="11 coordinated capabilities" provenance="UNAVAILABLE" subtitle="The installed skill is inspected and pinned; each online host is blocked in SideDeck's sandbox.">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{d.capabilities.map(c => <div key={c.id} className="rounded border border-rule p-3"><p className="font-medium">{c.id}</p><p className="mt-1 text-xs text-muted">{c.role}</p></div>)}</div>
      </Panel>
      <Panel title="Opportunities and plans" provenance={d.latest ? "SYNTHETIC_FIXTURE" : "UNAVAILABLE"} subtitle="Persisted scanner and plan outputs are evidence-labelled and remain proposal-only.">
        {d.opportunities.length ? <div className="space-y-2 text-sm">{d.opportunities.map((x, i) => <div key={i} className="rounded border border-rule p-2">{JSON.stringify(x)}</div>)}</div> : <p className="text-sm text-muted">No saved opportunities.</p>}
        <p className="mt-3 text-xs text-muted">Plans: {d.plans.length} · Rejected: {d.rejected.length} · Errors: {d.errors.length}</p>
      </Panel>
      <Panel title="Time Machine and run history" provenance={d.latest ? "SYNTHETIC_FIXTURE" : "UNAVAILABLE"} subtitle="Scenario estimates are not forecasts or locked out-of-sample evidence.">
        <p className="text-sm text-muted">{d.latest ? `Latest run ${d.runs[0]?.run_id ?? "unknown"}; ${d.runs.length} saved run(s).` : "No persisted research run."}</p>
        <p className="mt-2 text-xs text-muted">{d.latest ? "Simulation output is retained locally and labelled by its data basis." : "Run the offline fixture command to populate this workspace."}</p>
      </Panel>
    </>}</StateBlock>
    </div>;
}
