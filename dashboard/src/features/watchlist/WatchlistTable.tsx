import { RefreshCcw, Star } from "lucide-react";

import type { WatchlistEntry } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { useSortableData } from "../../hooks/useSortableData";
import { classNames } from "../../lib/classNames";

export function WatchlistTable({
  rows,
  error,
  retry,
}: {
  rows: WatchlistEntry[];
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "symbol",
    direction: "asc",
  });

  return (
    <Panel title="Watchlist">
      {error ? (
        <SectionError title="Watchlist unavailable" message={error} retry={retry} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Star}
          title="No watchlist entries yet"
          body="Tracked assets and entities will appear here after they are added through CLI or Phase 2 configuration UI."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
        <>
          <div className="flex items-center justify-between border-b border-zinc-800/40 pb-3 mb-4 text-xs text-zinc-500">
            <span>{sortedRows.length} assets watched</span>
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-zinc-500">Sort by:</span>
              <button
                onClick={() => requestSort("symbol")}
                className={classNames(
                  "hover:text-primary transition-colors flex items-center gap-0.5",
                  sortConfig.key === "symbol" && "text-primary font-semibold",
                )}
                type="button"
              >
                Symbol
                {sortConfig.key === "symbol" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
              </button>
              <button
                onClick={() => requestSort("name")}
                className={classNames(
                  "hover:text-primary transition-colors flex items-center gap-0.5",
                  sortConfig.key === "name" && "text-primary font-semibold",
                )}
                type="button"
              >
                Name
                {sortConfig.key === "name" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
              </button>
              <button
                onClick={() => requestSort("tier")}
                className={classNames(
                  "hover:text-primary transition-colors flex items-center gap-0.5",
                  sortConfig.key === "tier" && "text-primary font-semibold",
                )}
                type="button"
              >
                Tier
                {sortConfig.key === "tier" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
              </button>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {sortedRows.map((row) => (
              <div
                key={row.id}
                className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4 transition-all duration-150 hover:border-zinc-700/80"
              >
                <div className="flex items-center justify-between">
                  <div className="text-base font-bold text-zinc-100">{row.symbol ?? row.name}</div>
                  <Badge tone={row.enabled ? "success" : "neutral"}>{row.tier}</Badge>
                </div>
                <div className="mt-1.5 text-sm text-base-content/75">{row.name}</div>
                <div className="mt-2.5 text-xs text-base-content/60">
                  {row.region ?? "global"} · {row.asset_class ?? row.entity_type}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

