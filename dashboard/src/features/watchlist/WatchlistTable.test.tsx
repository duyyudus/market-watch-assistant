import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WatchlistEntry } from "../../api";
import { WatchlistTable } from "./WatchlistTable";

const rows: WatchlistEntry[] = [
  {
    id: "watch_1",
    symbol: "ZZZ",
    name: "Alpha Asset",
    entity_type: "stock",
    tier: "B",
    region: "us",
    asset_class: "equity",
    aliases: ["Alpha"],
    enabled: false,
  },
  {
    id: "watch_2",
    symbol: "AAA",
    name: "Zulu Asset",
    entity_type: "etf",
    tier: "A",
    region: "global",
    asset_class: "fund",
    aliases: [],
    enabled: true,
  },
];

function firstDataRow() {
  return screen.getAllByRole("row")[1];
}

describe("WatchlistTable", () => {
  it("renders watchlist fields in a table and sorts supported columns", () => {
    render(<WatchlistTable rows={rows} presets={null} retry={vi.fn()} />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.getAllByRole("columnheader").map((header) => header.textContent?.trim()),
    ).toEqual([
      "Symbol",
      "Name",
      "Entity type",
      "Tier",
      "Region",
      "Asset class",
      "Aliases",
      "Enabled",
      "Actions",
    ]);
    expect(within(firstDataRow()).getByText("AAA")).toBeInTheDocument();
    expect(within(firstDataRow()).getByText("Enabled")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("columnheader", { name: /symbol/i }));
    expect(within(firstDataRow()).getByText("ZZZ")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("columnheader", { name: /name/i }));
    expect(within(firstDataRow()).getByText("Alpha Asset")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("columnheader", { name: /tier/i }));
    expect(within(firstDataRow()).getByText("AAA")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("columnheader", { name: /entity type/i }));
    expect(within(firstDataRow()).getByText("etf")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("columnheader", { name: /region/i }));
    expect(within(firstDataRow()).getByText("global")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("columnheader", { name: /asset class/i }));
    expect(within(firstDataRow()).getByText("equity")).toBeInTheDocument();
  });
});
