import { RefreshCcw, TerminalSquare } from "lucide-react";

import type { BotCommand } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";
import { formatTime } from "../../lib/time";
import type { QueueCommand } from "../../types/dashboard";

export function CommandsTable({
  rows,
  compact = false,
  error,
  retry,
  queue,
}: {
  rows: BotCommand[];
  compact?: boolean;
  error?: string;
  retry: () => Promise<void>;
  queue: QueueCommand;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "created_at",
    direction: "desc",
  });

  if (error) {
    return <SectionError title="Command queue unavailable" message={error} retry={retry} />;
  }

  return (
    <div className="space-y-3">
      {!compact ? (
        <div className="flex flex-wrap gap-2">
          <button
            className="btn btn-sm btn-primary"
            onClick={() => queue("pipeline.run", { dry_run: true })}
            type="button"
          >
            Dry-run pipeline
          </button>
          <button
            className="btn btn-sm btn-outline"
            onClick={() => queue("retention.preview", {})}
            type="button"
          >
            Preview retention
          </button>
        </div>
      ) : null}
      {sortedRows.length === 0 ? (
        <EmptyState
          icon={TerminalSquare}
          title="No commands queued"
          body="Manual bot commands will appear here after an operator queues one."
          action={
            compact ? null : (
              <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
                <RefreshCcw className="h-4 w-4" />
                Refresh
              </button>
            )
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="table w-full">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
                <SortableHeader
                  label="Command"
                  sortKey="command_type"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Status"
                  sortKey="status"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Created"
                  sortKey="created_at"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                {!compact ? (
                  <SortableHeader
                    label="Payload"
                    sortKey="payload"
                    currentSortKey={sortConfig.key}
                    direction={sortConfig.direction}
                    onSort={requestSort}
                  />
                ) : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {sortedRows.map((row) => (
                <tr key={row.id} className="border-b border-zinc-800/30">
                  <td className="py-3 px-4 text-sm font-semibold text-zinc-200">
                    {row.command_type}
                  </td>
                  <td className="py-3 px-4 text-xs">
                    <Badge
                      tone={
                        row.status === "failed"
                          ? "error"
                          : row.status === "succeeded"
                            ? "success"
                            : "info"
                      }
                    >
                      {row.status}
                    </Badge>
                  </td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                    {formatTime(row.created_at)}
                  </td>
                  {!compact ? (
                    <td className="py-3 px-4 text-zinc-400 font-normal text-xs max-w-[360px] truncate">
                      {JSON.stringify(row.payload)}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

