import { Bell, RefreshCcw } from "lucide-react";

import type { AlertDecision } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { ResponsiveDataList } from "../../components/ResponsiveDataList";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { StatusBadge, type StatusBadgeTone } from "../../components/StatusBadge";
import { useSortableData } from "../../hooks/useSortableData";
import { classNames } from "../../lib/classNames";
import { formatTime } from "../../lib/time";

function alertDecisionTone(decision: string): StatusBadgeTone {
  return decision === "immediate_alert" ? "error" : "neutral";
}

function alertDecisionLabel(decision: string) {
  return decision.replace(/_/g, " ");
}

export function AlertsTable({
  rows,
  compact = false,
  error,
  retry,
  acknowledge,
  dismiss,
  selectedAlertId,
  onSelectAlert,
}: {
  rows: AlertDecision[];
  compact?: boolean;
  error?: string;
  retry: () => Promise<void>;
  acknowledge?: (id: string) => Promise<void>;
  dismiss?: (id: string) => Promise<void>;
  selectedAlertId?: string | null;
  onSelectAlert?: (id: string) => void;
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
    <ResponsiveDataList
      cards={sortedRows.map((row) => (
        <div
          aria-label={onSelectAlert ? `Select alert ${row.id}` : undefined}
          className={classNames(
            "rounded-md border bg-zinc-950/30 p-3 transition-colors",
            onSelectAlert && "cursor-pointer hover:border-primary/40",
            selectedAlertId === row.id ? "border-primary/60 bg-primary/5" : "border-zinc-800",
          )}
          data-testid={`alert-card-${row.id}`}
          key={row.id}
          onClick={() => onSelectAlert?.(row.id)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onSelectAlert?.(row.id);
            }
          }}
          role={onSelectAlert ? "button" : undefined}
          tabIndex={onSelectAlert ? 0 : undefined}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <StatusBadge tone={alertDecisionTone(row.decision)}>
              {alertDecisionLabel(row.decision)}
            </StatusBadge>
            <span className="text-xs text-zinc-500">
              {formatTime(row.sent_at ?? row.created_at)}
            </span>
          </div>
          <div className="mt-2 text-sm font-semibold text-zinc-100">
            {row.event?.headline ?? row.reason}
          </div>
          {!compact ? (
            <div className="mt-2 text-xs text-base-content/60">
              {row.channel ?? "-"} ·{" "}
              {row.suppression_reason === "dismissed"
                ? "dismissed"
                : row.acknowledged_at
                  ? "acknowledged"
                  : "unacknowledged"}
            </div>
          ) : null}
        </div>
      ))}
      table={
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
            {!compact ? <th className="px-4 py-3 text-left">State</th> : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/40">
          {sortedRows.map((row) => (
            <tr
              key={row.id}
              className={classNames(
                "border-b border-zinc-800/30 transition-colors",
                onSelectAlert && "cursor-pointer hover:bg-zinc-800/20",
                selectedAlertId === row.id && "bg-primary/5 outline outline-1 outline-primary/30",
              )}
              data-testid={`alert-row-${row.id}`}
              onClick={() => onSelectAlert?.(row.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectAlert?.(row.id);
                }
              }}
              tabIndex={onSelectAlert ? 0 : undefined}
            >
              <td className="py-3 px-4">
                <StatusBadge tone={alertDecisionTone(row.decision)}>
                  {alertDecisionLabel(row.decision)}
                </StatusBadge>
              </td>
              <td className="py-3 px-4 max-w-[700px] whitespace-normal text-sm font-semibold text-zinc-200">
                {row.event?.headline ?? row.reason}
              </td>
              {!compact ? (
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                  {row.channel ?? "-"}
                </td>
              ) : null}
              <td className="py-3 px-4 text-zinc-500 font-normal text-xs whitespace-nowrap">
                {formatTime(row.sent_at ?? row.created_at)}
              </td>
              {!compact ? (
                <td className="py-3 px-4">
                  <div className="flex items-center gap-2 whitespace-nowrap">
                    <span className="text-xs text-zinc-500">
                      {row.suppression_reason === "dismissed"
                        ? "dismissed"
                        : row.acknowledged_at
                        ? "acknowledged"
                        : "unacknowledged"}
                    </span>
                    {!row.acknowledged_at && row.suppression_reason !== "dismissed" && acknowledge ? (
                      <button
                        className="btn btn-xs btn-outline btn-primary"
                        onClick={(event) => {
                          event.stopPropagation();
                          void acknowledge(row.id);
                        }}
                        type="button"
                      >
                        Acknowledge
                      </button>
                    ) : null}
                    {!row.acknowledged_at && row.suppression_reason !== "dismissed" && dismiss ? (
                      <button
                        className="btn btn-xs btn-outline btn-primary"
                        onClick={(event) => {
                          event.stopPropagation();
                          void dismiss(row.id);
                        }}
                        type="button"
                      >
                        Dismiss
                      </button>
                    ) : null}
                  </div>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      }
    />
  );
}
