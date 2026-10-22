import { type KeyboardEvent, type ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, Loader2, RefreshCw } from "lucide-react";
import type { Provenance } from "../lib/contracts";
import { ago } from "../lib/format";
import type { Resource } from "../lib/api";

// --- Provenance -----------------------------------------------------------------------
const PROVENANCE: Record<Provenance, { label: string; edge: string; help: string }> = {
  REAL_DATA: { label: "Real data", edge: "prov-real", help: "Genuine, provenance-tagged market or filing data." },
  DEMO_BROKER: { label: "Demo broker", edge: "prov-demo", help: "Read from the eToro Demo account under an owner authorization." },
  SIMULATION: { label: "Simulation", edge: "prov-sim", help: "SideDeck's local simulated ledger; not broker fills." },
  SYNTHETIC_FIXTURE: { label: "Synthetic fixture", edge: "prov-synthetic", help: "Generated test data. Not market data and not performance." },
  UNAVAILABLE: { label: "No data", edge: "prov-none", help: "Nothing verified is loaded for this panel." },
};

export function ProvenanceBadge({ value }: { value: Provenance }) {
  const p = PROVENANCE[value];
  const style = value === "SYNTHETIC_FIXTURE" ? "hatch border-attention/50 text-attention"
    : value === "REAL_DATA" ? "border-gain/40 text-gain"
    : value === "UNAVAILABLE" ? "border-rule text-muted" : "border-accent/40 text-accent";
  return <span title={p.help} className={`inline-flex items-center rounded border px-1.5 py-0.5 text-2xs font-medium ${style}`}>{p.label}</span>;
}

