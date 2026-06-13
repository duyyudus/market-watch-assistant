import { Database, Search } from "lucide-react";

import type { EventCluster, EventDetail } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { scoreTone } from "../../lib/score";
import { formatTime } from "../../lib/time";
import type { QueueCommand } from "../../types/dashboard";
import { Detail } from "./Detail";
import { EventRows } from "./EventRows";

export function Events(props: {
  events: EventCluster[];
  error?: string;
  query: string;
  selectedEvent?: EventCluster;
  selectedEventDetail?: EventDetail;
  setQuery: (value: string) => void;
  setSelectedEventId: (value: string) => void;
  queue: QueueCommand;
  retry: () => Promise<void>;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
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
            <EventRows
              events={props.events}
              onSelect={props.setSelectedEventId}
              selectedEventId={props.selectedEvent?.id}
              retry={props.retry}
            />
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
              <Detail label="Event ID" value={props.selectedEvent.id} />
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
            <ScorePanel event={props.selectedEventDetail ?? props.selectedEvent} />
            {props.selectedEventDetail ? (
              <div className="space-y-4">
                <section>
                  <h3 className="mb-2 text-sm font-bold text-zinc-100">Timeline</h3>
                  <div className="space-y-2">
                    {props.selectedEventDetail.timeline.map((item) => (
                      <a
                        className="block rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-sm hover:border-primary/40"
                        href={item.url}
                        key={item.news_item_id}
                        rel="noopener noreferrer"
                        target="_blank"
                      >
                        <div className="font-semibold text-zinc-100">{item.title}</div>
                        <div className="mt-1 text-xs text-base-content/60">
                          {item.source_name} · {item.relation_type} · {item.similarity_score ?? "-"}
                        </div>
                      </a>
                    ))}
                  </div>
                </section>
                <section>
                  <h3 className="mb-2 text-sm font-bold text-zinc-100">LLM analysis</h3>
                  {props.selectedEventDetail.llm_runs.length ? (
                    props.selectedEventDetail.llm_runs.map((run) => (
                      <div
                        className="rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-sm"
                        key={run.id}
                      >
                        <div className="text-xs text-base-content/60">
                          {run.provider} · {run.model} · {run.status}
                        </div>
                        <div className="mt-1 text-zinc-200">
                          {String(run.result?.summary ?? run.result?.rationale ?? "No summary")}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="text-sm text-base-content/60">No LLM analysis yet.</div>
                  )}
                </section>
                <section>
                  <h3 className="mb-2 text-sm font-bold text-zinc-100">Investigation</h3>
                  <div className="rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-sm">
                    {props.selectedEventDetail.latest_investigation ? (
                      <>
                        <div className="font-semibold text-zinc-100">
                          {props.selectedEventDetail.latest_investigation.status}
                        </div>
                        <div className="mt-1 text-base-content/70">
                          {String(
                            props.selectedEventDetail.latest_investigation.result?.suggested_action ??
                              props.selectedEventDetail.latest_investigation.result?.summary ??
                              "No result summary",
                          )}
                        </div>
                      </>
                    ) : (
                      "No investigation yet."
                    )}
                  </div>
                </section>
                <section>
                  <h3 className="mb-2 text-sm font-bold text-zinc-100">
                    Latest price move snapshots
                  </h3>
                  {props.selectedEventDetail.market_moves.length ? (
                    <div className="grid gap-2 sm:grid-cols-2">
                      {props.selectedEventDetail.market_moves.map((move) => (
                        <div
                          className="rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-sm"
                          key={move.id}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="font-bold text-zinc-100">{move.asset_symbol}</div>
                            {move.exchange ? (
                              <div className="text-xs font-semibold text-base-content/50">
                                {move.exchange}
                              </div>
                            ) : null}
                          </div>
                          <div className="text-base-content/70">
                            {move.window}: {move.price_change_pct.toFixed(1)}%
                          </div>
                          <div className="mt-1 text-xs text-base-content/50">
                            Captured {formatTime(move.timestamp)}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-base-content/50 italic">
                      No latest price move snapshots detected for this event.
                    </div>
                  )}
                </section>
              </div>
            ) : null}
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

function ScorePanel({
  event,
}: {
  event: EventCluster &
    Partial<
      Pick<
        EventDetail,
        | "top_source_score"
        | "confirmation_score"
        | "novelty_score"
        | "urgency_score"
        | "market_impact_score"
        | "relevance_score"
        | "score_history"
      >
    >;
}) {
  const components = [
    ["Source", event.top_source_score],
    ["Impact", event.market_impact_score],
    ["Relevance", event.relevance_score],
    ["Novelty", event.novelty_score],
    ["Urgency", event.urgency_score],
    ["Confirmation", event.confirmation_score],
  ].filter((item): item is [string, number] => typeof item[1] === "number");
  const latest = event.score_history?.[0]?.score_breakdown;
  const penalties = latest
    ? [
        ["Duplicate", latest.duplicate_penalty],
        ["Noise", latest.noise_penalty],
        ["Stale", latest.stale_penalty],
      ].filter((item): item is [string, number] => Number(item[1]) > 0)
    : [];

  return (
    <section>
      <h3 className="mb-2 text-sm font-bold text-zinc-100">Scoring</h3>
      <div className="space-y-2">
        {components.map(([label, value]) => (
          <div key={label}>
            <div className="mb-1 flex justify-between text-xs">
              <span>{label}</span>
              <span>{value}</span>
            </div>
            <div className="h-2 rounded bg-zinc-800">
              <div className="h-2 rounded bg-primary" style={{ width: `${Math.min(value, 100)}%` }} />
            </div>
          </div>
        ))}
        {penalties.length ? (
          <div className="flex flex-wrap gap-2 pt-1">
            {penalties.map(([label, value]) => (
              <Badge key={label} tone="warning">
                {label} -{value}
              </Badge>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
