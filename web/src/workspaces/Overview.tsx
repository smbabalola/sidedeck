import { useResource } from "../lib/api";
import { type Provenance, isDemoSummary, isMarketTracks, isReleaseGate, isResearchSummary, isScanSnapshot, TRACKS } from "../lib/contracts";
import { ago, plainPct, when, words } from "../lib/format";
import { href } from "../lib/router";
import { Badge, KeyValues, Metric, Panel, ProvenanceBadge, StateBlock } from "../components/ui";

const AGENT_NAMES: Record<string, string> = { tradingagents: "TradingAgents", "ai-trading": "BuffettAgent (AI Hedge Fund)" };

export default function Overview() {
  const demo = useResource("/api/demo/summary", isDemoSummary);
  const gate = useResource("/api/research/release-gate", isReleaseGate);
  const tracks = useResource("/api/market/tracks", isMarketTracks);
  const scan = useResource("/api/market/scan", isScanSnapshot);
  const research = useResource("/api/research/summary", isResearchSummary);

  const events: { at: string; what: string; link: string; provenance: Provenance }[] = [];
  if (demo.state === "ready") {
    if (demo.data.captured_at) events.push({ at: demo.data.captured_at, what: "Protected Demo baseline captured", link: href("portfolio"), provenance: "DEMO_BROKER" });
    if (demo.data.fresh_snapshot) events.push({ at: demo.data.fresh_snapshot.observed_at, what: `Demo snapshot read (${words(demo.data.fresh_snapshot.reconciliation_status).toLowerCase()})`, link: href("portfolio"), provenance: "DEMO_BROKER" });
  }
  if (scan.state === "ready" && scan.data.status === "LOADED") events.push({ at: scan.data.generated_at, what: `Scanner run on the ${scan.data.cutoff} close`, link: href("markets"), provenance: scan.data.provenance });
  if (tracks.state === "ready" && tracks.data.universe.retrieved_at) events.push({ at: tracks.data.universe.retrieved_at, what: "US symbol universe snapshot loaded", link: href("markets"), provenance: "REAL_DATA" });
  events.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));

  return <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Execution and permissions" provenance={null} subtitle="Code-derived release gate; a local file cannot unlock it.">
        <StateBlock resource={gate}>{g => <>
          <dl className="grid grid-cols-2 gap-4">
            <Metric label="Paper release" value={words(g.overall_status)} tone="attention"/>
            <Metric label="Order submission" value={words(g.paper_order_submission)} tone="attention"/>
          </dl>
          <div className="mt-4"><KeyValues rows={[
            ["Human approval", words(g.human_approval)],
            ["Kill switch", words(g.kill_switch)],
            ["Protected baseline", words(g.protected_baseline)],
            ["eToro Real", g.etoro_demo ? words(g.etoro_demo.real_execution) : "—"],
          ]}/></div>
          <p className="mt-3 text-xs text-muted">The first MSFT Demo pilot runs only through the owner's signed release on the command line, never from this screen.</p>
        </>}</StateBlock>
      </Panel>
      <Panel title="Demo account" provenance={demo.state === "ready" ? "DEMO_BROKER" : "UNAVAILABLE"} subtitle="Saved baseline metadata. Balances are never shown here.">
        <StateBlock resource={demo}>{d => <>
          <dl className="grid grid-cols-2 gap-4">
            <Metric label="Protected positions" value={d.protected_positions ?? "—"} detail={d.captured_at ? `Captured ${when(d.captured_at)}` : "Baseline not captured"}/>
            <Metric label="Reconciliation" value={d.fresh_snapshot ? words(d.fresh_snapshot.reconciliation_status) : "Not current"} tone={d.fresh_snapshot?.reconciliation_status === "MATCHED" ? "gain" : "attention"}
              detail={d.fresh_snapshot ? `Read ${ago(d.fresh_snapshot.observed_at)}` : "No authorized read in the last 5 minutes"}/>
          </dl>
          <div className="mt-4"><KeyValues rows={[["Available cash", `${words(d.available_cash_usd_status)}, amount withheld`], ["Unrealised P&L", words(d.unrealized_pnl_status)]]}/></div>
        </>}</StateBlock>
      </Panel>
      <Panel title="Market coverage" provenance={tracks.state === "ready" && tracks.data.universe.status === "SNAPSHOT_LOADED" ? "REAL_DATA" : "UNAVAILABLE"} subtitle="What SideDeck can genuinely see today.">
        <StateBlock resource={tracks}>{t => <>
          <dl className="grid grid-cols-2 gap-4">
            <Metric label="US universe" value={t.universe.instruments?.toLocaleString() ?? "Not loaded"} detail={t.universe.status === "SNAPSHOT_LOADED" ? "Current listings, not point-in-time" : "Awaiting owner-signed SD-075A"}/>
            <Metric label="Price coverage" value={t.price_coverage.counts ? `${t.price_coverage.counts.COVERED} covered` : "None"} detail={t.price_coverage.counts ? `${t.price_coverage.counts.PARTIALLY_COVERED} partial, ${t.price_coverage.counts.UNAVAILABLE} unavailable` : "Awaiting owner-signed SD-075B"}/>
          </dl>
          <a className="mt-4 inline-block text-xs text-accent hover:underline" href={href("markets")}>Open Markets</a>
        </>}</StateBlock>
      </Panel>
    </div>

    <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
      <Panel title="Trading tracks" provenance={null} subtitle="Every track is research-only. Risk budgets are configuration, not capital.">
        <StateBlock resource={tracks}>{t => <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">Track status and risk budgets</caption>
            <thead><tr className="border-b border-rule text-left text-muted">
              <th scope="col" className="py-2 pr-3 font-medium">Track</th><th scope="col" className="py-2 pr-3 font-medium">Mode</th>
              <th scope="col" className="py-2 pr-3 font-medium">Data</th><th scope="col" className="py-2 pr-3 text-right font-medium">Risk per trade</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Max drawdown</th><th scope="col" className="py-2 pr-3 text-right font-medium">Candidates</th>
            </tr></thead>
            <tbody>{TRACKS.map(id => {
              const tr = t.tracks.find(x => x.track === id);
              if (!tr) return null;
              const loaded = scan.state === "ready" && scan.data.status === "LOADED" ? scan.data : null;
              return <tr key={id} className="border-b border-rule/60">
                <th scope="row" className="py-2 pr-3 text-left font-medium"><a href={href("tracks", id)} className="hover:text-accent">{words(id)}</a></th>
                <td className="py-2 pr-3"><Badge>{words(tr.mode)}</Badge></td>
                <td className="py-2 pr-3">{tr.data_status === "AVAILABLE" ? <Badge tone="attention" title="Approved for autonomous use; nothing implies data is loaded">{tr.usable_sources.map(words).join(", ")} only</Badge> : <Badge tone="blocked">No approved source</Badge>}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{plainPct(tr.risk_budget.risk_per_trade_pct)}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{plainPct(tr.risk_budget.max_drawdown_pct, 0)}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{loaded ? <>{loaded.tracks[id].candidates.length} <ProvenanceBadge value={loaded.provenance}/></> : "—"}</td>
              </tr>;
            })}</tbody>
          </table>
          <p className="mt-3 text-xs text-muted">{t.decision_engine.execution_permission === "NOT_GRANTED_BY_DECISION_ENGINE" ? "The decision engine never grants execution" : "Unexpected decision-engine permission"}; agent-only agreement is capped at {words(t.decision_engine.agent_only_cap).toLowerCase()}.</p>
        </div>}</StateBlock>
      </Panel>
      <Panel title="Agents" provenance={research.state === "ready" && research.data.agents.length ? "REAL_DATA" : "UNAVAILABLE"} subtitle="Opinions only; they never place orders.">
        <StateBlock resource={research}>{r => <ul className="space-y-2 text-sm">
          {["tradingagents", "ai-trading"].map(id => {
            const a = r.agents.find(x => x.id === id);
            return <li key={id} className="flex items-center justify-between gap-2">
              <span>{AGENT_NAMES[id]}</span>
              {a ? <Badge tone={a.status === "VERIFIED_OFFLINE" ? "gain" : "attention"}>{words(a.status)}, {a.evidence_count} evidence</Badge> : <Badge>Not run</Badge>}
            </li>;
          })}
          <li className="flex items-center justify-between gap-2"><span>Day-trader methods</span><Badge tone="accent">Native rules ready</Badge></li>
          <li className="pt-1 text-xs text-muted">Valuation evidence: {words(r.valuation).toLowerCase()}. Live agent runs need an owner-approved model budget.</li>
        </ul>}</StateBlock>
      </Panel>
    </div>

    <Panel title="Recent evidence" provenance={null} subtitle="Timestamps of the latest data SideDeck holds. Nothing here is a live feed.">
      {events.length === 0 ? <p className="text-sm text-muted">No timestamped evidence is loaded yet.</p> :
        <ol className="divide-y divide-rule/60 text-sm">
          {events.map(e => <li key={e.what + e.at} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span className="flex items-center gap-2"><ProvenanceBadge value={e.provenance}/><a href={e.link} className="hover:text-accent">{e.what}</a></span>
            <time dateTime={e.at} className="text-xs text-muted tabular-nums">{when(e.at)}, {ago(e.at)}</time>
          </li>)}
        </ol>}
    </Panel>
  </div>;
}
