import { useMemo, useState } from "react";
import { useResource } from "../lib/api";
import { type LoadedScan, type ScanInstrument, type TrackId, isMarketTracks, isScanSnapshot, TRACKS } from "../lib/contracts";
import { compactUsd, num, pct, plainPct, price, tone, when, words } from "../lib/format";
import { href } from "../lib/router";
import { Badge, type Column, DataTable, KeyValues, Metric, Panel, SearchBox, Select, StateBlock } from "../components/ui";

type TrackFilter = "ALL" | TrackId;
type FlagFilter = "ANY" | "BREAKOUT" | "SWEEP" | "ABOVE_200" | "BELOW_200";

const signed = (v: string | null) => {
  const t = tone(v);
  return <span className={t === "gain" ? "text-gain" : t === "loss" ? "text-loss" : t === "unknown" ? "text-faint" : ""}>{pct(v)}</span>;
};
const n = (v: string | null) => (v === null ? null : Number(v));

function rankIndex(scan: LoadedScan): Record<string, Partial<Record<TrackId, number>>> {
  const out: Record<string, Partial<Record<TrackId, number>>> = {};
  for (const t of TRACKS) for (const c of scan.tracks[t].candidates) (out[c.canonical_id] ??= {})[t] = c.rank;
  return out;
}

function InstrumentDetail({ scan, inst }: { scan: LoadedScan; inst: ScanInstrument }) {
  return <div className="space-y-4">
    <div>
      <p className="text-lg font-semibold">{inst.ticker} <span className="text-sm font-normal text-muted">{inst.exchange}</span></p>
      <p className="text-xs text-muted">{inst.canonical_id} · close of {scan.cutoff} · {inst.sessions} sessions · source {scan.source_id}</p>
    </div>
    <dl className="grid grid-cols-3 gap-3">
      <Metric label="Last close" value={price(inst.last_close)}/>
      <Metric label="20-day" value={pct(inst.ret_20)} tone={tone(inst.ret_20) === "loss" ? "loss" : tone(inst.ret_20) === "gain" ? "gain" : undefined}/>
      <Metric label="ATR" value={plainPct(inst.atr_pct)}/>
    </dl>
    <KeyValues rows={[
      ["5 / 60 / 126-day return", <>{pct(inst.ret_5)} / {pct(inst.ret_60)} / {pct(inst.ret_126)}</>],
      ["Relative strength vs benchmark (60d)", inst.rs_60 === null ? "Unavailable" : pct(inst.rs_60)],
      ["Realised volatility (20d, annualised)", plainPct(inst.vol20)],
      ["Average daily $ volume (20d)", compactUsd(inst.dollar_adv20)],
      ["Volume vs 20-day average", inst.unusual_volume === null ? "—" : `${num(inst.unusual_volume)}×`],
      ["Opening gap", pct(inst.gap_pct)],
      ["Above 200-day average", inst.above_sma200 === null ? "Insufficient history" : inst.above_sma200 ? "Yes" : "No"],
      ["Market regime (benchmark)", words(inst.regime)],
      ["Events", inst.event_flags.length ? inst.event_flags.map(words).join(", ") : "None supplied"],
    ]}/>
    <div>
      <h3 className="text-xs font-semibold text-muted">Track candidacy</h3>
      <ul className="mt-2 space-y-2">
        {TRACKS.map(t => {
          const c = scan.tracks[t].candidates.find(x => x.canonical_id === inst.canonical_id);
          return <li key={t} className="rounded border border-rule p-2.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <a href={href("tracks", t)} className="font-medium hover:text-accent">{words(t)}</a>
              {c ? <span className="flex items-center gap-1.5">{c.research && <Badge tone="accent">Research shortlist</Badge>}<Badge>Rank {c.rank}</Badge></span> : <Badge>Not shortlisted</Badge>}
            </div>
            {c && <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-faint">
              {Object.entries(c.components).map(([k, v]) => <span key={k} className="flex justify-between gap-2"><span>{words(k)}</span><span className="tabular-nums text-ink">{v === null ? "missing" : num(v, 3)}</span></span>)}
            </div>}
          </li>;
        })}
      </ul>
      <p className="mt-2 text-xs text-muted">Scores are percentile-rank heuristics for ordering research, not forecasts or orders.</p>
    </div>
  </div>;
}

