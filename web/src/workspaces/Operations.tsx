import { useResource } from "../lib/api";
import { isAuthorizationLedger, isDemoSummary, isMarketTracks, isOfflineOperatorStatus, isReleaseGate, isTrackLedgers, TRACKS } from "../lib/contracts";
import { ago, price, tone, when, words } from "../lib/format";
import { Badge, KeyValues, Metric, Panel, StateBlock } from "../components/ui";

const BOOK_NAMES: Record<string, string> = {
  "etoro-demo:tradingagents": "TradingAgents book", "etoro-demo:ai-trading": "BuffettAgent book", "etoro-demo:unattributed": "Original positions (protected)",
};

export function Portfolio() {
  const demo = useResource("/api/demo/summary", isDemoSummary);
  const ledgers = useResource("/api/portfolio/ledgers", isTrackLedgers);
  return <div className="space-y-4">
    <Panel title="Demo books" provenance={demo.state === "ready" && demo.data.fresh_snapshot ? "DEMO_BROKER" : null}
      actions={demo.state === "ready" && !demo.data.fresh_snapshot ? <Badge>Saved baseline</Badge> : undefined} subtitle="Positions are attributed only through verified order lineage, never by ticker.">
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
        <p className="text-sm text-muted">This read-only panel has no broker order-history feed. The earlier owner-supervised MSFT Demo pilot was manually closed and a separate authorised portfolio check confirmed it was no longer open; this screen does not establish its historical close price or realised P&L. No new position or broker-fill history is inferred from a saved baseline.</p>
      </Panel>
      <Panel title="Simulated track ledgers" provenance={ledgers.state === "ready" && ledgers.data.status === "LOADED" ? "SIMULATION" : "UNAVAILABLE"}
        subtitle="Local simulation only (fills are simulated, not broker fills). Each track keeps separate virtual capital.">
        <StateBlock resource={ledgers} empty={l => (l.status === "LOADED" ? null : `No simulation ledgers: ${l.reason ?? "not configured"}.`)}>{l => <table className="w-full text-xs">
          <caption className="sr-only">Simulated ledgers by track</caption>
          <thead><tr className="border-b border-rule text-left text-muted"><th scope="col" className="py-1.5 font-medium">Track</th><th scope="col" className="py-1.5 text-right font-medium">Cash</th><th scope="col" className="py-1.5 text-right font-medium">Open</th><th scope="col" className="py-1.5 text-right font-medium">Realised P&amp;L</th><th scope="col" className="py-1.5 text-right font-medium">Fees</th></tr></thead>
          <tbody>{TRACKS.map(id => {
            const t = l.tracks.find(x => x.track === id);
            if (!t || t.status !== "ACTIVE") return <tr key={id} className="border-b border-rule/60"><th scope="row" className="py-1.5 text-left font-medium">{words(id)}</th><td colSpan={4} className="py-1.5 text-right text-muted">{t ? words(t.status) : "Not reported"}</td></tr>;
            const pnl = tone(t.realized_pnl);
            return <tr key={id} className="border-b border-rule/60">
              <th scope="row" className="py-1.5 text-left font-medium">{words(id)}</th>
              <td className="py-1.5 text-right tabular-nums">{price(t.cash)}</td>
              <td className="py-1.5 text-right tabular-nums">{t.open_positions}</td>
              <td className={`py-1.5 text-right tabular-nums ${pnl === "gain" ? "text-gain" : pnl === "loss" ? "text-loss" : ""}`}>{price(t.realized_pnl)}</td>
              <td className="py-1.5 text-right tabular-nums">{price(t.fees)}</td>
            </tr>;
          })}</tbody>
        </table>}</StateBlock>
      </Panel>
    </div>
  </div>;
}

export function Operations() {
  const gate = useResource("/api/research/release-gate", isReleaseGate);
  const tracks = useResource("/api/market/tracks", isMarketTracks);
  const auths = useResource("/api/ops/authorizations", isAuthorizationLedger);
  const operator = useResource("/api/ops/offline-operator-status", isOfflineOperatorStatus);
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
    <Panel title="Offline worker diagnostics"
      subtitle="Local fence evidence only. This panel does not verify broker holdings, grant validity or account state.">
      <StateBlock resource={operator}>{o => <>
        <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Metric label="Worker fence" value={words(o.fence_state)} tone={o.fence_state === "IDLE" ? "attention" : "loss"}/>
          <Metric label="Safe to trade" value="No" tone="loss"/>
          <Metric label="Execution release" value="Not released" tone="loss"/>
          <Metric label="Alert delivery" value="Not configured" tone="attention"/>
        </dl>
        <div className="mt-4"><KeyValues rows={[
          ["Evidence source", words(o.source)], ["Broker account verified", "No"],
          ["Recovery", words(o.recovery)], ["Heartbeat age", o.heartbeat_age_seconds === null ? "Unavailable" : `${o.heartbeat_age_seconds} seconds`],
          ["Automatic broker reads or writes", "Disabled"], ["Historical HALT clear", "Disabled"],
        ]}/></div>
        <h3 className="mt-4 text-xs font-semibold text-muted">Local incidents</h3>
        <div className="mt-2 flex flex-wrap gap-1.5">{o.incidents.length
          ? o.incidents.map(item => <Badge key={item} tone="attention">{words(item)}</Badge>)
          : <span className="text-xs text-muted">No local fence incident recorded</span>}</div>
      </>}</StateBlock>
    </Panel>
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
        <h3 className="mt-4 text-xs font-semibold text-muted">Signed authorization usage</h3>
        <StateBlock resource={auths} empty={a => (a.authorizations.length ? null : a.reason ? `${a.reason[0].toUpperCase()}${a.reason.slice(1)}.` : "No signed authorization has been used.")}>{a => <ul className="mt-2 divide-y divide-rule/60 text-xs">
          {a.authorizations.map(x => <li key={x.digest_prefix} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
            <span className="tabular-nums">Digest {x.digest_prefix}… · {x.requests} request{x.requests === 1 ? "" : "s"}</span>
            <span className="flex flex-wrap gap-1">{Object.entries(x.outcomes).map(([k, v]) => <Badge key={k} tone={k === "OK" ? "gain" : k.startsWith("FAIL") ? "loss" : "neutral"}>{words(k)}: {v}</Badge>)}</span>
          </li>)}
        </ul>}</StateBlock>
      </Panel>
    </div>
  </div>;
}
