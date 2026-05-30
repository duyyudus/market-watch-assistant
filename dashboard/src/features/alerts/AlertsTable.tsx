import { Bell, RefreshCcw } from "lucide-react";

import type { AlertDecision } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";
import { classNames } from "../../lib/classNames";
import { formatTime } from "../../lib/time";

export function AlertsTable({
  rows,
  compact = false,
  error,
  retry,
}: {
  rows: AlertDecision[];
  compact?: boolean;
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "sent",
    direction: "desc",
  });

  if (error) {
    return <SectionError title="Alert decisions unavailable" message={error} retry={retry} />;
  }

  if (sortedRows.length === 0) {
    return (
      <EmptyState
        icon={Bell}
        title="No alert decisions yet"
        body="Alert decisions will appear after scored events cross alert or digest thresholds."
        action={
          <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
            <RefreshCcw className="h-4 w-4" />
            Refresh
          </button>
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="table w-full">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
            <SortableHeader
              label="Decision"
              sortKey="decision"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Event"
              sortKey="event_headline"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            {!compact ? (
              <SortableHeader
                label="Channel"
                sortKey="channel"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
            ) : null}
            <SortableHeader
              label="Sent"
              sortKey="sent"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/40">
          {sortedRows.map((row) => (
            <tr key={row.id} className="border-b border-zinc-800/30">
              <td className="py-3 px-4">
                <span
                  className={classNames(
                    "px-2 py-0.5 rounded text-xs font-bold uppercase whitespace-nowrap",
                    row.decision === "immediate_alert"
                      ? "bg-red-500/10 text-red-400 border border-red-500/20"
                      : "bg-zinc-800 text-zinc-400",
                  )}
                >
                  {row.decision.replace("_", " ")}
                </span>
              </td>
              <td className="py-3 px-4 max-w-[460px] whitespace-normal text-sm font-semibold text-zinc-200">
                {row.event?.headline ?? row.reason}
              </td>
              {!compact ? (
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                  {row.channel ?? "-"}
                </td>
              ) : null}
              <td className="py-3 px-4 text-zinc-500 font-normal text-xs">
                {formatTime(row.sent_at ?? row.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

