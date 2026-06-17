import { ChevronLeft, ChevronRight, Database, RefreshCcw, Search } from "lucide-react";

import type { EventCluster, EventDetail } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import type { QueueCommand } from "../../types/dashboard";
import { EventDetailReadOnly } from "./EventDetailReadOnly";
import { EventRows } from "./EventRows";

export function Events(props: {
  events: EventCluster[];
  error?: string;
  query: string;
  maxItems: number | null;
  minScore: number;
  offset: number;
  pageSize: number;
  total: number;
  selectedEvent?: EventCluster;
  selectedEventDetail?: EventDetail;
  setQuery: (value: string) => void;
  setMaxItems: (value: number | null) => void;
  setMinScore: (value: number) => void;
  setOffset: (value: number) => void;
  setSelectedEventId: (value: string) => void;
  queue: QueueCommand;
  retry: () => Promise<void>;
}) {
  const pageStart = props.total > 0 ? Math.min(props.offset + 1, props.total) : 0;
  const pageEnd = Math.min(props.offset + props.pageSize, props.total);
  const canGoPrevious = props.offset > 0;
  const canGoNext = props.offset + props.pageSize < props.total;

  return (
    <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
      <Panel title="Event clusters">
        {props.error ? (
          <SectionError title="Event clusters unavailable" message={props.error} retry={props.retry} />
        ) : (
          <>
            <div className="mb-4 grid gap-3 lg:grid-cols-[minmax(220px,1fr)_150px_150px_auto] lg:items-end">
              <label className="form-control w-full">
                <span className="label pb-1">
                  <span className="label-text text-xs font-semibold text-zinc-400">Search</span>
                </span>
                <span className="input input-sm input-bordered flex items-center gap-2">
                  <Search className="h-4 w-4" />
                  <input
                    value={props.query}
                    onChange={(event) => props.setQuery(event.target.value)}
                    placeholder="Search events, tickers, entities"
                  />
                </span>
              </label>
              <label className="form-control w-full">
                <span className="label pb-1">
                  <span className="label-text text-xs font-semibold text-zinc-400">Max items</span>
                </span>
                <select
                  aria-label="Max items"
                  className="select select-bordered select-sm w-full bg-zinc-950"
                  onChange={(event) =>
                    props.setMaxItems(event.target.value === "all" ? null : Number(event.target.value))
                  }
                  value={props.maxItems ?? "all"}
                >
                  {[100, 250, 500, 1000].map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                  <option value="all">All</option>
                </select>
              </label>
              <label className="form-control w-full">
                <span className="label pb-1">
                  <span className="label-text text-xs font-semibold text-zinc-400">
                    Minimum score
                  </span>
                </span>
                <input
                  aria-label="Minimum score"
                  className="input input-bordered input-sm w-full bg-zinc-950"
                  max={100}
                  min={0}
                  onChange={(event) => props.setMinScore(Number(event.target.value) || 0)}
                  type="number"
                  value={props.minScore}
                />
              </label>
              <button
                className="btn btn-sm btn-outline"
                onClick={() => void props.retry()}
                type="button"
              >
                <RefreshCcw className="h-4 w-4" />
                Refresh
              </button>
            </div>
            <EventRows
              events={props.events}
              onSelect={props.setSelectedEventId}
              selectedEventId={props.selectedEvent?.id}
              retry={props.retry}
            />
            <div className="mt-4 flex flex-col gap-2 border-t border-zinc-800/60 pt-3 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between">
              <span>
                {pageStart}-{pageEnd} of {props.total}
              </span>
              <div className="join">
                <button
                  aria-label="Previous event page"
                  className="btn join-item btn-sm btn-outline"
                  disabled={!canGoPrevious}
                  onClick={() => props.setOffset(Math.max(0, props.offset - props.pageSize))}
                  type="button"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  aria-label="Next event page"
                  className="btn join-item btn-sm btn-outline"
                  disabled={!canGoNext}
                  onClick={() => props.setOffset(props.offset + props.pageSize)}
                  type="button"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </Panel>
      <div className="xl:sticky xl:top-20 xl:self-start xl:max-h-[calc(100vh-100px)] xl:overflow-y-auto xl:overflow-x-hidden">
        <Panel title="Event detail">
        {props.error ? (
          <EmptyState
            icon={Database}
            title="No event selected"
            body="Event details will appear after event clusters load."
          />
        ) : props.selectedEvent ? (
          <div className="space-y-4">
            <EventDetailReadOnly
              event={props.selectedEvent}
              eventDetail={props.selectedEventDetail}
            />
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                className="btn btn-sm btn-outline btn-primary"
                onClick={() => props.queue("event.rescore", { event_id: props.selectedEvent!.id })}
                type="button"
              >
                Rescore
              </button>
              <button
                className="btn btn-sm btn-outline btn-primary"
                onClick={() =>
                  props.queue("investigation.run_event", { event_id: props.selectedEvent!.id })
                }
                type="button"
              >
                Investigate
              </button>
              <button
                className="btn btn-sm btn-outline btn-primary"
                onClick={() =>
                  props.queue("event.mark", {
                    event_id: props.selectedEvent!.id,
                    status: "confirmed",
                  })
                }
                type="button"
              >
                Confirm
              </button>
            </div>
          </div>
        ) : (
          <EmptyState
            icon={Database}
            title="No event details yet"
            body="Run the pipeline or wait for clustered news before event details appear here."
          />
        )}
        </Panel>
      </div>
    </div>
  );
}
