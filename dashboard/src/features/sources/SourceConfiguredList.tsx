import { Pencil } from "lucide-react";

import type { Source } from "../../api";
import { ResponsiveDataList } from "../../components/ResponsiveDataList";
import { SortableHeader } from "../../components/SortableHeader";

export function SourceConfiguredList({
  sources,
  sortKey,
  sortDirection,
  onSort,
  onEdit,
  onToggle,
}: {
  sources: Source[];
  sortKey: string;
  sortDirection: "asc" | "desc";
  onSort: (key: string) => void;
  onEdit: (source: Source) => void;
  onToggle: (source: Source) => void;
}) {
  return (
    <ResponsiveDataList
      cards={sources.map((source) => (
        <div
          className="rounded-md border border-zinc-800 bg-zinc-950/30 p-3"
          data-testid={`source-card-${source.id}`}
          key={source.id}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="font-semibold text-zinc-100">{source.name}</div>
            <input
              aria-label={`${source.enabled ? "Disable" : "Enable"} ${source.name}`}
              checked={source.enabled}
              className="toggle toggle-sm"
              onChange={() => onToggle(source)}
              type="checkbox"
            />
          </div>
          <div className="mt-2 text-xs text-base-content/60">
            {source.region} · {source.category} · {source.polling_interval_seconds}s
          </div>
          <button
            aria-label={`Edit ${source.name}`}
            className="btn btn-xs btn-outline btn-primary mt-3"
            onClick={() => onEdit(source)}
            type="button"
          >
            <Pencil className="h-3.5 w-3.5" />
            Edit
          </button>
        </div>
      ))}
      table={
        <table className="table w-full max-w-4xl">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
              <SortableHeader
                label="Name"
                sortKey="name"
                currentSortKey={sortKey}
                direction={sortDirection}
                onSort={onSort}
              />
              <SortableHeader
                label="Region"
                sortKey="region"
                currentSortKey={sortKey}
                direction={sortDirection}
                onSort={onSort}
              />
              <SortableHeader
                label="Category"
                sortKey="category"
                currentSortKey={sortKey}
                direction={sortDirection}
                onSort={onSort}
              />
              <SortableHeader
                label="Score"
                sortKey="source_score"
                currentSortKey={sortKey}
                direction={sortDirection}
                onSort={onSort}
              />
              <SortableHeader
                label="Interval"
                sortKey="polling_interval_seconds"
                currentSortKey={sortKey}
                direction={sortDirection}
                onSort={onSort}
              />
              <SortableHeader
                label="Enabled"
                sortKey="enabled"
                currentSortKey={sortKey}
                direction={sortDirection}
                onSort={onSort}
              />
              <th className="px-4 py-3 text-left">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/40">
            {sources.map((source) => (
              <tr key={source.id} className="border-b border-zinc-800/30">
                <td className="py-3 px-4 text-sm font-semibold text-zinc-200">{source.name}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{source.region}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{source.category}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                  {source.source_score}
                </td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                  {source.polling_interval_seconds}s
                </td>
                <td className="py-3 px-4">
                  <input
                    aria-label={`${source.enabled ? "Disable" : "Enable"} ${source.name}`}
                    checked={source.enabled}
                    className="toggle toggle-sm"
                    onChange={() => onToggle(source)}
                    type="checkbox"
                  />
                </td>
                <td className="py-3 px-4">
                  <button
                    aria-label={`Edit ${source.name}`}
                    className="btn btn-xs btn-ghost"
                    onClick={() => onEdit(source)}
                    type="button"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  );
}
