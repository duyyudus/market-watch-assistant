import { Newspaper, RefreshCcw } from "lucide-react";

import type { NewsItem } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";
import { formatTime } from "../../lib/time";

export function NewsTable({
  rows,
  error,
  retry,
}: {
  rows: NewsItem[];
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "time",
    direction: "desc",
  });

  return (
    <Panel title="Normalized news">
      {error ? (
        <SectionError title="Normalized news unavailable" message={error} retry={retry} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Newspaper}
          title="No normalized news yet"
          body="Ingested news will appear here after source fetch and normalization jobs run."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="table w-full">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
                <SortableHeader
                  label="Title"
                  sortKey="title"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Source"
                  sortKey="source_name"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Status"
                  sortKey="processing_status"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Region"
                  sortKey="region"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Time"
                  sortKey="time"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {sortedRows.map((row) => (
                <tr key={row.id} className="border-b border-zinc-800/30">
                  <td className="py-3 px-4 max-w-[620px] whitespace-normal text-sm font-semibold text-zinc-200">
                    {row.title}
                  </td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                    {row.source_name}
                  </td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                    {row.processing_status}
                  </td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.region}</td>
                  <td className="py-3 px-4 text-zinc-500 font-normal text-xs">
                    {formatTime(row.published_at ?? row.fetched_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