// --- Status tones -----------------------------------------------------------------------
export type Tone = "gain" | "loss" | "attention" | "neutral" | "blocked" | "accent";
const TONE: Record<Tone, string> = {
  gain: "border-gain/35 bg-gain/10 text-gain",
  loss: "border-loss/35 bg-loss/10 text-loss",
  attention: "border-attention/40 bg-attention/10 text-attention",
  blocked: "hatch border-attention/50 text-attention",
  accent: "border-accent/35 bg-accent/10 text-accent",
  neutral: "border-rule bg-raised text-muted",
};
export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-2xs font-medium ${TONE[tone]}`}>{children}</span>;
}

// --- Panel ------------------------------------------------------------------------------
/** ``provenance={null}`` is for panels that mix sources or show code-derived status; each row then carries its own badge. */
export function Panel({ title, subtitle, provenance = "UNAVAILABLE", actions, children, className = "", id }: {
  title: string; subtitle?: ReactNode; provenance?: Provenance | null; actions?: ReactNode; children: ReactNode; className?: string; id?: string;
}) {
  const headingId = useId();
  return <section id={id} aria-labelledby={headingId} className={`prov ${provenance ? PROVENANCE[provenance].edge : "prov-none"} min-w-0 rounded-md border border-rule bg-panel ${className}`}>
    <header className="flex flex-wrap items-start justify-between gap-2 border-b border-rule px-4 py-3 pl-5">
      <div className="min-w-0">
        <h2 id={headingId} className="text-sm font-semibold text-ink">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{provenance && <ProvenanceBadge value={provenance}/>}{actions}</div>
    </header>
    <div className="p-4 pl-5">{children}</div>
  </section>;
}

// --- Metrics ----------------------------------------------------------------------------
export function Metric({ label, value, detail, tone }: { label: string; value: ReactNode; detail?: ReactNode; tone?: "gain" | "loss" | "attention" }) {
  const color = tone === "gain" ? "text-gain" : tone === "loss" ? "text-loss" : tone === "attention" ? "text-attention" : "text-ink";
  return <div className="min-w-0">
    <dt className="text-xs text-muted">{label}</dt>
    <dd className={`mt-1 text-xl font-semibold tabular-nums ${color}`}>{value}</dd>
    {detail && <dd className="mt-0.5 text-xs text-faint">{detail}</dd>}
  </div>;
}

export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-xs">
    {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="text-right text-ink tabular-nums">{v}</dd></div>)}
  </dl>;
}

// --- Resource states --------------------------------------------------------------------
/** Current time that re-renders the caller every ``intervalMs`` (for staleness checks). */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), intervalMs); return () => clearInterval(t); }, [intervalMs]);
  return now;
}

export function StateBlock<T>({ resource, empty, staleAfterMs, children }: {
  resource: Resource<T> & { reload: () => void }; empty?: (data: T) => string | null; staleAfterMs?: number; children: (data: T) => ReactNode;
}) {
  const now = useNow();
  if (resource.state === "loading") {
    return <p role="status" className="flex items-center gap-2 py-6 text-sm text-muted"><Loader2 size={15} className="animate-spin" aria-hidden/> Loading…</p>;
  }
  if (resource.state === "error") {
    return <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded border border-loss/30 bg-loss/5 px-3 py-3 text-sm">
      <span className="flex items-center gap-2 text-ink"><AlertTriangle size={15} className="text-loss" aria-hidden/>{resource.error}</span>
      <button type="button" onClick={resource.reload} className="inline-flex items-center gap-1.5 rounded border border-rule px-2.5 py-1 text-xs text-ink hover:bg-raised"><RefreshCw size={13} aria-hidden/> Retry</button>
    </div>;
  }
  const message = empty?.(resource.data);
  if (message) return <p className="py-4 text-sm text-muted">{message}</p>;
  const stale = staleAfterMs !== undefined && now - resource.fetchedAt > staleAfterMs;
  return <>
    {stale && <p role="status" className="mb-3 rounded border border-attention/40 bg-attention/10 px-3 py-2 text-xs text-attention">Data is older than expected (fetched {ago(new Date(resource.fetchedAt).toISOString())}). Reload before relying on it.</p>}
    {children(resource.data)}
  </>;
}

// --- Data table -------------------------------------------------------------------------
export type Column<R> = {
  key: string; header: string; render: (row: R) => ReactNode; sortValue?: (row: R) => number | string | null;
  align?: "left" | "right"; className?: string; hideBelow?: "sm" | "md" | "lg" | "xl" | "2xl";
};
const HIDE = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell", xl: "hidden xl:table-cell", "2xl": "hidden 2xl:table-cell" };

export function DataTable<R>({ rows, columns, rowKey, caption, initialSort, onRowSelect, selectedKey, maxRows = 200 }: {
  rows: R[]; columns: Column<R>[]; rowKey: (row: R) => string; caption: string;
  initialSort?: { key: string; dir: "asc" | "desc" }; onRowSelect?: (row: R) => void; selectedKey?: string | null; maxRows?: number;
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find(c => c.key === sort.key);
    if (!column?.sortValue) return rows;
    const value = column.sortValue;
    return [...rows].sort((a, b) => {
      const x = value(a), y = value(b);
      if (x === null && y === null) return 0;
      if (x === null) return 1;            // unknown values always sort last
      if (y === null) return -1;
      const cmp = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [rows, columns, sort]);
  const shown = sorted.slice(0, maxRows);
  const firstDir = (key: string): "asc" | "desc" => {
    const value = columns.find(c => c.key === key)?.sortValue;
    const sample = value ? rows.map(value).find(v => v !== null) : undefined;
    return typeof sample === "string" ? "asc" : "desc";   // text A to Z, numbers largest first
  };
  const toggle = (key: string) => setSort(s => s?.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: firstDir(key) });
  return <div className="overflow-x-auto">
    <table className="w-full border-collapse text-xs">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-rule text-muted">
          {columns.map(c => {
            const active = sort?.key === c.key;
            const aria = active ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
            return <th key={c.key} scope="col" aria-sort={c.sortValue ? aria : undefined}
              className={`whitespace-nowrap px-2 py-2 font-medium ${c.align === "right" ? "text-right" : "text-left"} ${c.hideBelow ? HIDE[c.hideBelow] : ""}`}>
              {c.sortValue ? <button type="button" onClick={() => toggle(c.key)} className={`inline-flex items-center gap-1 hover:text-ink ${active ? "text-ink" : ""}`}>
                {c.header}{active ? (sort.dir === "asc" ? <ArrowUp size={12} aria-hidden/> : <ArrowDown size={12} aria-hidden/>) : <ArrowUpDown size={12} aria-hidden className="opacity-40"/>}
              </button> : c.header}
            </th>;
          })}
        </tr>
      </thead>
      <tbody>
        {shown.map(row => {
          const key = rowKey(row);
          const selected = selectedKey === key;
          return <tr key={key} aria-current={selected ? "true" : undefined}
            onClick={onRowSelect ? () => onRowSelect(row) : undefined}
            className={`border-b border-rule/60 ${onRowSelect ? "cursor-pointer hover:bg-raised focus-within:bg-raised" : ""} ${selected ? "bg-accent/10" : ""}`}>
            {columns.map((c, i) => <td key={c.key} className={`whitespace-nowrap px-2 py-1.5 tabular-nums ${c.align === "right" ? "text-right" : ""} ${c.hideBelow ? HIDE[c.hideBelow] : ""} ${c.className ?? ""}`}>
              {i === 0 && onRowSelect
                ? <button type="button" className="text-left hover:text-accent" aria-label={`Show details for ${key}`} onClick={e => { e.stopPropagation(); onRowSelect(row); }}>{c.render(row)}</button>
                : c.render(row)}
            </td>)}
          </tr>;
        })}
        {shown.length === 0 && <tr><td colSpan={columns.length} className="px-2 py-6 text-center text-muted">No rows match the current filters.</td></tr>}
      </tbody>
    </table>
    {sorted.length > shown.length && <p className="mt-2 text-xs text-faint">Showing {shown.length} of {sorted.length}. Narrow the filters to see the rest.</p>}
  </div>;
}

// --- Tabs (WAI-ARIA tabs pattern) -------------------------------------------------------
export const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
export const tabPanelId = (prefix: string) => `${prefix}-panel`;

export function Tabs<T extends string>({ label, tabs, value, onChange, idPrefix }: { label: string; tabs: { id: T; label: string; hint?: string }[]; value: T; onChange: (id: T) => void; idPrefix: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (event: KeyboardEvent, index: number) => {
    const keys: Record<string, number> = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 };
    if (!(event.key in keys)) return;
    event.preventDefault();
    const next = (keys[event.key] + tabs.length) % tabs.length;
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  };
  return <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-rule">
    {tabs.map((t, i) => {
      const active = t.id === value;
      return <button key={t.id} ref={el => { refs.current[i] = el; }} type="button" role="tab" id={tabId(idPrefix, t.id)} aria-controls={tabPanelId(idPrefix)} aria-selected={active} tabIndex={active ? 0 : -1}
        onClick={() => onChange(t.id)} onKeyDown={e => onKey(e, i)}
        className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm ${active ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink"}`}>
        {t.label}{t.hint && <span className="ml-1.5 text-xs text-faint">{t.hint}</span>}
      </button>;
    })}
  </div>;
}

export function SearchBox({ value, onChange, label, placeholder }: { value: string; onChange: (v: string) => void; label: string; placeholder?: string }) {
  const id = useId();
  return <div className="flex flex-col gap-1">
    <label htmlFor={id} className="text-xs text-muted">{label}</label>
    <input id={id} type="search" value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
      className="w-full rounded border border-rule bg-raised px-2.5 py-1.5 text-sm text-ink placeholder:text-faint sm:w-56"/>
  </div>;
}

export function Select<T extends string>({ value, onChange, label, options }: { value: T; onChange: (v: T) => void; label: string; options: { value: T; label: string }[] }) {
  const id = useId();
  return <div className="flex flex-col gap-1">
    <label htmlFor={id} className="text-xs text-muted">{label}</label>
    <select id={id} value={value} onChange={e => onChange(e.target.value as T)} className="rounded border border-rule bg-raised px-2.5 py-1.5 text-sm text-ink">
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  </div>;
}
