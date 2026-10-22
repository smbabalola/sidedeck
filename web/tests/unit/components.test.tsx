import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable, Panel, ProvenanceBadge, StateBlock, Tabs } from "../../src/components/ui";

type Row = { id: string; v: number | null };
const rows: Row[] = [{ id: "a", v: 2 }, { id: "b", v: null }, { id: "c", v: 5 }];
const cols = [
  { key: "id", header: "Id", render: (r: Row) => r.id, sortValue: (r: Row) => r.id },
  { key: "v", header: "Value", render: (r: Row) => String(r.v ?? "—"), sortValue: (r: Row) => r.v },
];

describe("DataTable", () => {
  it("sorts with unknown values last in both directions and exposes aria-sort", async () => {
    render(<DataTable rows={rows} columns={cols} rowKey={r => r.id} caption="t"/>);
    const button = screen.getByRole("button", { name: /Value/ });
    await userEvent.click(button);
    const ids = () => within(screen.getByRole("table")).getAllByRole("row").slice(1).map(r => r.textContent?.[0]);
    expect(ids()).toEqual(["c", "a", "b"]);
    expect(screen.getByRole("columnheader", { name: /Value/ })).toHaveAttribute("aria-sort", "descending");
    await userEvent.click(screen.getByRole("button", { name: /^Id/ }));
    expect(ids()).toEqual(["a", "b", "c"]);   // text sorts A to Z first
    await userEvent.click(button);
    await userEvent.click(button);
    expect(ids()).toEqual(["a", "c", "b"]);
  });
  it("selects rows with the keyboard", async () => {
    const onSelect = vi.fn();
    render(<DataTable rows={rows} columns={cols} rowKey={r => r.id} caption="t" onRowSelect={onSelect}/>);
    screen.getByRole("button", { name: "Show details for a" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(rows[0]);
  });
});

describe("StateBlock", () => {
  const reload = vi.fn();
  it("shows loading, error with retry, empty and content states", async () => {
    const { rerender } = render(<StateBlock resource={{ state: "loading", data: null, error: null, fetchedAt: null, reload }}>{() => "x"}</StateBlock>);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    rerender(<StateBlock resource={{ state: "error", data: null, error: "Boom", fetchedAt: 1, reload }}>{() => "x"}</StateBlock>);
    expect(screen.getByRole("alert")).toHaveTextContent("Boom");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(reload).toHaveBeenCalled();
    rerender(<StateBlock resource={{ state: "ready", data: [], error: null, fetchedAt: Date.now(), reload }} empty={d => (d.length ? null : "Nothing")}>{() => "x"}</StateBlock>);
    expect(screen.getByText("Nothing")).toBeInTheDocument();
    rerender(<StateBlock resource={{ state: "ready", data: [1], error: null, fetchedAt: Date.now() - 10_000, reload }} staleAfterMs={1000}>{() => "content"}</StateBlock>);
    expect(screen.getByText("content")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/older than expected/);
  });
});

describe("Provenance and panels", () => {
  it("labels synthetic data plainly and panels are labelled regions", () => {
    render(<Panel title="Scan" provenance="SYNTHETIC_FIXTURE">body</Panel>);
    expect(screen.getByRole("region", { name: "Scan" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic fixture")).toHaveAttribute("title", expect.stringMatching(/Not market data/));
    render(<ProvenanceBadge value="REAL_DATA"/>);
    expect(screen.getByText("Real data")).toBeInTheDocument();
  });
});

describe("Tabs", () => {
  it("moves with arrow keys", async () => {
    const onChange = vi.fn();
    render(<Tabs idPrefix="t" label="t" value="A" onChange={onChange} tabs={[{ id: "A", label: "A" }, { id: "B", label: "B" }, { id: "C", label: "C" }]}/>);
    const a = screen.getByRole("tab", { name: "A" });
    expect(a).toHaveAttribute("aria-controls", "t-panel");
    a.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("B");
    await userEvent.keyboard("{End}");
    expect(onChange).toHaveBeenLastCalledWith("C");
  });
});
