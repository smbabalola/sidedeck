import { useState } from "react";
import type { DayTraderSummary, Provenance } from "../lib/contracts";
import { Badge, DataTable, KeyValues, Panel, SearchBox, type Column } from "../components/ui";

type Candidate = {
  key: string;
  symbol: string;
  status: string;
  score: number | null;
  reason: string;
  hasPlan: boolean;
  plan: Record<string, unknown> | null;
  raw: unknown;
};

const object = (x: unknown): Record<string, unknown> =>
  x !== null && typeof x === "object" && !Array.isArray(x) ? x as Record<string, unknown> : {};
const text = (x: unknown, fallback = "—"): string =>
  typeof x === "string" || typeof x === "number" || typeof x === "boolean" ? String(x) : fallback;
const symbolOf = (x: unknown) => {
  const row = object(x);
  return text(row.symbol ?? row.ticker ?? row.canonical_id, "");
};
const evidenceBasis = (basis?: string): Provenance =>
  basis && (basis.includes("FIXTURE") || basis.includes("SYNTH"))
    ? "SYNTHETIC_FIXTURE" : "UNAVAILABLE";

const columns: Column<Candidate>[] = [
  { key: "symbol", header: "Symbol", render: row => <span className="font-semibold text-ink">{row.symbol}</span>,
    sortValue: row => row.symbol },
  { key: "score", header: "Research score", align: "right",
    render: row => row.score === null ? "—" : row.score.toFixed(2),
    sortValue: row => row.score },
  { key: "stage", header: "Scanner outcome", render: row => <Badge tone="attention">{row.status}</Badge>,
    sortValue: row => row.status, hideBelow: "md" },
  { key: "plan", header: "Plan", render: row => row.hasPlan ? <Badge tone="accent">Research plan</Badge> : "—",
    sortValue: row => row.hasPlan ? 1 : 0 },
];

function buildCandidates(d: DayTraderSummary): Candidate[] {
  const plans = new Map<string, Record<string, unknown>>();
  d.plans.forEach(plan => {
    const symbol = symbolOf(plan);
    if (symbol && !plans.has(symbol)) plans.set(symbol, object(plan));
  });
  return d.opportunities.map((raw, index) => {
    const row = object(raw);
    const symbol = symbolOf(raw) || `Candidate ${index + 1}`;
    const score = typeof row.score === "number" && Number.isFinite(row.score)
      ? row.score : null;
    const plan = plans.get(symbol) ?? null;
    return {
      key: `${symbol}-${index}`, symbol, score, plan, hasPlan: plan !== null,
      status: text(row.status ?? row.result, "RESEARCH"),
      reason: text(row.reason ?? row.description, "No scanner reason provided."),
      raw,
    };
  });
}

/** Read-only selection of local research evidence; never contains an order action. */
export default function DayTraderCandidateDesk({ summary }: { summary: DayTraderSummary }) {
  const [query, setQuery] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const candidates = buildCandidates(summary);
  const matches = candidates.filter(row => row.symbol.toLowerCase().includes(query.trim().toLowerCase()));
  const selected = matches.find(row => row.key === selectedKey) ?? matches[0] ?? null;
  const record = selected?.plan ?? null;
  const proposal = object(record?.proposal);
  const decision = object(proposal.sidedeck_decision);
  const provenance = evidenceBasis(summary.runs[0]?.basis);

  return <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]">
    <Panel title="Candidate watchlist" provenance={provenance}
      subtitle="Sorted research candidates. Scores are not trade probabilities or investment advice.">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <SearchBox label="Filter research candidates" value={query} onChange={setQuery}
          placeholder="Search ticker…"/>
        <span className="text-xs text-muted">{matches.length} of {candidates.length} candidates · {summary.plans.length} plans</span>
      </div>
      <DataTable rows={matches} columns={columns} rowKey={row => row.key}
        caption="Day Trader research candidate watchlist"
        initialSort={{ key: "score", dir: "desc" }}
        onRowSelect={row => setSelectedKey(row.key)} selectedKey={selected?.key ?? null}
        maxRows={100}/>
    </Panel>
    <Panel title="Selected candidate" provenance={provenance}
      subtitle="An inspection panel, not an executable order ticket.">
      {selected ? <>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
          <div><p className="text-xs text-muted">Selected instrument</p>
            <p className="mt-1 text-xl font-semibold">{selected.symbol}</p></div>
          <Badge tone="attention">{selected.status}</Badge>
        </div>
        <KeyValues rows={[
          ["Scanner score", selected.score === null ? "Unavailable" : selected.score.toFixed(2)],
          ["Reason", selected.reason],
          ["SideDeck decision", record ? text(decision.status, "Not admitted") : "No saved plan"],
          ["Entry hypothesis", record ? text(record.entry ?? proposal.entry) : "—"],
          ["Stop hypothesis", record ? text(record.stop ?? proposal.stop) : "—"],
          ["Target hypothesis", record ? text(record.target ?? proposal.target) : "—"],
        ]}/>
        <div className="mt-4 rounded border border-rule bg-raised/50 px-3 py-3">
          <p className="text-xs font-medium">Price chart unavailable</p>
          <p className="mt-1 text-xs text-muted">No approved, timestamped five-minute OHLCV series is attached to this saved run. A candlestick chart will appear only when validated bars exist.</p>
        </div>
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-accent">Inspect saved research evidence</summary>
          <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words text-muted">{JSON.stringify({ candidate: selected.raw, plan: selected.plan }, null, 2)}</pre>
        </details>
        <p className="mt-3 text-xs text-attention">Fixture/research only — no eToro Demo order or admitted strategy.</p>
      </> : <p className="py-4 text-sm text-muted">No candidates match your filter. Clear the search to review the saved research run.</p>}
    </Panel>
  </div>;
}
