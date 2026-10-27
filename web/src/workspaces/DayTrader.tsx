import { useState } from "react";
import DayTraderWorkflow from "./DayTraderWorkflow";
import DayTraderCandidateDesk from "./DayTraderCandidateDesk";
import { useResource } from "../lib/api";
import {
  isDayTraderReadiness, isDayTraderSummary, isMarketTracks, isTrackLedgers,
  type DayTraderSummary, type Provenance,
} from "../lib/contracts";
import { plainPct, price, when, words } from "../lib/format";
import { Badge, KeyValues, Metric, Panel, SearchBox, StateBlock, Tabs } from "../components/ui";

type Section = "desk" | "research" | "audit" | "readiness";
const sections: { id: Section; label: string }[] = [
  { id: "desk", label: "Desk" },
  { id: "research", label: "Opportunities & plans" },
  { id: "audit", label: "Run history & audit" },
  { id: "readiness", label: "Execution readiness" },
];
const value = (x: unknown, fallback = "—"): string =>
  x === null || x === undefined || x === "" ? fallback
    : typeof x === "string" || typeof x === "number" || typeof x === "boolean" ? String(x)
      : JSON.stringify(x);
const object = (x: unknown): Record<string, unknown> =>
  x && typeof x === "object" && !Array.isArray(x) ? x as Record<string, unknown> : {};
const basis = (b?: string): Provenance =>
  b && (b.includes("FIXTURE") || b.includes("SYNTH")) ? "SYNTHETIC_FIXTURE" : "UNAVAILABLE";
const details = (label: string, data: unknown) =>
  <details className="rounded border border-rule p-2 text-xs">
    <summary className="cursor-pointer text-accent">{label}</summary>
    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-muted">{JSON.stringify(data, null, 2)}</pre>
  </details>;

function Readiness() {
  const state = useResource("/api/day-trader/readiness", isDayTraderReadiness);
  return <StateBlock resource={state}>{d => <>
    <p className="mb-3 text-xs text-muted">Code-derived readiness only; no broker read, API credentials, trading permission or fresh market-data verification.</p>
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {d.gates.map((g, i) => <article key={g.id} className="rounded border border-rule bg-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-mono text-xs text-faint">0{i + 1}</span>
          <Badge tone={g.status === "IMPLEMENTED_OFFLINE" ? "accent" : "blocked"}>{words(g.status)}</Badge>
        </div>
        <h3 className="mt-3 text-sm font-semibold">{g.label}</h3>
        <p className="mt-1 text-xs text-muted">{g.detail}</p>
        <div className="mt-3 border-t border-rule pt-3">
          <p className="text-2xs font-semibold uppercase tracking-wide text-faint">Next action</p>
          <p className="mt-1 text-xs">{g.next_action}</p>
        </div>
      </article>)}
    </div>
    <Panel title="Readiness limits" provenance={null} className="mt-4">
      <KeyValues rows={[
        ["Five-minute data", words(d.data_status)],
        ["Strategy admission", words(d.strategy_status)],
        ["Demo execution", words(d.demo_release)],
        ["Real-money trading", words(d.real_execution)],
      ]}/>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">{d.limitations.map(x => <li key={x}>{x}</li>)}</ul>
    </Panel>
  </>}</StateBlock>;
}

