import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bell,
  CheckCircle2,
  Database,
  Eye,
  Radio,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
} from "lucide-react";
import type { MouseEvent, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type { AlertDecision, BotCommand, CatalystReview, EventCluster, EventDetail } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { SectionError } from "../../components/SectionError";
import { EventDetailReadOnly } from "../events/EventDetailReadOnly";
import { classNames } from "../../lib/classNames";
import { scoreTone } from "../../lib/score";
import { formatTime } from "../../lib/time";
import type {
  DashboardState,
  QueueCommand,
  ResourceErrors,
  TrackCommand,
} from "../../types/dashboard";

type Segment = "global" | "us" | "vietnam" | "crypto";
type ActionItem =
  | { type: "alert"; id: string; alert: AlertDecision; event?: EventCluster }
  | { type: "investigation"; id: string; event: EventCluster }
  | { type: "catalyst"; id: string; catalyst: CatalystReview };
type SpotlightAnchor = Pick<DOMRect, "bottom" | "height" | "left" | "top" | "width">;
type SpotlightPopover = { event: EventCluster; anchor: SpotlightAnchor };

// Decisions that result in a delivered alert the user can acknowledge.
const ACKNOWLEDGEABLE_DECISIONS = new Set(["immediate_alert", "watchlist_batch"]);
const INVESTIGATION_ACTION_STATUSES = new Set(["pending", "running", "investigating", "failed"]);
const WATCHLIST_TIERS = new Set(["tier-1", "tier1", "1", "s", "a"]);
const SPOTLIGHT_EVENT_LIMIT = 5;
const SEGMENTS: Array<{ id: Segment; label: string }> = [
  { id: "global", label: "Global" },
  { id: "us", label: "U.S." },
  { id: "vietnam", label: "Vietnam" },
  { id: "crypto", label: "Crypto" },
];

function lowerValues(values: Array<string | null | undefined>) {
  return values.filter(Boolean).map((value) => value!.toLowerCase());
}

function needsAcknowledgement(alert: AlertDecision) {
  return ACKNOWLEDGEABLE_DECISIONS.has(alert.decision) && !alert.acknowledged_at;
}

function isInvestigationAction(event: EventCluster) {
  const status = event.latest_investigation?.status?.toLowerCase();
  return status ? INVESTIGATION_ACTION_STATUSES.has(status) : false;
}

function relativeAge(value?: string | null) {
  if (!value) return "No successful run";
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function freshnessTone(value?: string | null) {
  if (!value) return "bg-rose-400";
  const minutes = Math.max(0, (Date.now() - new Date(value).getTime()) / 60_000);
  if (minutes <= 30) return "bg-emerald-400";
  if (minutes <= 180) return "bg-amber-400";
  return "bg-rose-400";
}

function scoreTrend(detail?: EventDetail) {
  if (!detail || detail.score_history.length < 2) return null;
  const ordered = [...detail.score_history].sort(
    (left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime(),
  );
  const first = ordered[0].final_score;
  const latest = ordered[ordered.length - 1].final_score;
  const delta = latest - first;
  if (Math.abs(delta) < 1) return { label: "flat", className: "text-zinc-400", icon: ArrowRight };
  return delta > 0
    ? { label: `+${delta.toFixed(0)}`, className: "text-emerald-400", icon: ArrowUpRight }
    : { label: delta.toFixed(0), className: "text-rose-400", icon: ArrowDownRight };
}

function primaryMove(detail?: EventDetail) {
  return detail?.market_moves[0] ?? null;
}

function mergedEvent(event: EventCluster, detail?: EventDetail) {
  return detail ?? event;
}

function eventRecency(event: EventCluster) {
  const value = event.report_end_at ?? event.last_updated_at ?? event.report_start_at;
  return value ? new Date(value).getTime() : 0;
}

function sourceHealthCounts(state: DashboardState) {
  return state.sourceHealth.reduce(
    (counts, source) => {
      counts[source.health_status] += 1;
      return counts;
    },
    { healthy: 0, degraded: 0, failing: 0, disabled: 0 },
  );
}

function watchlistHits(state: DashboardState) {
  const events = state.events.map((event) => mergedEvent(event, state.eventDetails[event.id]));
  return state.watchlist
    .filter((entry) => entry.enabled && WATCHLIST_TIERS.has(entry.tier.toLowerCase()))
    .map((entry) => {
      const needles = new Set(
        lowerValues([entry.symbol, entry.name, ...entry.aliases]).filter((value) => value.length > 0),
      );
      const matches = events.filter((event) => {
        const haystack = lowerValues([
          ...event.affected_tickers,
          ...event.affected_entities,
          event.canonical_headline,
          event.summary,
        ]);
        return haystack.some((value) =>
          Array.from(needles).some((needle) => value === needle || value.includes(needle)),
        );
      }).sort((left, right) => {
        const recencyDelta = eventRecency(right) - eventRecency(left);
        return recencyDelta || right.final_score - left.final_score;
      });
      return { entry, matches };
    })
    .filter((item) => item.matches.length > 0);
}

function DigestNarrative({ content }: { content: string }) {
  // Content is topic-separated text: a lead paragraph, then blocks whose first
  // line is the topic heading and the rest is the body (blank lines between).
  const blocks = content.trim().split(/\n{2,}/);
  return (
    <div className="space-y-3 text-sm leading-6 text-zinc-300">
      {blocks.map((block, index) => {
        const [heading, ...rest] = block.split("\n");
        if (rest.length === 0) {
          return <p key={index}>{heading}</p>;
        }
        return (
          <div key={index}>
            <div className="font-semibold text-zinc-100">{heading}</div>
            <p className="mt-0.5 whitespace-pre-line">{rest.join("\n")}</p>
          </div>
        );
      })}
    </div>
  );
}

function OverviewPanel({
  title,
  icon: Icon,
  action,
  children,
}: {
  title: string;
  icon: typeof Activity;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-zinc-800/80 bg-zinc-900/60 shadow-lg shadow-black/10">
      <div className="flex items-center gap-2 border-b border-zinc-800/60 bg-zinc-900/40 px-5 py-4">
        <Icon className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-bold uppercase tracking-widest text-zinc-200">{title}</h2>
        {action ? <div className="ml-auto">{action}</div> : null}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function ActionQueue({
  items,
  acknowledgeAlert,
  openEvent,
  openMaintenance,
}: {
  items: ActionItem[];
  acknowledgeAlert: (id: string) => Promise<void>;
  openEvent: (id: string) => void;
  openMaintenance: () => void;
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="You're all caught up"
        body="No alerts, investigations, or unexplained moves need review right now."
      />
    );
  }

  return (
    <div className="space-y-3">
      {items.slice(0, 10).map((item) => {
        if (item.type === "alert") {
          const title = item.alert.event?.headline ?? item.event?.canonical_headline ?? item.alert.reason;
          return (
            <div
              className="rounded-lg border border-rose-500/20 bg-rose-500/5 p-3"
              key={item.id}
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
                    <Bell className="h-4 w-4 text-rose-300" />
                    {title}
                  </div>
                  <div className="mt-1 text-xs text-base-content/60">
                    {item.alert.decision.replace(/_/g, " ")} · score{" "}
                    {item.alert.event?.final_score ?? item.event?.final_score ?? "-"} ·{" "}
                    {formatTime(item.alert.sent_at ?? item.alert.created_at)}
                  </div>
                </div>
                <div className="flex gap-2">
                  {item.event ? (
                    <button
                      className="btn btn-xs btn-ghost"
                      onClick={() => openEvent(item.event!.id)}
                      type="button"
                    >
                      <Eye className="h-3.5 w-3.5" />
                      Event
                    </button>
                  ) : null}
                  <button
                    aria-label={`Acknowledge ${title}`}
                    className="btn btn-xs btn-outline btn-primary"
                    onClick={() => void acknowledgeAlert(item.alert.id)}
                    type="button"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Ack
                  </button>
                </div>
              </div>
            </div>
          );
        }
        if (item.type === "investigation") {
          return (
            <button
              className="w-full rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-left transition-colors hover:border-sky-400/40"
              key={item.id}
              onClick={() => openEvent(item.event.id)}
              type="button"
            >
              <div className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
                <Search className="h-4 w-4 text-sky-300" />
                {item.event.canonical_headline}
              </div>
              <div className="mt-1 text-xs text-base-content/60">
                investigation {item.event.latest_investigation?.status}
              </div>
            </button>
          );
        }
        return (
          <button
            className="w-full rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-left transition-colors hover:border-amber-400/40"
            key={item.id}
            onClick={openMaintenance}
            type="button"
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
              <AlertTriangle className="h-4 w-4 text-amber-300" />
              Unexplained {item.catalyst.asset_symbol} move
            </div>
            <div className="mt-1 text-xs text-base-content/60">
              {item.catalyst.price_change_pct >= 0 ? "+" : ""}
              {item.catalyst.price_change_pct.toFixed(2)}% · {item.catalyst.move_window} ·{" "}
              {item.catalyst.status}
            </div>
          </button>
        );
      })}
    </div>
  );
}

function EventCard({
  event,
  detail,
  openEvent,
}: {
  event: EventCluster;
  detail?: EventDetail;
  openEvent: (id: string) => void;
}) {
  const combined = mergedEvent(event, detail);
  const trend = scoreTrend(detail);
  const move = primaryMove(detail);
  const TrendIcon = trend?.icon;
  return (
    <button
      className="w-full rounded-lg border border-zinc-800 bg-zinc-950/30 p-4 text-left transition-colors hover:border-primary/40 hover:bg-zinc-900/70"
      data-testid={`event-card-${event.id}`}
      onClick={() => openEvent(event.id)}
      type="button"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={scoreTone(event.final_score)}>{event.final_score}</Badge>
        {event.alert_level ? <Badge tone="neutral">{event.alert_level.replace(/_/g, " ")}</Badge> : null}
        <span className="text-xs text-base-content/50">{event.source_count} sources</span>
        {trend && TrendIcon ? (
          <span className={classNames("inline-flex items-center gap-1 text-xs font-semibold", trend.className)}>
            <TrendIcon className="h-3.5 w-3.5" />
            {trend.label}
          </span>
        ) : null}
        {move ? (
          <span
            className={classNames(
              "rounded-md px-2 py-0.5 text-xs font-semibold",
              move.price_change_pct >= 0
                ? "bg-emerald-500/10 text-emerald-300"
                : "bg-rose-500/10 text-rose-300",
            )}
          >
            {move.asset_symbol} {move.price_change_pct >= 0 ? "+" : ""}
            {move.price_change_pct.toFixed(1)}%
          </span>
        ) : null}
      </div>
      <div className="mt-3 text-sm font-semibold text-zinc-100">{event.canonical_headline}</div>
      {combined.summary ? (
        <p className="mt-1 text-xs leading-5 text-base-content/60">{combined.summary}</p>
      ) : null}
      {combined.affected_tickers.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {combined.affected_tickers.slice(0, 5).map((ticker) => (
            <span
              className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-xs font-semibold text-zinc-300"
              key={ticker}
            >
              {ticker}
            </span>
          ))}
        </div>
      ) : null}
    </button>
  );
}

function spotlightPopoverStyle(anchor: SpotlightAnchor) {
  const margin = 16;
  const gap = 8;
  const preferredMaxHeight = 720;
  const width = Math.min(560, Math.max(320, window.innerWidth - 32));
  const left = Math.min(
    Math.max(margin, anchor.left),
    Math.max(margin, window.innerWidth - width - margin),
  );
  const spaceBelow = window.innerHeight - anchor.bottom - gap - margin;
  const spaceAbove = anchor.top - gap - margin;
  const opensAbove = spaceBelow < 360 && spaceAbove > spaceBelow;
  const availableHeight = Math.max(120, Math.min(preferredMaxHeight, opensAbove ? spaceAbove : spaceBelow));
  const top = opensAbove
    ? Math.max(margin, anchor.top - gap - availableHeight)
    : Math.min(anchor.bottom + gap, window.innerHeight - margin - availableHeight);
  return { left, maxHeight: availableHeight, top, width };
}

function WatchlistEventPopover({
  popover,
  detail,
}: {
  popover: SpotlightPopover;
  detail?: EventDetail;
}) {
  if (typeof document === "undefined") return null;
  const popoverId = `watchlist-event-popover-${popover.event.id}`;
  const style = spotlightPopoverStyle(popover.anchor);

  return createPortal(
    <div
      aria-label={`${popover.event.canonical_headline} details`}
      className="fixed z-50 overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-950 p-4 text-left shadow-2xl shadow-black/40"
      data-watchlist-event-popover={popover.event.id}
      id={popoverId}
      role="dialog"
      style={style}
    >
      <EventDetailReadOnly event={popover.event} eventDetail={detail} />
      {detail ? null : (
        <div className="mt-4 rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-xs text-base-content/60">
          Loading event details...
        </div>
      )}
    </div>,
    document.body,
  );
}

export function Overview({
  state,
  errors,
  retry,
  acknowledgeAlert,
  loadEventDetail,
  queue,
  trackCommand,
  trackedCommand,
  openEvent,
  openSources,
  openMaintenance,
}: {
  state: DashboardState;
  errors: ResourceErrors;
  retry: () => Promise<void>;
  acknowledgeAlert: (id: string) => Promise<void>;
  loadEventDetail: (id: string) => void;
  queue: QueueCommand;
  trackCommand: TrackCommand;
  trackedCommand: BotCommand | null;
  openEvent: (id: string) => void;
  openSources: () => void;
  openMaintenance: () => void;
}) {
  const [activeSegment, setActiveSegment] = useState<Segment>("global");
  const [spotlightPopover, setSpotlightPopover] = useState<SpotlightPopover | null>(null);
  const latestCompletedAt = state.status?.latest_job?.completed_at;
  const queueUnavailable = state.status?.command_queue_available === false;

  // Live status of an in-flight digest rebuild queued from this page.
  const digestStatus =
    trackedCommand?.command_type === "digest.send" ? trackedCommand.status : null;
  const digestRebuilding = digestStatus === "pending" || digestStatus === "running";

  async function rebuildDigest() {
    const command = await queue("digest.send", { hours: 24, dry_run: true }, { navigate: false });
    if (command) trackCommand(command);
  }

  const unacknowledgedAlerts = useMemo(
    () => state.alerts.filter(needsAcknowledgement),
    [state.alerts],
  );
  const actionItems = useMemo<ActionItem[]>(() => {
    const eventById = new Map(state.events.map((event) => [event.id, event]));
    return [
      ...unacknowledgedAlerts.map((alert) => ({
        type: "alert" as const,
        id: `alert:${alert.id}`,
        alert,
        event: eventById.get(alert.event_cluster_id),
      })),
      ...state.events.filter(isInvestigationAction).map((event) => ({
        type: "investigation" as const,
        id: `investigation:${event.id}`,
        event,
      })),
      ...state.catalystReviews
        .filter(
          (review) =>
            !review.detected_event_cluster_id &&
            ["pending", "investigating"].includes(review.status.toLowerCase()),
        )
        .map((catalyst) => ({ type: "catalyst" as const, id: `catalyst:${catalyst.id}`, catalyst })),
    ];
  }, [state.catalystReviews, state.events, unacknowledgedAlerts]);
  // Each segment is fetched server-side (top results for that market), so a quiet
  // segment surfaces its own clusters instead of being crowded out of the shared
  // recency window. Sort the returned set by score for a "top events" ordering.
  const selectedEvents = useMemo(
    () =>
      [...(state.overviewSegments[activeSegment]?.items ?? [])].sort(
        (left, right) => right.final_score - left.final_score,
      ),
    [activeSegment, state.overviewSegments],
  );

  // Load detail (score history + market moves) for the events actually shown, so the
  // trend arrows and move chips render for the active segment rather than only the
  // first few events globally.
  useEffect(() => {
    for (const event of selectedEvents) {
      if (!state.eventDetails[event.id]) {
        loadEventDetail(event.id);
      }
    }
  }, [loadEventDetail, selectedEvents, state.eventDetails]);

  const healthCounts = sourceHealthCounts(state);
  const degradedSources = healthCounts.degraded + healthCounts.failing;
  const spotlight = watchlistHits(state);
  const activeSpotlightDetail = spotlightPopover
    ? state.eventDetails[spotlightPopover.event.id]
    : undefined;

  function openSpotlightPopover(
    event: EventCluster,
    clickEvent: MouseEvent<HTMLButtonElement>,
  ) {
    const rect = clickEvent.currentTarget.getBoundingClientRect();
    setSpotlightPopover({
      event,
      anchor: {
        bottom: rect.bottom,
        height: rect.height,
        left: rect.left,
        top: rect.top,
        width: rect.width,
      },
    });
    if (!state.eventDetails[event.id]) {
      loadEventDetail(event.id);
    }
  }

  useEffect(() => {
    if (!spotlightPopover) return undefined;
    const activeEventId = spotlightPopover.event.id;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setSpotlightPopover(null);
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const insidePopover = Boolean(target.closest("[data-watchlist-event-popover]"));
      const insideTrigger = Boolean(
        target.closest(`[data-watchlist-event-trigger="${activeEventId}"]`),
      );
      if (!insidePopover && !insideTrigger) {
        setSpotlightPopover(null);
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [spotlightPopover]);

  if (errors.events || errors.alerts) {
    return (
      <SectionError
        title="Overview unavailable"
        message={errors.events ?? errors.alerts ?? "Overview resources failed to load"}
        retry={retry}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
        <OverviewPanel icon={ShieldCheck} title="Needs you now">
          <ActionQueue
            acknowledgeAlert={acknowledgeAlert}
            items={actionItems}
            openEvent={openEvent}
            openMaintenance={openMaintenance}
          />
        </OverviewPanel>

        <OverviewPanel
          icon={Sparkles}
          title="Daily synthesis"
          action={
            state.latestDigest ? (
              <div className="flex items-center gap-2">
                {digestStatus ? (
                  <span className="text-xs text-base-content/60">rebuild {digestStatus}</span>
                ) : null}
                <button
                  className="btn btn-xs btn-ghost gap-1"
                  disabled={queueUnavailable || digestRebuilding}
                  onClick={() => void rebuildDigest()}
                  type="button"
                >
                  <RefreshCcw
                    className={classNames("h-3.5 w-3.5", digestRebuilding && "animate-spin")}
                  />
                  {digestRebuilding ? "Rebuilding…" : "Rebuild"}
                </button>
              </div>
            ) : null
          }
        >
          {state.latestDigest ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-base-content/60">
                <Badge tone="info">{state.latestDigest.digest_type}</Badge>
                <span>
                  {state.latestDigest.event_count} event
                  {state.latestDigest.event_count === 1 ? "" : "s"}
                </span>
                <span className="text-zinc-600">·</span>
                <span>
                  {formatTime(state.latestDigest.window_start)} –{" "}
                  {formatTime(state.latestDigest.window_end)}
                </span>
                <span className="text-zinc-600">·</span>
                <span>built {relativeAge(state.latestDigest.created_at)}</span>
              </div>
              <DigestNarrative content={state.latestDigest.content} />
            </div>
          ) : (
            <EmptyState
              icon={Sparkles}
              title="No digest yet"
              body="The worker hasn't generated a market digest for the current window. It will appear here once the next daily digest runs — or build one now."
              action={
                <button
                  className="btn btn-sm btn-outline btn-primary"
                  disabled={queueUnavailable || digestRebuilding}
                  onClick={() => void rebuildDigest()}
                  type="button"
                >
                  <Sparkles
                    className={classNames("h-3.5 w-3.5", digestRebuilding && "animate-spin")}
                  />
                  {digestRebuilding ? "Building…" : "Build digest now"}
                </button>
              }
            />
          )}
        </OverviewPanel>
      </div>

      <OverviewPanel icon={Database} title="Top events">
        <div className="mb-4 flex flex-wrap gap-2">
          {SEGMENTS.map((segment) => (
            <button
              className={classNames(
                "btn btn-xs border-zinc-800",
                activeSegment === segment.id
                  ? "bg-primary/15 text-primary"
                  : "bg-zinc-950/40 text-zinc-400 hover:text-zinc-100",
              )}
              key={segment.id}
              onClick={() => setActiveSegment(segment.id)}
              type="button"
            >
              {segment.label}
            </button>
          ))}
        </div>
        {selectedEvents.length > 0 ? (
          <div className="grid gap-3 xl:grid-cols-2">
            {selectedEvents.slice(0, 10).map((event) => (
              <EventCard
                detail={state.eventDetails[event.id]}
                event={event}
                key={event.id}
                openEvent={openEvent}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Database}
            title={`No ${SEGMENTS.find((segment) => segment.id === activeSegment)?.label} events`}
            body="No event clusters currently match this market segment."
          />
        )}
      </OverviewPanel>

      <OverviewPanel icon={Star} title="Watchlist spotlight">
        {spotlight.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {spotlight.map(({ entry, matches }) => (
              <div
                className="rounded-lg border border-zinc-800 bg-zinc-950/30 p-4"
                key={entry.id}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-baseline gap-2">
                    <div className="text-sm font-semibold text-zinc-100">{entry.name}</div>
                    <div className="text-xs text-base-content/60">
                      {entry.symbol ?? entry.entity_type}
                    </div>
                  </div>
                  <Badge tone="info">{matches.length} hit{matches.length === 1 ? "" : "s"}</Badge>
                </div>
                <div className="mt-3 space-y-2">
                  {matches.slice(0, SPOTLIGHT_EVENT_LIMIT).map((event) => (
                    <button
                      aria-controls={
                        spotlightPopover?.event.id === event.id
                          ? `watchlist-event-popover-${event.id}`
                          : undefined
                      }
                      aria-expanded={spotlightPopover?.event.id === event.id}
                      className={classNames(
                        "w-full rounded-md border bg-zinc-950/40 px-3 py-2 text-left text-xs font-semibold leading-5 text-primary transition-colors hover:border-primary/40 hover:bg-zinc-900/70",
                        spotlightPopover?.event.id === event.id
                          ? "border-primary/60 bg-primary/5"
                          : "border-zinc-800/70",
                      )}
                      data-watchlist-event-trigger={event.id}
                      key={event.id}
                      onClick={(clickEvent) => openSpotlightPopover(event, clickEvent)}
                      type="button"
                    >
                      {event.canonical_headline}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Star}
            title="No tier-1 watchlist hits"
            body="Your highest-priority watchlist entities are quiet in the current event set."
          />
        )}
      </OverviewPanel>

      {spotlightPopover ? (
        <WatchlistEventPopover
          detail={activeSpotlightDetail}
          popover={spotlightPopover}
        />
      ) : null}

      <div className="rounded-lg border border-zinc-800/80 bg-zinc-900/60 px-4 py-3 text-sm text-base-content/70">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <Radio className="h-4 w-4 text-primary" />
            <span>
              Coverage: {healthCounts.healthy} healthy · {healthCounts.degraded} degraded ·{" "}
              {healthCounts.failing} failing
            </span>
            <span className="text-zinc-600">·</span>
            <span>Latest pipeline {state.status?.latest_job?.status ?? "unknown"}</span>
            <span className={classNames("h-2.5 w-2.5 rounded-full", freshnessTone(latestCompletedAt))} />
            <span>{relativeAge(latestCompletedAt)}</span>
          </div>
          {degradedSources > 0 ? (
            <button className="btn btn-xs btn-outline btn-warning" onClick={openSources} type="button">
              Review sources
            </button>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-300">
              <CheckCircle2 className="h-3.5 w-3.5" />
              source coverage stable
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
