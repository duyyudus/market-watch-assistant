import type { EventCluster, EventDetail } from "../../api";
import { Badge } from "../../components/Badge";
import { scoreTone } from "../../lib/score";
import { formatTime } from "../../lib/time";
import { Detail } from "./Detail";

export function EventDetailReadOnly({
  event,
  eventDetail,
}: {
  event: EventCluster;
  eventDetail?: EventDetail;
}) {
  return (
    <div className="space-y-4">
      <div>
        <Badge tone={scoreTone(event.final_score)}>{event.final_score}</Badge>
        <h2 className="mt-2 text-xl font-bold text-zinc-100">{event.canonical_headline}</h2>
        <p className="mt-1 text-sm text-base-content/70">{event.summary ?? "No summary yet."}</p>
      </div>
      <div className="grid gap-2 text-sm">
        <Detail label="Event ID" value={event.id} />
        <Detail label="Status" value={event.status} />
        <Detail label="Regions" value={event.regions.join(", ") || "-"} />
        <Detail label="Assets" value={event.asset_classes.join(", ") || "-"} />
        <Detail label="Entities" value={event.affected_entities.join(", ") || "-"} />
        <Detail label="Tickers" value={event.affected_tickers.join(", ") || "-"} />
        <Detail label="Sources" value={event.source_count} />
      </div>
      <ScorePanel event={eventDetail ?? event} />
      {eventDetail ? <EventDetailSections eventDetail={eventDetail} /> : null}
    </div>
  );
}

function EventDetailSections({ eventDetail }: { eventDetail: EventDetail }) {
  return (
    <div className="space-y-4">
      <section>
        <h3 className="mb-2 text-sm font-bold text-zinc-100">Timeline</h3>
        <div className="space-y-2">
          {eventDetail.timeline.map((item) => (
            <a
              className="block rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-sm hover:border-primary/40"
              href={item.url}
              key={item.news_item_id}
              rel="noopener noreferrer"
              target="_blank"
            >
              <div className="font-semibold text-zinc-100">{item.title}</div>
              <div className="mt-1 text-xs text-base-content/60">
                {item.source_name} / {item.relation_type} / {item.similarity_score ?? "-"}
              </div>
            </a>
          ))}
        </div>
      </section>
      <section>
        <h3 className="mb-2 text-sm font-bold text-zinc-100">LLM analysis</h3>
        {eventDetail.llm_runs.length ? (
          eventDetail.llm_runs.map((run) => (
            <div
              className="rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-sm"
              key={run.id}
            >
              <div className="text-xs text-base-content/60">
                {run.provider} / {run.model} / {run.status}
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
          {eventDetail.latest_investigation ? (
            <>
              <div className="font-semibold text-zinc-100">
                {eventDetail.latest_investigation.status}
              </div>
              <div className="mt-1 text-base-content/70">
                {String(
                  eventDetail.latest_investigation.result?.suggested_action ??
                    eventDetail.latest_investigation.result?.summary ??
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
        <h3 className="mb-2 text-sm font-bold text-zinc-100">Latest price move snapshots</h3>
        {eventDetail.market_moves.length ? (
          <div className="grid gap-2 sm:grid-cols-2">
            {eventDetail.market_moves.map((move) => (
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