function SimulatedBook() {
  const ledgers = useResource("/api/portfolio/ledgers", isTrackLedgers);
  const tracks = useResource("/api/market/tracks", isMarketTracks);
  return <div className="grid gap-4 xl:grid-cols-2">
    <Panel title="DAY simulated accounting" provenance="SIMULATION"
      subtitle="Local ledger only; not eToro Demo holdings or realised broker P&L.">
      <StateBlock resource={ledgers}>{d => {
        const day = d.tracks.find(x => x.track === "DAY");
        return day?.status === "ACTIVE" ? <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Metric label="Simulated cash" value={price(day.cash)}/>
          <Metric label="Open positions" value={day.open_positions}/>
          <Metric label="Realised P&L" value={price(day.realized_pnl)}/>
          <Metric label="Entries" value={day.entries}/><Metric label="Closes" value={day.closes}/>
          <Metric label="Fees" value={price(day.fees)}/>
        </dl> : <p className="text-sm text-muted">No active DAY simulation ledger. A research run does not create an eToro position.</p>;
      }}</StateBlock>
    </Panel>
    <Panel title="DAY risk configuration" provenance={null}
      subtitle="Proposed limits are not owner-signed capital allocation.">
      <StateBlock resource={tracks}>{d => {
        const day = d.tracks.find(x => x.track === "DAY");
        return day ? <KeyValues rows={[
          ["Execution", words(day.execution)], ["Data", words(day.data_status)],
          ["Virtual capital (configuration)", day.risk_budget.virtual_capital === "NOT_ALLOCATED" ? "Not allocated" : price(day.risk_budget.virtual_capital)],
          ["Max positions", day.risk_budget.max_positions],
          ["Daily loss limit", plainPct(day.risk_budget.max_daily_loss_pct)],
          ["Drawdown limit", plainPct(day.risk_budget.max_drawdown_pct)],
          ["Exit policy", words(day.risk_budget.exit_policy)],
        ]}/> : <p className="text-sm text-muted">DAY risk configuration unavailable.</p>;
      }}</StateBlock>
    </Panel>
  </div>;
}

function Desk({ d }: { d: DayTraderSummary }) {
  const run = d.runs[0] ?? null;
  const provenance = basis(run?.basis);
  const scenario = object(d.simulations);
  return <>
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel title="Latest research run" provenance={provenance}
        subtitle={run ? "Saved " + when(run.created_at) : "No persisted research run."}>
        <KeyValues rows={[
          ["Mode", words(d.mode)], ["Status", words(run?.status)], ["Basis", value(run?.basis)],
          ["Scanner candidates", d.opportunities.length], ["Plans", d.plans.length],
          ["Stage errors", d.errors.length],
        ]}/>
      </Panel>
      <Panel title="Signal boundary" provenance={null}
        subtitle="Upstream skill confidence is not independent strategy admission.">
        <dl className="grid grid-cols-2 gap-4">
          <Metric label="Candidates" value={d.opportunities.length}/>
          <Metric label="Rejected" value={d.rejected.length} tone={d.rejected.length ? "attention" : undefined}/>
        </dl>
        <p className="mt-3 text-xs text-muted">No released DAY trading strategy is established by this run.</p>
      </Panel>
      <Panel title="Scenario evidence" provenance={provenance}
        subtitle="Fixture scenarios do not imply real performance.">
        <KeyValues rows={[
          ["Performance", words(d.performance_status)], ["Scenario", value(scenario.status ?? scenario.label)],
          ["Source verification", d.source.verification],
          ["Report hash", run?.report_sha256 ? run.report_sha256.slice(0, 16) + "…" : "—"],
        ]}/>
      </Panel>
    </div>
    <DayTraderCandidateDesk summary={d}/>
    <DayTraderWorkflow/>
    <SimulatedBook/>
    <Panel title="Path to Demo autonomy" provenance={null}
      subtitle="Each gate is independent. Passing offline tests never unlocks broker trading.">
      <div className="grid gap-3 md:grid-cols-3">{[
        ["01 / Data", "Authorised historical and current five-minute data, proven provenance and complete sessions."],
        ["02 / Strategy", "Out-of-sample admission of native DAY rules with realistic execution costs."],
        ["03 / Execution", "Reviewed Demo-only transport, external anchors and owner-signed bounded release."],
      ].map(([name, note]) => <div className="rounded border border-rule p-3" key={name}>
        <h3 className="text-sm font-semibold">{name}</h3>
        <p className="mt-1 text-xs text-muted">{note}</p>
      </div>)}</div>
    </Panel>
  </>;
}

