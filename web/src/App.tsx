import { useEffect, useState } from "react";
import { Activity, ArrowUpRight, BarChart3, Bot, BrainCircuit, CircleAlert, CircleCheck, Database, LayoutDashboard, LockKeyhole, Moon, ShieldCheck, Wallet } from "lucide-react";
import "./index.css";

type Book = { id: string; title: string; positions: number; pnlStatus: "AVAILABLE" | "UNAVAILABLE"; allocation: string; description: string };
const initialBooks: Book[] = [
  { id: "tradingagents", title: "TradingAgents", positions: 0, pnlStatus: "AVAILABLE", allocation: "NOT ALLOCATED", description: "Independent strategy book" },
  { id: "ai-trading", title: "AI-Trading", positions: 0, pnlStatus: "AVAILABLE", allocation: "NOT ALLOCATED", description: "Independent strategy book" },
  { id: "unattributed", title: "Existing portfolio", positions: 4, pnlStatus: "AVAILABLE", allocation: "NOT ALLOCATED", description: "Immutable baseline · protected positions" },
];
function StatusPill({ children, positive = false }: { children: React.ReactNode; positive?: boolean }) {
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${positive ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-300" : "border-slate-700 bg-slate-800/70 text-slate-300"}`}>{children}</span>;
}
function Stat({ title, value, detail, icon: Icon }: { title: string; value: string; detail: string; icon: typeof Wallet }) {
  return <section className="rounded-2xl border border-slate-700/60 bg-panel p-5 shadow-glow"><div className="flex items-center justify-between"><p className="text-sm text-slate-400">{title}</p><Icon size={18} className="text-slate-400" aria-hidden="true"/></div><p className="mt-5 text-3xl font-semibold tracking-tight text-white">{value}</p><p className="mt-2 text-xs text-slate-400">{detail}</p></section>;
}
export default function App() {
  const [activeBook, setActiveBook] = useState("all");
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const [summary, setSummary] = useState<{ protected_positions: number | null; captured_at: string | null; books: {id: string; positions: number | null}[]; fresh_snapshot?: { observed_at: string; reconciliation_status: string; discrepancy_count: number | null; available_cash_usd_status: string; books: {id: string; positions: number | null}[] } | null } | null>(null);
  const [apiError, setApiError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/demo/summary", { signal: controller.signal, cache: "no-store" })
      .then(response => { if (!response.ok) throw Error("API unavailable"); return response.json(); })
      .then(data => {
        if (data.schema_version !== 1 || data.source !== "LOCAL_BASELINE_ONLY" || data.execution_enabled !== false || !Array.isArray(data.books)) throw Error("API schema mismatch");
        setSummary(data);
      })
      .catch(() => { if (!controller.signal.aborted) setApiError(true); });
    return () => controller.abort();
  }, []);
  const observed = summary?.fresh_snapshot ? Date.parse(summary.fresh_snapshot.observed_at) : NaN;
  const fresh = Number.isFinite(observed) && clock >= observed && clock - observed <= 300000 ? summary?.fresh_snapshot : null;
  const books = initialBooks.map(b => ({...b, positions: (fresh?.books ?? summary?.books)?.find(x => x.id === "etoro-demo:" + b.id)?.positions ?? null, pnlStatus: "UNAVAILABLE" }));

  const shown = activeBook === "all" ? books : books.filter(b => b.id === activeBook);
  return <div className="min-h-screen bg-ink text-slate-100">
    <div className="flex min-h-screen">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-800 bg-[#0C1625] px-5 py-7 lg:flex">
        <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-ink"><BarChart3 size={23}/></div><div><div className="text-xl font-bold tracking-tight">SideDeck</div><div className="text-xs text-slate-500">Research workstation</div></div></div>
        <div className="mt-12 space-y-2">
          <div className="flex items-center gap-3 rounded-xl border border-accent/20 bg-accent/10 px-4 py-3 text-sm font-semibold text-accent"><LayoutDashboard size={17}/> Demo portfolio</div>
          <div className="flex items-center gap-3 px-4 py-3 text-sm text-slate-500"><Activity size={17}/> Strategy analytics <span className="ml-auto text-[10px] uppercase">Soon</span></div>
          <div className="flex items-center gap-3 px-4 py-3 text-sm text-slate-500"><Database size={17}/> Evidence center <span className="ml-auto text-[10px] uppercase">Soon</span></div>
        </div>
        <div className="mt-auto rounded-xl border border-slate-700 bg-raised p-4"><div className="flex items-center gap-2 text-sm text-emerald-300"><ShieldCheck size={16}/> Execution locked</div><p className="mt-2 text-xs leading-5 text-slate-400">All broker order submission remains disabled. This screen contains no broker connectivity.</p></div>
      </aside>
      <main className="mx-auto w-full max-w-[1520px] px-5 py-7 sm:px-8 lg:px-12">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[.16em] text-accent"><Moon size={13}/> Trading workspace <span className="text-slate-600">/</span> eToro Demo</div><h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Portfolio overview</h1><p className="mt-2 max-w-2xl text-sm text-slate-400">A protected baseline and three isolated books. No live connection or monetary balances are displayed in this preview.</p></div>
          <div className="flex flex-wrap gap-2"><StatusPill positive><CircleCheck size={13}/> {fresh ? "Fresh Demo snapshot" : "Saved baseline only"}</StatusPill><StatusPill><LockKeyhole size={13}/> Read-only</StatusPill></div>
        </header>
        <div className="mt-7 flex items-start gap-3 rounded-xl border border-amber-400/20 bg-amber-400/5 px-4 py-3 text-sm text-amber-100"><CircleAlert size={18} className="mt-0.5 shrink-0 text-amber-300"/><p><strong>Local baseline, not live.</strong> {apiError ? "Backend unavailable. Start the local SideDeck service." : summary ? `Baseline captured ${summary.captured_at ?? "at an unknown time"}.` : "Loading baseline metadata."} {fresh ? `Fresh owner-authorized snapshot ${fresh.observed_at}. Reconciliation: ${fresh.reconciliation_status}.` : "No recent authorized snapshot. Current portfolio reconciliation, cash and P&L are unavailable."}</p></div>
        <div className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat title="Protected positions" value={summary?.protected_positions?.toString() ?? "—"} detail="Saved holdings · unattributed" icon={ShieldCheck}/>
          <Stat title="Strategy positions" value={fresh ? String((fresh.books[0]?.positions ?? 0) + (fresh.books[1]?.positions ?? 0)) : "—"} detail={fresh ? "Owner-authorized snapshot" : "Current positions unavailable"} icon={BrainCircuit}/>
          <Stat title="Reconciliation exceptions" value={fresh?.discrepancy_count?.toString() ?? "—"} detail={fresh ? fresh.reconciliation_status : "Current reconciliation unavailable"} icon={CircleCheck}/>
          <Stat title="Available cash (USD)" value="—" detail={fresh ? `Status: ${fresh.available_cash_usd_status} · amount withheld` : "Status: UNAVAILABLE · no live data"} icon={Wallet}/>
        </div>
        <div className="mt-9 flex flex-wrap items-end justify-between gap-4"><div><h2 className="text-xl font-semibold">Strategy books</h2><p className="mt-1 text-sm text-slate-400">Positions and capital remain segregated by attribution.</p></div><label className="flex items-center gap-3 text-sm text-slate-400">View <select aria-label="Filter strategy books" value={activeBook} onChange={e => setActiveBook(e.target.value)} className="rounded-lg border border-slate-700 bg-panel px-3 py-2 text-slate-100"><option value="all">All books</option>{books.map(b => <option value={b.id} key={b.id}>{b.title}</option>)}</select></label></div>
        <div className="mt-5 grid gap-4 lg:grid-cols-3">
          {shown.map(b => <article key={b.id} className="rounded-2xl border border-slate-700/60 bg-panel p-6">
            <div className="flex items-center justify-between"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-raised text-accent">{b.id === "tradingagents" ? <BrainCircuit size={21}/> : b.id === "ai-trading" ? <Bot size={21}/> : <ShieldCheck size={21}/>}</div><StatusPill>{b.id === "unattributed" ? "Protected" : "Unallocated"}</StatusPill></div>
            <h3 className="mt-5 text-lg font-semibold">{b.title}</h3><p className="mt-1 text-sm text-slate-400">{b.description}</p>
            <div className="mt-6 grid grid-cols-2 gap-4 border-t border-slate-800 pt-5"><div><p className="text-xs text-slate-500">Positions</p><p className="mt-1 text-2xl font-semibold tabular-nums">{b.positions ?? "—"}</p></div><div><p className="text-xs text-slate-500">Capital</p><p className="mt-2 text-xs font-semibold text-amber-300">{b.allocation}</p></div></div>
            <div className="mt-5 flex items-center justify-between rounded-lg bg-raised px-3 py-2.5 text-xs"><span className="text-slate-400">Unrealised P&amp;L status</span><span className="font-semibold text-amber-300">UNAVAILABLE</span></div>
          </article>)}
        </div>
        <section className="mt-8 overflow-hidden rounded-2xl border border-slate-700/60 bg-panel">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 px-6 py-5"><div><h2 className="text-lg font-semibold">Portfolio safeguards</h2><p className="mt-1 text-sm text-slate-400">{fresh ? "Latest owner-authorized snapshot; no orders possible." : "Baseline stored locally; current reconciliation not available."}</p></div><StatusPill><CircleAlert size={14}/> {fresh ? `Reconciliation: ${fresh.reconciliation_status}` : "Not currently reconciled"}</StatusPill></div>
          <div className="grid gap-px bg-slate-800 md:grid-cols-3"><div className="bg-panel p-6"><LockKeyhole size={20} className="text-accent"/><h3 className="mt-3 font-semibold">No order capability</h3><p className="mt-2 text-sm leading-6 text-slate-400">There are no buy, sell, close or order-management controls in this application.</p></div><div className="bg-panel p-6"><ShieldCheck size={20} className="text-accent"/><h3 className="mt-3 font-semibold">Baseline protected</h3><p className="mt-2 text-sm leading-6 text-slate-400">Four pre-existing positions are assigned only to the unattributed book.</p></div><div className="bg-panel p-6"><ArrowUpRight size={20} className="text-accent"/><h3 className="mt-3 font-semibold">No inferred allocations</h3><p className="mt-2 text-sm leading-6 text-slate-400">Each strategy needs an explicit owner decision before virtual capital can appear.</p></div></div>
        </section>
        <footer className="mt-8 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><span>SideDeck · eToro Demo portfolio UI preview</span><span>Local baseline summary · No broker calls</span></footer>
      </main>
    </div>
  </div>;
}
