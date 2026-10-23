import { useResource } from "../lib/api";
import { type TrackId, type UkIdentity, type UkMarkets as UkData, type UkScan, isUkMarkets, TRACKS } from "../lib/contracts";
import { gbp, num, when, words } from "../lib/format";
import { Badge, type Column, DataTable, KeyValues, Metric, Panel, StateBlock } from "../components/ui";

const identityColumns: Column<UkIdentity>[] = [
  { key: "tidm", header: "TIDM", render: i => <span className="font-medium">{i.tidm ?? "—"}</span>, sortValue: i => i.tidm },
  { key: "isin", header: "ISIN", render: i => i.isin ?? "—", sortValue: i => i.isin, hideBelow: "sm" },
  { key: "name", header: "Name", render: i => i.name ?? "—", sortValue: i => i.name, hideBelow: "lg" },
  { key: "unit", header: "Source unit", render: i => <span>{i.source_unit ?? "—"}{i.divisor && i.divisor !== "1" ? <span className="text-faint"> ÷{i.divisor}</span> : null}</span>, hideBelow: "md" },
  { key: "close", header: "Last close (GBP)", align: "right", render: i => gbp(i.last_close_gbp), sortValue: i => (i.last_close_gbp === null ? null : Number(i.last_close_gbp)) },
  { key: "bar", header: "Last bar", render: i => i.last_bar ?? "—", sortValue: i => i.last_bar, hideBelow: "sm" },
  { key: "retrieved", header: "Retrieved", render: i => when(i.retrieved_at), sortValue: i => i.retrieved_at, hideBelow: "xl" },
];

