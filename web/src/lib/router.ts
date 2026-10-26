import { useEffect, useState } from "react";

export const WORKSPACES = [
  { id: "overview", label: "Overview" },
  { id: "engine", label: "Trading engine" },
  { id: "markets", label: "Markets" },
  { id: "tracks", label: "Trading tracks" },
  { id: "agents", label: "Agents" },
  { id: "strategies", label: "Strategies" },
  { id: "portfolio", label: "Portfolio" },
  { id: "operations", label: "Operations" },
] as const;
export type WorkspaceId = (typeof WORKSPACES)[number]["id"];

export type Route = { workspace: WorkspaceId; detail: string | null };

export function parseRoute(hash: string): Route {
  const [first, ...rest] = hash.replace(/^#\/?/, "").split("/");
  const found = WORKSPACES.find(w => w.id === first);
  let detail: string | null = null;
  if (rest.length) {
    try { detail = decodeURIComponent(rest.join("/")); } catch { detail = null; }
  }
  return { workspace: found ? found.id : "overview", detail: found ? detail : null };
}

export function href(workspace: WorkspaceId, detail?: string): string {
  return `#/${workspace}${detail ? "/" + encodeURIComponent(detail) : ""}`;
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
