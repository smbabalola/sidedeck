import { useResource } from "../lib/api";
import { isDayTraderReadiness } from "../lib/contracts";
import { Badge, Panel, StateBlock } from "../components/ui";

const stages = [
  { id: "research", title: "Research", detail: "Offline scans and saved evidence" },
  { id: "market_data", title: "Market data", detail: "Licensed, complete five-minute bars" },
  { id: "strategy", title: "Strategy", detail: "Locked out-of-sample qualification" },
  { id: "offline_cycle", title: "Trade lifecycle", detail: "Simulated open, monitor, exit and reconcile" },
  { id: "broker", title: "eToro Demo", detail: "Signed release and verified broker fills" },
] as const;

export default function DayTraderWorkflow() {
  const readiness = useResource("/api/day-trader/readiness", isDayTraderReadiness);
  return <Panel title="Autonomous trading pipeline" provenance={null}
    subtitle="Read-only engineering status. This is not a live market feed, account connection or order monitor.">
    <StateBlock resource={readiness}>{data => {
      const byId = new Map(data.gates.map(g => [g.id, g]));
      const built = data.gates.filter(g => g.status === "IMPLEMENTED_OFFLINE").length;
      return <>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted">{built} of {data.gates.length} stages implemented offline; none constitute a broker execution release.</p>
          <Badge tone="blocked">Demo transport locked</Badge>
        </div>
        <ol aria-label="Day Trader autonomy implementation stages" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          {stages.map((step, index) => {
            const gate = byId.get(step.id);
            const implemented = gate?.status === "IMPLEMENTED_OFFLINE";
            return <li key={step.id} className="rounded border border-rule bg-raised/40 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-faint">{String(index + 1).padStart(2, "0")}</span>
                <Badge tone={implemented ? "accent" : "blocked"}>
                  {implemented ? "Offline verified" : "Blocked"}
                </Badge>
              </div>
              <h3 className="mt-2 text-sm font-semibold">{step.title}</h3>
              <p className="mt-1 text-xs text-muted">{step.detail}</p>
              <p className="mt-2 border-t border-rule pt-2 text-xs text-faint">{gate?.next_action ?? "No verified status"}</p>
            </li>;
          })}
        </ol>
        <p role="status" className="mt-3 text-xs text-muted">
          Strategy signals and simulated fills are not eToro Demo orders. Real-money execution is permanently excluded.
        </p>
      </>;
    }}</StateBlock>
  </Panel>;
}
