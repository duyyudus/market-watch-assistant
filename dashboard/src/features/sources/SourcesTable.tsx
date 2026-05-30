import { Radio, RefreshCcw } from "lucide-react";

import { api, type Source } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";

export function SourcesTable({
  rows,
  error,
  reload,
}: {
  rows: Source[];
  error?: string;
  reload: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "name",
    direction: "asc",
  });

  async function toggle(row: Source) {
    await api.setSourceEnabled(row.id, !row.enabled);
    await reload();
  }

  return (
    <Panel title="Sources">
      {error ? (
        <SectionError title="Sources unavailable" message={error} retry={reload} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Radio}
          title="No sources configured"
          body="Source configuration will appear here after feed sources are added to the shared database."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void reload()} type="button">
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
                  label="Name"
                  sortKey="name"
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
                  label="Category"
                  sortKey="category"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Score"
                  sortKey="source_score"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Interval"
                  sortKey="polling_interval_seconds"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Enabled"
                  sortKey="enabled"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {sortedRows.map((row) => (
                <tr key={row.id} className="border-b border-zinc-800/30">
                  <td className="py-3 px-4 text-sm font-semibold text-zinc-200">{row.name}</td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.region}</td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.category}</td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                    {row.source_score}
                  </td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                    {row.polling_interval_seconds}s
                  </td>
                  <td className="py-3 px-4">
                    <input
                      className="toggle toggle-sm"
                      checked={row.enabled}
                      onChange={() => void toggle(row)}
                      type="checkbox"
                    />
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

