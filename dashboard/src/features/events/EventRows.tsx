import { Database, RefreshCcw } from "lucide-react";

import type { EventCluster } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { ResponsiveDataList } from "../../components/ResponsiveDataList";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";
import { classNames } from "../../lib/classNames";
import { scoreTone } from "../../lib/score";
import { formatTime, formatTimeRange } from "../../lib/time";

export function EventRows({
  events,
  onSelect,
  selectedEventId,
  error,
  retry,
}: {
  events: EventCluster[];
  onSelect?: (id: string) => void;
  selectedEventId?: string;
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedEvents, requestSort, sortConfig } = useSortableData(events, {
    key: "report_end_at",
    direction: "desc",
  });

  if (error) {
    return <SectionError title="Event clusters unavailable" message={error} retry={retry} />;
  }

  if (sortedEvents.length === 0) {
    return (
      <EmptyState
        icon={Database}
        title="No priority events yet"
        body="No event clusters match the current data set or search filter."
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
      cards={sortedEvents.map((event) => (
        <button
          className={classNames(
            "rounded-md border p-3 text-left transition-colors",
            onSelect && "cursor-pointer hover:border-primary/40",
            selectedEventId === event.id ? "border-primary/60 bg-primary/5" : "border-zinc-800 bg-zinc-950/30",
          )}
          data-testid={`event-card-${event.id}`}
          key={event.id}
          onClick={() => onSelect?.(event.id)}
          type="button"
        >
          <div className="flex items-center justify-between gap-2">
            <Badge tone={scoreTone(event.final_score)}>{event.final_score}</Badge>
            <span className="text-xs text-zinc-500">{formatTime(event.last_updated_at)}</span>
          </div>
          <div className="mt-2 text-sm font-semibold text-zinc-100">
            {event.canonical_headline}
          </div>
          <div className="mt-2 text-xs text-base-content/60">
            {event.status !== "reported" ? `${event.status} · ` : ""}
            {event.source_count} sources
          </div>
          <div className="mt-1 text-xs text-base-content/50">
            Reports {formatTimeRange(event.report_start_at, event.report_end_at)}
          </div>
        </button>
      ))}
      table={
      <table className="table w-full">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
            <SortableHeader
              label="Score"
              sortKey="final_score"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
              className="w-1 whitespace-nowrap"
            />
            <SortableHeader
              label="Headline"
              sortKey="canonical_headline"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Sources"
              sortKey="source_count"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
              className="w-20 whitespace-nowrap"
            />
            <SortableHeader
              label="Report range"
              sortKey="report_end_at"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
              className="w-48 whitespace-nowrap"
            />
            <SortableHeader
              label="Updated"
              sortKey="last_updated_at"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
              className="w-40 whitespace-nowrap"
            />
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/40">
          {sortedEvents.map((event) => (
            <tr
              key={event.id}
              className={classNames(
                "group border-b border-zinc-800/30 transition-colors duration-150",
                onSelect && "cursor-pointer hover:bg-zinc-800/20",
                selectedEventId === event.id && "bg-primary/5 outline outline-1 outline-primary/30",
              )}
              data-testid={`event-row-${event.id}`}
              onClick={() => onSelect?.(event.id)}
            >
              <td className="py-3 px-4 w-1 whitespace-nowrap">
                <Badge tone={scoreTone(event.final_score)}>{event.final_score}</Badge>
              </td>
              <td className="py-3 px-4 max-w-[520px] whitespace-normal text-sm font-semibold text-zinc-200 group-hover:text-primary transition-colors duration-150">
                {event.canonical_headline}
              </td>
              <td className="py-3 px-4 text-zinc-400 font-normal text-xs w-20 whitespace-nowrap">
                {event.source_count}
              </td>
              <td className="py-3 px-4 text-zinc-500 font-normal text-xs w-48 whitespace-nowrap">
                {formatTimeRange(event.report_start_at, event.report_end_at)}
              </td>
              <td className="py-3 px-4 text-zinc-500 font-normal text-xs w-40 whitespace-nowrap">
                {formatTime(event.last_updated_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      }
    />
  );
}