export default function Markets({ detail }: { detail: string | null }) {
  const scan = useResource("/api/market/scan", isScanSnapshot);
  const tracks = useResource("/api/market/tracks", isMarketTracks);
  const [query, setQuery] = useState("");
  const [track, setTrack] = useState<TrackFilter>("ALL");
  const [flag, setFlag] = useState<FlagFilter>("ANY");
  const [exchange, setExchange] = useState("ALL");

  const loaded = scan.state === "ready" && scan.data.status === "LOADED" ? scan.data : null;
  const ranks = useMemo(() => (loaded ? rankIndex(loaded) : {}), [loaded]);
  const exchanges = useMemo(() => (loaded ? [...new Set(loaded.instruments.map(i => i.exchange))].sort() : []), [loaded]);
  const rows = useMemo(() => {
    if (!loaded) return [];
    const q = query.trim().toUpperCase();
    return loaded.instruments.filter(i =>
      (!q || i.ticker.includes(q) || i.canonical_id.toUpperCase().includes(q))
      && (exchange === "ALL" || i.exchange === exchange)
      && (track === "ALL" || ranks[i.canonical_id]?.[track] !== undefined)
      && (flag === "ANY" || (flag === "BREAKOUT" && i.breakout_20) || (flag === "SWEEP" && i.sweep_reversal_20)
        || (flag === "ABOVE_200" && i.above_sma200 === true) || (flag === "BELOW_200" && i.above_sma200 === false)));
  }, [loaded, query, exchange, track, flag, ranks]);
  const selected = loaded?.instruments.find(i => i.canonical_id === detail) ?? null;

  const columns: Column<ScanInstrument>[] = [
    { key: "ticker", header: "Instrument", render: i => <span><span className="font-medium">{i.ticker}</span> <span className="text-faint">{i.exchange}</span></span>, sortValue: i => i.ticker },
    { key: "close", header: "Close", align: "right", render: i => price(i.last_close), sortValue: i => n(i.last_close) },
    { key: "r20", header: "20d", align: "right", render: i => signed(i.ret_20), sortValue: i => n(i.ret_20) },
    { key: "r60", header: "60d", align: "right", render: i => signed(i.ret_60), sortValue: i => n(i.ret_60), hideBelow: "sm" },
    { key: "rs", header: "RS 60d", align: "right", render: i => signed(i.rs_60), sortValue: i => n(i.rs_60), hideBelow: "xl" },
    { key: "atr", header: "ATR", align: "right", render: i => plainPct(i.atr_pct), sortValue: i => n(i.atr_pct), hideBelow: "md" },
    { key: "adv", header: "$ volume", align: "right", render: i => compactUsd(i.dollar_adv20), sortValue: i => n(i.dollar_adv20), hideBelow: "sm" },
    { key: "flags", header: "Setups", render: i => <span className="flex gap-1">{i.breakout_20 && <Badge tone="accent">Breakout</Badge>}{i.sweep_reversal_20 && <Badge tone="accent">Sweep</Badge>}{i.above_sma200 === false && <Badge>Below 200d</Badge>}</span>, hideBelow: "2xl" },
    { key: "shortlists", header: "Shortlists", align: "left",
      render: i => {
        const r = ranks[i.canonical_id] ?? {};
        const items = TRACKS.filter(t => r[t] !== undefined);
        return items.length ? <span className="flex gap-1">{items.map(t => <Badge key={t} tone={track === t ? "accent" : "neutral"}>{words(t)} #{r[t]}</Badge>)}</span> : <span className="text-faint">None</span>;
      },
      sortValue: i => {
        const r = ranks[i.canonical_id] ?? {};
        const values = (track === "ALL" ? TRACKS : [track]).map(t => r[t]).filter((v): v is number => v !== undefined);
        return values.length ? Math.min(...values) : null;
      } },
  ];

  return <div className="space-y-4">
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel title="US universe" provenance={tracks.state === "ready" && tracks.data.universe.status === "SNAPSHOT_LOADED" ? "REAL_DATA" : "UNAVAILABLE"}>
        <StateBlock resource={tracks}>{t => t.universe.status === "SNAPSHOT_LOADED"
          ? <dl className="grid grid-cols-2 gap-4"><Metric label="Listed symbols" value={t.universe.instruments?.toLocaleString()} detail={`Snapshot ${when(t.universe.retrieved_at)}`}/><Metric label="Tradability" value="Not assessed" tone="attention" detail="No broker mapping implied"/></dl>
          : <p className="text-sm text-muted">No genuine universe yet. It loads after the owner signs the SD-075A authorization (two public Nasdaq Trader files).</p>}</StateBlock>
      </Panel>
      <Panel title="Latest scan" provenance={loaded ? loaded.provenance : "UNAVAILABLE"}>
        <StateBlock resource={scan}>{s => s.status === "LOADED"
          ? <dl className="grid grid-cols-3 gap-4"><Metric label="Scanned" value={`${s.scanned}/${s.universe_size}`}/><Metric label="Close of" value={new Date(s.cutoff + "T12:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric" })} detail={s.cutoff}/><Metric label="Duration" value={`${s.duration_seconds.toFixed(1)} s`}/></dl>
          : <p className="text-sm text-muted">{s.reason}. Run a scan to populate this view.</p>}</StateBlock>
      </Panel>
      <Panel title="Excluded instruments" provenance={loaded ? loaded.provenance : "UNAVAILABLE"} subtitle="Stale, future-dated or malformed data is excluded, never repaired.">
        {loaded ? (Object.keys(loaded.excluded).length
          ? <KeyValues rows={Object.entries(loaded.excluded).map(([k, v]) => [words(k), v])}/>
          : <p className="text-sm text-muted">None in the latest scan.</p>) : <p className="text-sm text-muted">—</p>}
      </Panel>
    </div>

    {loaded?.provenance === "SYNTHETIC_FIXTURE" && <p role="note" className="hatch rounded border border-attention/50 px-3 py-2 text-sm text-attention">
      These rows come from a synthetic fixture generator ({loaded.source_id}). They test the scanner and this screen; they are not market data.</p>}

    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Panel title="Scanner results" provenance={loaded ? loaded.provenance : "UNAVAILABLE"} subtitle={loaded ? `${rows.length} of ${loaded.instruments.length} instruments · ${loaded.data_basis}` : undefined}>
        <StateBlock resource={scan} empty={s => (s.status === "LOADED" ? null : "No scanner snapshot is available.")}>{() => <>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <SearchBox label="Search" value={query} onChange={setQuery} placeholder="Ticker or ID"/>
            <Select label="Exchange" value={exchange} onChange={setExchange} options={[{ value: "ALL", label: "All exchanges" }, ...exchanges.map(e => ({ value: e, label: e }))]}/>
            <Select<TrackFilter> label="Shortlisted for" value={track} onChange={setTrack} options={[{ value: "ALL", label: "Any track" }, ...TRACKS.map(t => ({ value: t, label: words(t) }))]}/>
            <Select<FlagFilter> label="Setup" value={flag} onChange={setFlag} options={[
              { value: "ANY", label: "Any" }, { value: "BREAKOUT", label: "20-day breakout" }, { value: "SWEEP", label: "Liquidity sweep" },
              { value: "ABOVE_200", label: "Above 200-day" }, { value: "BELOW_200", label: "Below 200-day" }]}/>
          </div>
          <DataTable rows={rows} columns={columns} rowKey={i => i.canonical_id} caption="Scanner results"
            initialSort={{ key: "shortlists", dir: "asc" }} selectedKey={detail}
            onRowSelect={i => { window.location.hash = href("markets", i.canonical_id); }}/>
        </>}</StateBlock>
      </Panel>
      <Panel title="Instrument detail" provenance={loaded && selected ? loaded.provenance : "UNAVAILABLE"} className="xl:sticky xl:top-16 xl:self-start">
        {loaded && selected ? <InstrumentDetail scan={loaded} inst={selected}/>
          : <p className="text-sm text-muted">{detail && loaded ? `${detail} is not in the latest scan.` : "Select a row to see identity, features and why it ranks where it does."}</p>}
      </Panel>
    </div>
  </div>;
}
