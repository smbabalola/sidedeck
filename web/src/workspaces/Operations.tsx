import { useResource } from "../lib/api";
import { isDemoSummary, isMarketTracks, isReleaseGate } from "../lib/contracts";
import { ago, when, words } from "../lib/format";
import { Badge, KeyValues, Metric, Panel, StateBlock } from "../components/ui";

const BOOK_NAMES: Record<string, string> = {
  "etoro-demo:tradingagents": "TradingAgents book", "etoro-demo:ai-trading": "BuffettAgent book", "etoro-demo:unattributed": "Original positions (protected)",
};

export function Portfolio() {
  const demo = useResource("/api/demo/summary", isDemoSummary);
  return <div className="space-y-4">
    <Panel title="Demo books" provenance={demo.state === "ready" ? "DEMO_BROKER" : "UNAVAILABLE"} subtitle="Positions are attributed only through verified order lineage, never by ticker.">
      <StateBlock resource={demo}>{d => {
        const books = d.fresh_snapshot?.books ?? d.books;
        return <>
          <table className="w-full text-xs"><caption className="sr-only">Demo books</caption>
            <thead><tr className="border-b border-rule text-left text-muted"><th scope="col" className="py-2 font-medium">Book</th><th scope="col" className="py-2 text-right font-medium">Positions</th><th scope="col" className="py-2 font-medium">Capital</th><th scope="col" className="py-2 font-medium">P&amp;L</th></tr></thead>
            <tbody>{books.map(b => <tr key={b.id} className="border-b border-rule/60">
              <th scope="row" className="py-2 text-left font-medium">{BOOK_NAMES[b.id] ?? b.id}</th>
              <td className="py-2 text-right tabular-nums">{b.positions ?? "—"}</td>
              <td className="py-2"><Badge tone="attention">{words(b.allocation_status)}</Badge></td>
              <td className="py-2 text-muted">Unavailable</td>
            </tr>)}</tbody>
          </table>
          <p className="mt-3 text-xs text-muted">{d.fresh_snapshot ? `From an owner-authorized read ${ago(d.fresh_snapshot.observed_at)}.` : `Saved baseline from ${when(d.captured_at)}; current positions are not reconciled.`}</p>
        </>;
      }}</StateBlock>
    </Panel>
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="SideDeck orders, fills and exits" provenance="UNAVAILABLE">
        <p className="text-sm text-muted">No SideDeck-owned Demo orders exist yet. The first one is the owner-run MSFT pilot; its order, fill, close and reconciliation evidence will appear here with full lineage once recorded.</p>
      </Panel>
      <Panel title="Simulated track ledgers" provenance="UNAVAILABLE">
        <p className="text-sm text-muted">The DAY, SWING and POSITION simulation ledgers are not exposed by the service yet, so no simulated positions are shown.</p>
      </Panel>
    </div>
  </div>;
}

export function Operations() {
  const gate = useResource("/api/research/release-gate", isReleaseGate);
  const tracks = useResource("/api/market/tracks", isMarketTracks);
  return <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Release gate" provenance={null} subtitle="Fail-closed; the browser cannot change it.">
        <StateBlock resource={gate}>{g => <>
          <dl className="grid grid-cols-3 gap-4">
            <Metric label="Overall" value={words(g.overall_status)} tone="attention"/>
            <Metric label="Kill switch" value={words(g.kill_switch)}/>
            <Metric label="Rehearsal" value={words(g.rehearsal.status)}/>
          </dl>
          <div className="mt-4"><KeyValues rows={[
            ["Order submission", words(g.paper_order_submission)], ["Human approval", words(g.human_approval)],
            ["Account mapping", words(g.account_mapping)], ["Broker reconciliation", words(g.broker_reconciliation)],
            ["Protected baseline", words(g.protected_baseline)], ["Engineering rehearsal", words(g.engineering_rehearsal)],
          ]}/></div>
          <h3 className="mt-4 text-xs font-semibold text-muted">Blocking controls</h3>
          <div className="mt-2 flex flex-wrap gap-1.5">{g.blocking_controls.map(c => <Badge key={c} tone="blocked">{words(c)}</Badge>)}</div>
        </>}</StateBlock>
      </Panel>
      <Panel title="eToro Demo broker" provenance={null} subtitle="Code-derived status. eToro Real is permanently excluded.">
        <StateBlock resource={gate} empty={g => (g.etoro_demo ? null : "Broker status not reported.")}>{g => g.etoro_demo && <>
          <KeyValues rows={[
            ["Priority", `${words(g.etoro_demo.broker_priority)} (${g.etoro_demo.secondary_broker} secondary)`],
            ["Execution release", words(g.etoro_demo.execution_release)], ["Real execution", words(g.etoro_demo.real_execution)],
            ["Transport", words(g.etoro_demo.transport)], ["Baseline", words(g.etoro_demo.baseline)],
            ["Ownership", words(g.etoro_demo.ownership)], ["Agent portfolios", words(g.etoro_demo.agent_portfolios)],
          ]}/>
          <h3 className="mt-4 text-xs font-semibold text-muted">Open risks</h3>
          <div className="mt-2 flex flex-wrap gap-1.5">{g.etoro_demo.open_risks.length ? g.etoro_demo.open_risks.map(r => <Badge key={r} tone="attention">{r}</Badge>) : <span className="text-xs text-muted">None recorded</span>}</div>
        </>}</StateBlock>
      </Panel>
    </div>
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Scheduler" provenance={null} subtitle="Planned runs in your local time. Broker reconciliation stays disabled until a request budget is approved.">
        <StateBlock resource={tracks}>{t => <ul className="divide-y divide-rule/60 text-xs">
          {t.tracks.flatMap(tr => tr.jobs.map(j => ({ ...j, track: tr.track }))).map(j => <li key={j.job_id} className="flex items-center justify-between gap-2 py-1.5">
            <span>{words(j.job_id)} <span className="text-faint">{words(j.track)}</span></span>
            {Number.isFinite(Date.parse(j.next_run_utc)) ? <time dateTime={j.next_run_utc} className="tabular-nums text-muted">{when(j.next_run_utc)}</time> : <Badge tone="attention">{words(j.next_run_utc)}</Badge>}
          </li>)}
        </ul>}</StateBlock>
      </Panel>
      <Panel title="Data sources and authorizations" provenance={null} subtitle="Every authenticated or public download needs an owner-signed, bounded authorization.">
        <StateBlock resource={tracks}>{t => <KeyValues rows={[
          ["US universe (SD-075A)", t.universe.status === "SNAPSHOT_LOADED" ? `Loaded ${when(t.universe.retrieved_at)}` : "Awaiting owner signature"],
          ["Daily prices (SD-075B)", t.price_coverage.status === "PILOT_LOADED" ? "Pilot loaded" : "Awaiting owner signature"],
          ["Intraday data (Day track)", "No approved source"],
          ["Paid model calls", "Not authorized"],
        ]}/>}</StateBlock>
      </Panel>
    </div>
  </div>;
}