function Research({ d }: { d: DayTraderSummary }) {
  const [search, setSearch] = useState("");
  const query = search.trim().toLowerCase();
  const opportunities = d.opportunities.filter(item => {
    const row = object(item);
    return !query || value(row.symbol ?? row.ticker ?? row.canonical_id).toLowerCase().includes(query);
  });
  const plans = d.plans.filter(item => {
    const row = object(item);
    return !query || value(row.symbol ?? row.ticker ?? object(row.proposal).canonical_id).toLowerCase().includes(query);
  });
  return <>
    <div className="flex flex-wrap items-end justify-between gap-3">
      <p className="max-w-2xl text-sm text-muted">Latest saved local run only. All candidates and proposed entries are non-executable.</p>
      <SearchBox label="Search Day Trader symbols" value={search} onChange={setSearch} placeholder="Search symbol…"/>
    </div>
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title={"Watchlist · " + opportunities.length} provenance={basis(d.runs[0]?.basis)}
        subtitle="A candidate is not an independently qualified trade.">
        <div className="space-y-3">{opportunities.map((item, i) => {
          const row = object(item);
          return <article className="rounded border border-rule p-3" key={i}>
            <div className="flex flex-wrap justify-between gap-2">
              <strong>{value(row.symbol ?? row.ticker ?? row.canonical_id, "Candidate " + (i + 1))}</strong>
              <Badge tone="attention">{value(row.status ?? "RESEARCH")}</Badge>
            </div>
            <p className="my-2 text-xs text-muted">{value(row.reason ?? row.description, "Scanner output · research only")}</p>
            {details("Inspect candidate evidence", item)}
          </article>;
        })}{!opportunities.length && <p className="text-sm text-muted">No candidates match this saved run and search.</p>}</div>
      </Panel>
      <Panel title={"Entry / exit plans · " + plans.length} provenance={basis(d.runs[0]?.basis)}
        subtitle="Entry, stop and target are research hypotheses, not executable eToro quotes.">
        <div className="space-y-3">{plans.map((item, i) => {
          const row = object(item), proposal = object(row.proposal), decision = object(proposal.sidedeck_decision);
          return <article key={i} className="rounded border border-rule p-3">
            <div className="flex flex-wrap justify-between gap-2">
              <strong>{value(row.symbol ?? row.ticker, "Plan " + (i + 1))}</strong>
              <Badge tone="attention">{value(decision.status ?? row.result, "NOT ADMITTED")}</Badge>
            </div>
            <div className="my-2"><KeyValues rows={[
              ["Direction", value(row.direction ?? proposal.direction)],
              ["Entry", value(row.entry ?? proposal.entry)], ["Stop", value(row.stop ?? proposal.stop)],
              ["Target", value(row.target ?? proposal.target)],
              ["Decision reasons", value(decision.reasons ?? row.reason)],
            ]}/></div>
            <p className="mb-2 text-xs text-muted">No broker order permission.</p>
            {details("Inspect full plan evidence", item)}
          </article>;
        })}{!plans.length && <p className="text-sm text-muted">No plans match this saved run and search.</p>}</div>
      </Panel>
    </div>
  </>;
}