function ScanView({ scan, label }: { scan: UkScan; label: string }) {
  return <div className="space-y-4">
    <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <Metric label="Close of" value={scan.cutoff}/>
      <Metric label="Scanned" value={`${scan.scanned}/${scan.universe}`}/>
      <Metric label="Native signals" value={scan.signals}/>
      <Metric label="Acceptance" value={words(scan.acceptance)} tone="attention"/>
    </dl>
    <div className="grid gap-4 lg:grid-cols-3">
      {TRACKS.map((t: TrackId) => {
        const rows = scan.rankings[t];
        const filtered = scan.filtered[t] ?? {};
        return <div key={t} className="min-w-0 rounded border border-rule p-3">
          <h3 className="text-xs font-semibold text-ink">{words(t)} ranking <span className="font-normal text-faint">({label})</span></h3>
          {rows.length
            ? <ol className="mt-2 space-y-1 text-xs">{rows.slice(0, 10).map(r => <li key={r.canonical_id} className="flex justify-between gap-2"><span className="min-w-0 truncate">#{r.rank} {r.canonical_id}</span><span className="tabular-nums text-muted">{num(r.score, 3)}</span></li>)}</ol>
            : <p className="mt-2 text-xs text-muted">No candidates.</p>}
          {Object.keys(filtered).length > 0 && <div className="mt-3"><p className="text-2xs text-faint">Filtered (reason: count)</p>
            <KeyValues rows={Object.entries(filtered).map(([k, v]): [string, number] => [words(k), v])}/></div>}
        </div>;
      })}
    </div>
    {(scan.excluded.length > 0 || Object.keys(scan.scan_exclusions).length > 0) && <div>
      <h3 className="text-xs font-semibold text-ink">Rejected before ranking</h3>
      <p className="text-2xs text-faint">Stale, incomplete, ineligible or malformed series are excluded, never repaired.</p>
      <KeyValues rows={[...scan.excluded.map(([id, why]): [string, string] => [id, words(why)]),
        ...Object.entries(scan.scan_exclusions).map(([why, count]): [string, string] => [words(why), String(count)])]}/>
    </div>}
    {Object.keys(scan.decision_counts).length > 0 && <div className="flex flex-wrap gap-1">{Object.entries(scan.decision_counts).map(([k, v]) => <Badge key={k}>{words(k)}: {v}</Badge>)}</div>}
  </div>;
}

function Calendar({ c }: { c: UkData["calendar"] }) {
  return <Panel title="London Stock Exchange calendar" provenance={null} subtitle={`${c.timezone} · continuous ${c.continuous_hours_local} · half days close ${c.half_day_close_local}`}
    actions={<Badge tone="attention" title={c.source_status}>Corroboration pending</Badge>}>
    <div className="grid gap-4 md:grid-cols-2">
      <dl className="grid grid-cols-2 gap-4">
        <Metric label="Market now" value={words(c.status_now)} tone={c.status_now === "OPEN" ? "gain" : undefined}/>
        <Metric label="Last completed session" value={c.last_completed_session ?? "—"}/>
      </dl>
      <div>
        <p className="text-xs text-muted">Next sessions (UTC)</p>
        <ul className="mt-1 space-y-0.5 text-xs tabular-nums">{c.next_sessions.map(s => <li key={s.date}>{s.date} · {s.open_utc.slice(11, 16)}–{s.close_utc.slice(11, 16)}{s.early_close ? " · half day" : ""}</li>)}</ul>
      </div>
    </div>
    {c.half_days_uncorroborated.length > 0 && <p className="mt-3 text-2xs text-faint">Half days awaiting LSE confirmation: {c.half_days_uncorroborated.join(", ")}</p>}
  </Panel>;
}

export default function UkMarkets() {
  const uk = useResource("/api/market/uk", isUkMarkets);
  return <StateBlock resource={uk}>{d => {
    const g = d.genuine;
    return <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone="blocked">UK broker execution disabled</Badge>
        <Badge tone="neutral">Research only · prices in GBP</Badge>
        {(["A", "B", "C"] as const).map(k => <Badge key={k} tone="attention" title="SD-094 bounded data request">SD-094{k}: {words(d.authorizations[k])}</Badge>)}
      </div>
      <Calendar c={d.calendar}/>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="UK universe and data" provenance={g.provenance} className="lg:col-span-2"
          subtitle={g.provenance === "REAL_DATA" ? "Owner-supplied licensed files (owner-declared basis)" : "No licensed UK data is loaded"}>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Metric label="Status" value={words(g.status)} tone={g.provenance === "REAL_DATA" ? undefined : "attention"}/>
            <Metric label="Instruments" value={g.identities.length}/>
            <Metric label="Rejected rows" value={g.rejected} tone={g.rejected ? "attention" : undefined}/>
            <Metric label="Review flags" value={g.warnings} tone={g.warnings ? "attention" : undefined}/>
          </dl>
          {g.blocker && <p className="mt-3 text-sm text-muted">{g.blocker}</p>}
          {g.identities.length > 0 && <div className="mt-4"><DataTable rows={g.identities} columns={identityColumns} rowKey={i => i.canonical_id} caption="UK instrument identities and price units" initialSort={{ key: "tidm", dir: "asc" }}/></div>}
        </Panel>
        <Panel title="FTSE membership" provenance={g.provenance} subtitle="Dated evidence only; snapshot lists are never backdated.">
          {g.memberships.length
            ? <KeyValues rows={g.memberships.map((m): [string, string] => [m.canonical_id, `${m.index_id} · ${words(m.basis)} from ${m.start}${m.end ? ` to ${m.end}` : ""}`])}/>
            : <p className="text-sm text-muted">No FTSE 100/250 membership evidence loaded.</p>}
        </Panel>
      </div>
      <Panel title="UK scan on genuine data" provenance={g.provenance}>
        {g.scan ? <ScanView scan={g.scan} label="real data"/> : <p className="text-sm text-muted">No genuine UK scan yet. It runs when licensed files are imported (SD-098) or after an owner-signed SD-094 request.</p>}
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Candidate watchlist" provenance={g.provenance} subtitle="Identity must be sourced; abstentions are a valid result.">
          <ul className="space-y-2 text-xs">{g.candidates.map(c => <li key={c.proposed_tidm} className="flex flex-wrap items-center justify-between gap-2">
            <span><span className="font-medium">{c.proposed_tidm}</span> <span className="text-muted">{c.name}</span></span>
            <span className="flex flex-wrap gap-1"><Badge tone={c.result === "WATCHLIST" ? "accent" : "neutral"}>{words(c.result)}</Badge>{c.reasons.map(r => <Badge key={r}>{words(r)}</Badge>)}</span>
          </li>)}</ul>
        </Panel>
        <Panel title="UK tracks" provenance={null} subtitle="Per-exchange jobs on the London calendar; execution cannot be configured.">
          <ul className="space-y-3 text-xs">{d.tracks.map(t => <li key={t.track}>
            <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{words(t.track)}</span><Badge>{words(t.mode)}</Badge><Badge tone="attention">{words(t.data_status)}</Badge></div>
            <ul className="mt-1 text-faint">{t.jobs.map(j => <li key={j.job_id}>{j.job_id}{j.enabled ? ` · next ${when(j.next_run_utc)}` : " · disabled"}</li>)}</ul>
          </li>)}</ul>
        </Panel>
      </div>
      <Panel title="Fixture scan (pipeline test)" provenance={d.fixture ? "SYNTHETIC_FIXTURE" : "UNAVAILABLE"} subtitle="Synthetic instruments (ZZ ISINs). Not market data.">
        {d.fixture ? <ScanView scan={d.fixture} label="fixture"/> : <p className="text-sm text-muted">{d.report_reason ?? "No fixture report."}</p>}
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Simulated UK trade" provenance={d.simulation ? "SIMULATION" : "UNAVAILABLE"} subtitle="Local simulated venue; not broker fills.">
          {d.simulation ? <KeyValues rows={[
            ["Instrument", d.simulation.instrument.tidm ?? "—"],
            ["GBX ask → GBP", `${d.simulation.gbx_to_gbp.source_ask ?? "—"} → ${gbp(d.simulation.gbx_to_gbp.normalized_ask_gbp)}`],
            ["Reconciliation", words(d.simulation.reconciliation.status)],
            ["Realised P&L (simulated)", gbp(d.simulation.reconciliation.realized_pnl_gbp)],
            ["Open positions", d.simulation.reconciliation.open_positions],
          ]}/> : <p className="text-sm text-muted">{d.report_reason ?? "No simulation report."}</p>}
        </Panel>
        <Panel title="Strategy and agent evidence" provenance="UNAVAILABLE">
          <KeyValues rows={[["Admitted UK strategies", d.evidence.admitted_uk_strategies], ["Research agents", d.evidence.agents]]}/>
          <p className="mt-2 text-2xs text-faint">{d.evidence.note}</p>
        </Panel>
      </div>
    </div>;
  }}</StateBlock>;
}
