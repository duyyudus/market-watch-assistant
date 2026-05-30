import { Database, Search } from "lucide-react";

import type { EventCluster } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { scoreTone } from "../../lib/score";
import type { QueueCommand } from "../../types/dashboard";
import { Detail } from "./Detail";
import { EventRows } from "./EventRows";

export function Events(props: {
  events: EventCluster[];
  error?: string;
  query: string;
  selectedEvent?: EventCluster;
  setQuery: (value: string) => void;
  setSelectedEventId: (value: string) => void;
  queue: QueueCommand;
  retry: () => Promise<void>;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[1.45fr_1fr]">
      <Panel title="Event clusters">
        {props.error ? (
          <SectionError title="Event clusters unavailable" message={props.error} retry={props.retry} />
        ) : (
          <>
            <label className="input input-sm input-bordered mb-3 flex items-center gap-2">
              <Search className="h-4 w-4" />
              <input
                value={props.query}
                onChange={(event) => props.setQuery(event.target.value)}
                placeholder="Search events, tickers, entities"
              />
            </label>
            <EventRows events={props.events} onSelect={props.setSelectedEventId} retry={props.retry} />
          </>
        )}
      </Panel>
      <Panel title="Event detail">
        {props.error ? (
          <EmptyState
            icon={Database}
            title="No event selected"
            body="Event details will appear after event clusters load."
          />
        ) : props.selectedEvent ? (
          <div className="space-y-4">
            <div>
              <Badge tone={scoreTone(props.selectedEvent.final_score)}>
                {props.selectedEvent.final_score}
              </Badge>
              <h2 className="mt-2 text-xl font-bold text-zinc-100">
                {props.selectedEvent.canonical_headline}
              </h2>
              <p className="mt-1 text-sm text-base-content/70">
                {props.selectedEvent.summary ?? "No summary yet."}
              </p>
            </div>
            <div className="grid gap-2 text-sm">
              <Detail label="Status" value={props.selectedEvent.status} />
              <Detail label="Regions" value={props.selectedEvent.regions.join(", ") || "-"} />
              <Detail label="Assets" value={props.selectedEvent.asset_classes.join(", ") || "-"} />
              <Detail
                label="Entities"
                value={props.selectedEvent.affected_entities.join(", ") || "-"}
              />
              <Detail
                label="Tickers"
                value={props.selectedEvent.affected_tickers.join(", ") || "-"}
              />
              <Detail label="Sources" value={props.selectedEvent.source_count} />
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                className="btn btn-sm btn-outline"
                onClick={() => props.queue("event.rescore", { event_id: props.selectedEvent!.id })}
                type="button"
              >
                Rescore
              </button>
              <button
                className="btn btn-sm btn-outline"
                onClick={() =>
                  props.queue("investigation.run_event", { event_id: props.selectedEvent!.id })
                }
                type="button"
              >
                Investigate
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
  );
}

