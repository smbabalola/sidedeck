// Display helpers. Numbers arrive as decimal strings and are formatted, never invented.

export const dash = "—";

export function words(token: string | null | undefined): string {
  if (!token) return dash;
  const text = token.replace(/[_-]+/g, " ").toLowerCase().replace(/\b(csv|sec|sip|iex|etf|api|oos|atr|rsi)\b/g, m => m.toUpperCase());
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function pct(value: string | number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || value === "") return dash;
  const n = Number(value);
  if (!Number.isFinite(n)) return dash;
  const s = (n * 100).toFixed(digits);
  return `${n > 0 ? "+" : ""}${s}%`;
}

export function plainPct(value: string | number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || value === "") return dash;
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : dash;
}

export function price(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return dash;
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : dash;
}

export function compactUsd(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return dash;
  const n = Number(value);
  if (!Number.isFinite(n)) return dash;
  return "$" + new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function num(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") return dash;
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : dash;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return dash;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return words(iso);
  return new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return dash;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return dash;
  const minutes = Math.round((now - t) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function tone(value: string | number | null | undefined): "gain" | "loss" | "flat" | "unknown" {
  if (value === null || value === undefined || value === "") return "unknown";
  const n = Number(value);
  if (!Number.isFinite(n)) return "unknown";
  return n > 0 ? "gain" : n < 0 ? "loss" : "flat";
}
