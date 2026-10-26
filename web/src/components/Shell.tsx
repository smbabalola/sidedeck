import { type KeyboardEvent as ReactKeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { Activity, BarChart3, Bot, Briefcase, Gauge, Layers, LockKeyhole, Menu, Moon, Radar, Sun, Wrench, X } from "lucide-react";
import { type ReleaseGate, isReleaseGate } from "../lib/contracts";
import { useResource } from "../lib/api";
import { WORKSPACES, type WorkspaceId, href } from "../lib/router";
import type { Theme } from "../lib/theme";
import { words } from "../lib/format";

const ICONS: Record<WorkspaceId, typeof Gauge> = {
  overview: Gauge, engine: BarChart3, markets: Radar, tracks: Layers, agents: Bot, strategies: Activity, portfolio: Briefcase, operations: Wrench, "day-trader": Radar,
};

type Gate = ReturnType<typeof useResource<ReleaseGate>>;

function LockStatus({ gate, compact = false }: { gate: Gate; compact?: boolean }) {
  const locked = gate.state !== "ready" || gate.data.broker_execution === "DISABLED";
  const text = gate.state === "ready" ? `Execution ${words(gate.data.overall_status).toLowerCase()} · orders ${words(gate.data.paper_order_submission).toLowerCase()}`
    : gate.state === "loading" ? "Checking execution lock…" : "Lock status unknown: treat as locked";
  return <div role="status" className={`flex items-center gap-2 ${compact ? "text-xs" : "rounded border border-attention/40 bg-attention/5 px-3 py-2 text-xs"} text-attention`}>
    <LockKeyhole size={14} aria-hidden/>
    {compact ? <>
      <span className="sm:hidden">{locked ? "Locked" : "Check lock"}<span className="sr-only">: {text}</span></span>
      <span className="hidden sm:inline">{locked ? text : "Unexpected lock state"}</span>
    </> : <span>{locked ? text : "Unexpected lock state"}</span>}
  </div>;
}

function NavLinks({ active, onNavigate }: { active: WorkspaceId; onNavigate?: () => void }) {
  return <ul className="space-y-0.5">
    {WORKSPACES.map(w => {
      const Icon = ICONS[w.id];
      const current = w.id === active;
      return <li key={w.id}>
        <a href={href(w.id)} onClick={onNavigate} aria-current={current ? "page" : undefined}
          className={`flex items-center gap-3 rounded px-3 py-2 text-sm ${current ? "bg-raised font-medium text-ink" : "text-muted hover:bg-raised/60 hover:text-ink"}`}>
          <Icon size={16} aria-hidden className={current ? "text-accent" : ""}/>{w.label}
        </a>
      </li>;
    })}
  </ul>;
}

export function Shell({ active, theme, onToggleTheme, children }: { active: WorkspaceId; theme: Theme; onToggleTheme: () => void; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const gate = useResource("/api/research/release-gate", isReleaseGate);
  const title = WORKSPACES.find(w => w.id === active)?.label ?? "Overview";
  useEffect(() => { document.title = `${title} · SideDeck`; setOpen(false); }, [title]);
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);
  const asideRef = useRef<HTMLElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Make the page behind the modal drawer inert (not focusable or clickable).
    for (const el of [asideRef.current, contentRef.current]) el?.toggleAttribute("inert", open);
  }, [open]);
  useEffect(() => {
    if (open) {
      closeButton.current?.focus();
      wasOpen.current = true;
      const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
    if (wasOpen.current) { menuButton.current?.focus(); wasOpen.current = false; }
    return undefined;
  }, [open]);
  // Keep Tab inside the drawer while it is open (the rest of the page is also inert).
  const trapFocus = (e: ReactKeyboardEvent) => {
    if (e.key !== "Tab" || !drawer.current) return;
    const items = drawer.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled])");
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  const skip = (e: { preventDefault: () => void }) => { e.preventDefault(); document.getElementById("main")?.focus(); };
  const brand = <div className="flex items-center gap-2.5 px-3"><BarChart3 size={20} className="text-accent" aria-hidden/><span className="text-base font-semibold tracking-tight">SideDeck</span></div>;
  return <div className="min-h-screen bg-canvas text-ink">
    <a href="#main" onClick={skip} className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-panel focus:px-3 focus:py-2">Skip to content</a>
    <div className="flex min-h-screen">
      <aside ref={asideRef} className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-rule bg-panel py-4 lg:flex" aria-label="Workspaces">
        {brand}
        <nav className="mt-6 flex-1 px-2" aria-label="Primary"><NavLinks active={active}/></nav>
        <div className="px-3"><LockStatus gate={gate}/></div>
      </aside>
      {open && <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation" onKeyDown={trapFocus}>
        <div aria-hidden="true" className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)}/>
        <div ref={drawer} className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-rule bg-panel py-4">
          <div className="flex items-center justify-between pr-3">{brand}<button ref={closeButton} type="button" onClick={() => setOpen(false)} aria-label="Close navigation" className="rounded p-1.5 text-muted hover:text-ink"><X size={18}/></button></div>
          <nav className="mt-6 flex-1 px-2" aria-label="Primary mobile"><NavLinks active={active} onNavigate={() => setOpen(false)}/></nav>
          <div className="px-3"><LockStatus gate={gate}/></div>
        </div>
      </div>}
      <div ref={contentRef} className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-rule bg-canvas/95 px-4 py-2.5 backdrop-blur sm:px-6">
          <button ref={menuButton} type="button" onClick={() => setOpen(true)} aria-label="Open navigation" aria-expanded={open} className="rounded p-1.5 text-muted hover:text-ink lg:hidden"><Menu size={18}/></button>
          <h1 className="text-base font-semibold">{title}</h1>
          <div className="ml-auto flex items-center gap-3">
            <LockStatus gate={gate} compact/>
            <button type="button" onClick={onToggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              className="rounded border border-rule p-1.5 text-muted hover:text-ink">{theme === "dark" ? <Sun size={15}/> : <Moon size={15}/>}</button>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5 sm:px-6">{children}</main>
        <footer className="border-t border-rule px-4 py-3 text-xs text-faint sm:px-6">Read-only research workstation. This interface has no order, close or capital controls.</footer>
      </div>
    </div>
  </div>;
}
