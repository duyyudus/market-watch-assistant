import { Database, RefreshCcw } from "lucide-react";

import type { EventCluster } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";
import { classNames } from "../../lib/classNames";
import { scoreTone } from "../../lib/score";
import { formatTime } from "../../lib/time";

export function EventRows({
  events,
  onSelect,
  error,
  retry,
}: {
  events: EventCluster[];
  onSelect?: (id: string) => void;
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedEvents, requestSort, sortConfig } = useSortableData(events, {
    key: "last_updated_at",
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
    <>
      <div className="grid gap-3 lg:hidden">
        {sortedEvents.map((event) => (
          <button
            className="rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-left"
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
              {event.status} · {event.source_count} sources
            </div>
          </button>
        ))}
      </div>
      <div className="hidden overflow-x-auto lg:block">
      <table className="table w-full">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
            <SortableHeader
              label="Score"
              sortKey="final_score"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Headline"
              sortKey="canonical_headline"
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
              label="Sources"
              sortKey="source_count"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Updated"
              sortKey="last_updated_at"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
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
              )}
              onClick={() => onSelect?.(event.id)}
            >
              <td className="py-3 px-4">
                <Badge tone={scoreTone(event.final_score)}>{event.final_score}</Badge>
              </td>
              <td className="py-3 px-4 max-w-[520px] whitespace-normal text-sm font-semibold text-zinc-200 group-hover:text-primary transition-colors duration-150">
                {event.canonical_headline}
              </td>
              <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{event.status}</td>
              <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                {event.source_count}
              </td>
              <td className="py-3 px-4 text-zinc-500 font-normal text-xs">
                {formatTime(event.last_updated_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </>
  );
}
