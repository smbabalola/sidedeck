import { useResource } from "../lib/api";
import { type MarketTrack, type ScanCandidate, type TrackId, isMarketTracks, isScanSnapshot, TRACKS } from "../lib/contracts";
import { compactUsd, num, plainPct, when, words } from "../lib/format";
import { href } from "../lib/router";
import { Badge, type Column, DataTable, KeyValues, Panel, StateBlock, Tabs, tabId, tabPanelId } from "../components/ui";

const PURPOSE: Record<TrackId, string> = {
  DAY: "Short-term moves inside one session. Positions are flat before the close; nothing carries overnight.",
  SWING: "Moves over roughly 2 to 15 trading days, from daily bars with intraday confirmation where data allows.",
  POSITION: "Weeks to months, combining daily prices with SEC-based fundamental research.",
};

function TrackView({ track }: { track: MarketTrack }) {
  const scan = useResource("/api/market/scan", isScanSnapshot);
  const loaded = scan.state === "ready" && scan.data.status === "LOADED" ? scan.data : null;
  const tickers = Object.fromEntries((loaded?.instruments ?? []).map(i => [i.canonical_id, i]));
  const b = track.risk_budget;
  const columns: Column<ScanCandidate>[] = [
    { key: "rank", header: "Rank", align: "right", render: c => c.rank, sortValue: c => c.rank },
    { key: "inst", header: "Instrument", render: c => <a className="hover:text-accent" href={href("markets", c.canonical_id)}><span className="font-medium">{tickers[c.canonical_id]?.ticker ?? c.canonical_id}</span> <span className="text-faint">{tickers[c.canonical_id]?.exchange ?? ""}</span></a>, sortValue: c => c.canonical_id },
    { key: "score", header: "Score", align: "right", render: c => num(c.score, 3), sortValue: c => (c.score === null ? null : Number(c.score)) },
    { key: "stage", header: "Stage", render: c => c.research ? <Badge tone="accent">Research shortlist</Badge> : <Badge>Quantitative shortlist</Badge> },
    { key: "missing", header: "Missing inputs", render: c => c.missing.length ? <span className="text-attention">{c.missing.map(words).join(", ")}</span> : <span className="text-faint">None</span>, hideBelow: "md" },
    { key: "source", header: "Source", render: () => <span className="text-muted">Scanner sd067 v1, {words(track.track)}</span>, hideBelow: "lg" },
  ];
  return <div className="space-y-4">
    <p className="max-w-3xl text-sm text-muted">{PURPOSE[track.track]}</p>
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel title="Status and data" provenance={null}>
        <div className="mb-3 flex flex-wrap gap-2">
          <Badge>{words(track.mode)}</Badge>
          <Badge tone="blocked">Execution {words(track.execution).toLowerCase()}</Badge>
          {track.data_status === "AVAILABLE" ? <Badge tone="attention">Approved source: {track.usable_sources.map(words).join(", ")}</Badge> : <Badge tone="blocked">No approved data source</Badge>}
        </div>
        <KeyValues rows={[
          ["Horizon", track.horizon_trading_days[1] === 0 ? "Same session" : `${track.horizon_trading_days[0]}–${track.horizon_trading_days[1]} trading days`],
          ["Usable sources", track.usable_sources.length ? track.usable_sources.map(words).join(", ") : "None"],
          ["Minimum price", `$${track.filters.min_price}`],
          ["Minimum daily $ volume", compactUsd(track.filters.min_dollar_adv)],
          ["Minimum history", `${track.filters.min_sessions} sessions`],
          ["Spread data", track.filters.spread_required ? "Required" : "Optional"],
          ["Shortlist sizes", `${track.shortlist_sizes.quant} quantitative, ${track.shortlist_sizes.research} research`],
        ]}/>
      </Panel>
      <Panel title="Risk budget" provenance={null} subtitle="Research configuration for simulation. Not an authorization and not allocated capital.">
        <KeyValues rows={[
          ["Virtual capital", words(b.virtual_capital)],
          ["Risk per trade", plainPct(b.risk_per_trade_pct)],
          ["Maximum positions", b.max_positions],
          ["Maximum drawdown", plainPct(b.max_drawdown_pct, 0)],
          ["Daily loss limit", plainPct(b.max_daily_loss_pct, 0)],
          ["Orders per day", b.max_orders_per_day],
          ["Exit policy", words(b.exit_policy)],
        ]}/>
        <p className="mt-3 text-xs text-muted">Changing these values or releasing execution needs the owner's signed authorization, which this screen cannot provide.</p>
      </Panel>
      <Panel title="Schedule" provenance={null} subtitle="New York market calendar, shown in your local time.">
        <ul className="space-y-2 text-xs">
          {track.jobs.map(j => <li key={j.job_id} className="flex items-center justify-between gap-2">
            <span>{words(j.job_id)}</span>
            {Number.isFinite(Date.parse(j.next_run_utc)) ? <time dateTime={j.next_run_utc} className="tabular-nums text-muted">{when(j.next_run_utc)}</time> : <Badge tone="attention">{words(j.next_run_utc)}</Badge>}
          </li>)}
        </ul>
        <p className="mt-3 text-xs text-muted">The scheduler plans runs; nothing executes in the background without a running SideDeck worker.</p>
      </Panel>
    </div>
    <Panel title="Candidates" provenance={loaded ? loaded.provenance : "UNAVAILABLE"} subtitle={loaded ? `Close of ${loaded.cutoff}. Ranking heuristics, not forecasts.` : undefined}>
      <StateBlock resource={scan} empty={s => (s.status === "LOADED" ? null : `No scanner snapshot: ${s.reason}.`)}>{() => loaded && <>
        {loaded.tracks[track.track].candidates.length === 0
          ? <p className="text-sm text-muted">No candidates passed this track's filters{track.filters.spread_required ? " (spread data is required and none was supplied)" : ""}.</p>
          : <DataTable rows={loaded.tracks[track.track].candidates} columns={columns} rowKey={c => c.canonical_id} caption={`${track.track} candidates`} initialSort={{ key: "rank", dir: "asc" }}/>}
        {Object.keys(loaded.tracks[track.track].filtered).length > 0 && <div className="mt-4">
          <h3 className="text-xs font-semibold text-muted">Why others were filtered out</h3>
          <div className="mt-2 flex flex-wrap gap-2">{Object.entries(loaded.tracks[track.track].filtered).map(([k, v]) => <Badge key={k}>{words(k)}: {v}</Badge>)}</div>
        </div>}
      </>}</StateBlock>
    </Panel>
    <Panel title="Signals and decisions" provenance="UNAVAILABLE" subtitle="Research signals and decision-engine outcomes for this track.">
      <p className="text-sm text-muted">No signals are recorded yet. Agent research needs an owner-approved model budget (SD-008), and the decision engine only reports. Every signal will show its source, version and track when present.</p>
    </Panel>
  </div>;
}

export default function Tracks({ detail }: { detail: string | null }) {
  const tracks = useResource("/api/market/tracks", isMarketTracks);
  const active: TrackId = TRACKS.includes(detail as TrackId) ? (detail as TrackId) : "SWING";
  return <StateBlock resource={tracks}>{t => {
    const track = t.tracks.find(x => x.track === active);
    return <div className="space-y-4">
      <Tabs idPrefix="tracks" label="Trading track" value={active} onChange={id => { window.location.hash = href("tracks", id); }}
        tabs={TRACKS.map(id => ({ id, label: words(id), hint: t.tracks.find(x => x.track === id)?.data_status === "AVAILABLE" ? undefined : "data blocked" }))}/>
      <div role="tabpanel" id={tabPanelId("tracks")} aria-labelledby={tabId("tracks", active)} tabIndex={0}>{track ? <TrackView track={track}/> : <p className="text-sm text-muted">Track not reported by the service.</p>}</div>
    </div>;
  }}</StateBlock>;
}