function Audit({ d }: { d: DayTraderSummary }) {
  const [search, setSearch] = useState("");
  const query = search.trim().toLowerCase();
  const runs = d.runs.filter(r => !query || [r.run_id, r.status, r.basis].some(v => v.toLowerCase().includes(query)));
  return <>
    <Panel title="Append-only run history" provenance={null}
      subtitle="Details on the other tabs reflect the latest run only; historical rows are metadata, not replay controls.">
      <div className="mb-3"><SearchBox label="Find a saved run" value={search} onChange={setSearch}/></div>
      {runs.length ? <div className="overflow-x-auto"><table className="w-full min-w-[600px] text-left text-xs">
        <caption className="sr-only">Saved Day Trader research runs</caption>
        <thead><tr className="border-b border-rule text-muted">
          <th scope="col" className="p-2">Created</th><th scope="col" className="p-2">Run ID</th>
          <th scope="col" className="p-2">Basis</th><th scope="col" className="p-2">Status</th>
          <th scope="col" className="p-2">Digest</th>
        </tr></thead>
        <tbody>{runs.map(r => <tr key={r.run_id} className="border-b border-rule/60">
          <td className="p-2">{when(r.created_at)}</td>
          <td className="p-2 font-mono">{r.run_id.slice(0, 14)}</td>
          <td className="p-2">{words(r.basis)}</td>
          <td className="p-2"><Badge tone={r.status === "OK" ? "accent" : "attention"}>{words(r.status)}</Badge></td>
          <td className="p-2 font-mono">{r.report_sha256.slice(0, 14)}…</td>
        </tr>)}</tbody>
      </table></div> : <p className="text-sm text-muted">No run history matches the search.</p>}
    </Panel>
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title={"Rejected · " + d.rejected.length} provenance={basis(d.runs[0]?.basis)}>
        <div className="space-y-2">{d.rejected.slice(0, 25).map((x, i) =>
          <div key={i}>{details(value(object(x).symbol ?? object(x).result, "Rejection " + (i + 1)), x)}</div>)}
          {!d.rejected.length && <p className="text-sm text-muted">No rejections in the latest saved run.</p>}
        </div>
      </Panel>
      <Panel title={"Stage errors · " + d.errors.length} provenance={null}>
        <div className="space-y-2">{d.errors.slice(0, 25).map((x, i) =>
          <div key={i}>{details(value(object(x).stage ?? object(x).skill, "Stage " + (i + 1)), x)}</div>)}
          {!d.errors.length && <p className="text-sm text-muted">No errors in the latest saved run.</p>}
        </div>
      </Panel>
    </div>
    <Panel title="Pinned module and limitations" provenance={null}>
      <KeyValues rows={[
        ["Source", d.source.name + " " + d.source.version], ["Pinned commit", d.source.commit],
        ["Verification", d.source.verification], ["Skill capabilities", d.capabilities.length],
      ]}/>
      <details className="mt-3 text-xs"><summary className="cursor-pointer text-accent">Inspect all capabilities</summary>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{d.capabilities.map(c =>
          <div className="rounded border border-rule p-3" key={c.id}>
            <p className="font-medium">{c.id}</p><p className="mt-1 text-muted">{c.role}</p></div>)}</div>
      </details>
      <p className="mt-3 text-xs text-muted">{d.limitations.join(" ")}</p>
    </Panel>
  </>;
}

export default function DayTrader() {
  const [section, setSection] = useState<Section>("desk");
  const state = useResource("/api/day-trader/summary", isDayTraderSummary);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="text-xs uppercase tracking-[0.18em] text-accent">SideDeck / intraday workstation</p>
        <h2 className="mt-1 text-2xl font-semibold">Day Trader</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">Research, watchlists, proposed trades, simulation and operational readiness in one workspace.</p>
      </div>
      <Badge tone="blocked">eToro Demo · NOT RELEASED</Badge>
    </div>
    <div role="status" className="rounded border border-attention/35 bg-attention/5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-sm">Execution locked</strong>
        <Badge tone="attention">Research only</Badge>
        <Badge>Real trading excluded</Badge>
      </div>
      <p className="mt-1 text-xs text-muted">This screen cannot read .env credentials or send orders. A local scenario is not an eToro Demo fill, and green CI is not an owner-signed release.</p>
    </div>
    <Tabs label="Day Trader workspaces" tabs={sections} value={section} onChange={setSection} idPrefix="day-trader"/>
    <div role="tabpanel" id="day-trader-panel" aria-labelledby={"day-trader-tab-" + section} className="space-y-4" tabIndex={0}>
      {section === "readiness" ? <Readiness/> :
        <StateBlock resource={state} staleAfterMs={300_000}>{d =>
          section === "desk" ? <Desk d={d}/> : section === "research"
            ? <Research d={d}/> : <Audit d={d}/>}</StateBlock>}
    </div>
  </div>;
}
