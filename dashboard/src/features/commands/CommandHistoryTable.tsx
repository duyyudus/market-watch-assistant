import { ChevronDown, ChevronRight, RefreshCcw, TerminalSquare, XCircle } from "lucide-react";
import { Fragment } from "react";

import type { BotCommand } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { SortableHeader } from "../../components/SortableHeader";
import { StatusBadge, type StatusBadgeTone } from "../../components/StatusBadge";
import { formatTime } from "../../lib/time";

const STATUS_TONE: Record<string, StatusBadgeTone> = {
  pending: "info",
  running: "warning",
  succeeded: "success",
  failed: "error",
  cancelled: "info",
};

export function CommandHistoryTable({
  rows,
  compact,
  expandedId,
  sortKey,
  sortDirection,
  onExpand,
  onSort,
  onCancel,
  retry,
}: {
  rows: BotCommand[];
  compact: boolean;
  expandedId: string | null;
  sortKey: string;
  sortDirection: "asc" | "desc";
  onExpand: (id: string | null) => void;
  onSort: (key: string) => void;
  onCancel: (commandId: string) => void;
  retry: () => Promise<void>;
}) {
  if (rows.length === 0) {
    return (
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
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="table w-full">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
            {!compact ? <th className="w-8" /> : null}
            <SortableHeader
              label="Command"
              sortKey="command_type"
              currentSortKey={sortKey}
              direction={sortDirection}
              onSort={onSort}
            />
            <SortableHeader
              label="Status"
              sortKey="status"
              currentSortKey={sortKey}
              direction={sortDirection}
              onSort={onSort}
            />
            <SortableHeader
              label="Created"
              sortKey="created_at"
              currentSortKey={sortKey}
              direction={sortDirection}
              onSort={onSort}
            />
            {!compact ? (
              <>
                <th className="py-3 px-4 text-left">Payload</th>
                <th className="py-3 px-4 text-left">Actions</th>
              </>
            ) : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/40">
          {rows.map((row) => {
            const isExpanded = expandedId === row.id;
            return (
              <Fragment key={row.id}>
                <tr className="border-b border-zinc-800/30">
                  {!compact ? (
                    <td className="py-3 px-2">
                      <button
                        className="btn btn-ghost btn-xs btn-square"
                        onClick={() => onExpand(isExpanded ? null : row.id)}
                        type="button"
                        aria-label={`Toggle details for ${row.id}`}
                      >
                        {isExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </td>
                  ) : null}
                  <td className="py-3 px-4 text-sm font-semibold text-zinc-200">
                    {row.command_type}
                  </td>
                  <td className="py-3 px-4 text-xs">
                    <StatusBadge tone={STATUS_TONE[row.status] ?? "info"}>{row.status}</StatusBadge>
                  </td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                    {formatTime(row.created_at)}
                  </td>
                  {!compact ? (
                    <>
                      <td className="py-3 px-4 text-zinc-400 font-normal text-xs max-w-[280px] truncate">
                        {JSON.stringify(row.payload)}
                      </td>
                      <td className="py-3 px-4">
                        {row.status === "pending" ? (
                          <button
                            className="btn btn-ghost btn-xs text-error"
                            onClick={() => onCancel(row.id)}
                            type="button"
                            aria-label={`Cancel ${row.command_type}`}
                          >
                            <XCircle className="h-3.5 w-3.5" />
                            Cancel
                          </button>
                        ) : null}
                      </td>
                    </>
                  ) : null}
                </tr>
                {isExpanded && !compact ? (
                  <tr className="bg-zinc-900/50">
                    <td colSpan={6} className="px-8 py-3">
                      <div className="grid gap-2 text-xs">
                        <div className="flex gap-6">
                          <span className="text-zinc-500">ID:</span>
                          <span className="font-mono text-zinc-300">{row.id}</span>
                        </div>
                        {row.started_at ? (
                          <div className="flex gap-6">
                            <span className="text-zinc-500">Started:</span>
                            <span className="text-zinc-300">{formatTime(row.started_at)}</span>
                          </div>
                        ) : null}
                        {row.completed_at ? (
                          <div className="flex gap-6">
                            <span className="text-zinc-500">Completed:</span>
                            <span className="text-zinc-300">{formatTime(row.completed_at)}</span>
                          </div>
                        ) : null}
                        {row.result ? (
                          <div>
                            <span className="text-zinc-500">Result:</span>
                            <pre className="mt-1 max-h-40 overflow-auto rounded bg-zinc-800 p-2 text-zinc-300 font-mono text-xs">
                              {JSON.stringify(row.result, null, 2)}
                            </pre>
                          </div>
                        ) : null}
                        {row.error_message ? (
                          <div>
                            <span className="text-zinc-500">Error:</span>
                            <pre className="mt-1 max-h-40 overflow-auto rounded bg-red-950/40 border border-red-900/40 p-2 text-red-300 font-mono text-xs">
                              {row.error_message}
                            </pre>
                          </div>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
