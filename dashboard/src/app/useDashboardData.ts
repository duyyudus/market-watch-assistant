import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AlertChannel,
  AlertDecision,
  AlertPolicy,
  AlertSuppressionRule,
  BotCommand,
  BotStatus,
  CatalystReview,
  ConfigurationPresets,
  Digest,
  EventCluster,
  EventDetail,
  JobRun,
  NewsDetail,
  NewsFilterOptions,
  NewsItem,
  Source,
  SourceHealth,
  WatchlistEntry,
} from "../api";
import { api, eventStreamUrl, normalizeListResponse } from "../api";
import { createResourceCache } from "../lib/apiCache";
import { settle } from "../lib/errors";
import type { DashboardState, ResourceErrors, ResourceKey, View } from "../types/dashboard";
import { emptyErrors, emptyState } from "./state";

type ListResourceKey = Exclude<ResourceKey, "alertDetail" | "eventDetail" | "newsDetail">;
export type AlertSubTab = "decisions" | "settings";
const EVENT_PAGE_SIZE = 100;
const ALERT_PAGE_SIZE = 100;
const OVERVIEW_SEGMENTS = ["global", "us", "vietnam", "crypto"] as const;
const OVERVIEW_SEGMENT_SIZE = 10;

function messageFromError(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function useDashboardData() {
  const [view, setView] = useState<View>("overview");
  const [state, setState] = useState<DashboardState>(emptyState);
  const [resourceErrors, setResourceErrors] = useState<ResourceErrors>(emptyErrors);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [eventsOffset, setEventsOffset] = useState(0);
  const [eventsMaxItems, setEventsMaxItems] = useState<number | null>(100);
  const [eventsMinScore, setEventsMinScore] = useState(0);
  const [alertsOffset, setAlertsOffset] = useState(0);
  const [alertsMaxItems, setAlertsMaxItems] = useState<number | null>(100);
  const [alertsDecision, setAlertsDecision] = useState<string | null>(null);
  const [newsLimit, setNewsLimit] = useState(100);
  const [newsOffset, setNewsOffset] = useState(0);
  const [newsDomain, setNewsDomain] = useState("");
  const [newsSourceId, setNewsSourceId] = useState("");
  const [newsStatus, setNewsStatus] = useState("normalized");
  const [newsRegion, setNewsRegion] = useState("");
  const [selectedNewsId, setSelectedNewsId] = useState<string | null>(null);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [autoRefreshMs, setAutoRefreshMs] = useState<number>(
    () => Number(localStorage.getItem("mw-auto-refresh-ms") ?? "0"),
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [liveUpdateError, setLiveUpdateError] = useState<string | null>(null);
  const [alertSubTab, setAlertSubTab] = useState<AlertSubTab>("decisions");
  const [trackedCommand, setTrackedCommand] = useState<BotCommand | null>(null);
  const trackTimer = useRef<number | null>(null);
  const loadingKeys = useRef(new Set<ResourceKey>());
  const resourceCache = useRef(createResourceCache({ ttlMs: 15_000 })).current;
  const eventsParams = `${eventsOffset}:${eventsMaxItems ?? "all"}:${eventsMinScore}`;
  const previousEventsParams = useRef(eventsParams);
  const alertsParams = `${alertsOffset}:${alertsMaxItems ?? "all"}:${alertsDecision ?? "all"}`;
  const previousAlertsParams = useRef(alertsParams);
  const newsParams = `${newsLimit}:${newsDomain}:${newsOffset}:${newsSourceId}:${newsStatus}:${newsRegion}`;
  const previousNewsParams = useRef(newsParams);
  const newsFilters = useMemo(
    () =>
      newsSourceId || newsStatus || newsRegion
        ? {
            ...(newsSourceId ? { sourceId: newsSourceId } : {}),
            ...(newsStatus ? { status: newsStatus } : {}),
            ...(newsRegion ? { region: newsRegion } : {}),
          }
        : undefined,
    [newsRegion, newsSourceId, newsStatus],
  );

  const applyResult = useCallback((key: ResourceKey, value: unknown) => {
    setState((current) => {
      if (key === "status") return { ...current, status: value as BotStatus };
      if (key === "sources") {
        return { ...current, sources: normalizeListResponse<Source>(value).items };
      }
      if (key === "sourceHealth") {
        return { ...current, sourceHealth: normalizeListResponse<SourceHealth>(value).items };
      }
      if (key === "events") {
        const response = normalizeListResponse<EventCluster>(value);
        return { ...current, events: response.items, eventsTotal: response.total };
      }
      if (key === "news") {
        const response = normalizeListResponse<NewsItem>(value);
        return { ...current, news: response.items, newsTotal: response.total };
      }
      if (key === "newsDomains") {
        return { ...current, newsDomains: normalizeListResponse<string>(value).items };
      }
      if (key === "newsFilterOptions") {
        return { ...current, newsFilterOptions: value as NewsFilterOptions };
      }
      if (key === "alerts") {
        const response = normalizeListResponse<AlertDecision>(value);
        return { ...current, alerts: response.items, alertsTotal: response.total };
      }
      if (key === "alertChannels") {
        return {
          ...current,
          alertChannels: normalizeListResponse<AlertChannel>(value).items,
        };
      }
      if (key === "alertSuppressionRules") {
        return {
          ...current,
          alertSuppressionRules: normalizeListResponse<AlertSuppressionRule>(value).items,
        };
      }
      if (key === "jobs") return { ...current, jobs: normalizeListResponse<JobRun>(value).items };
      if (key === "watchlist") {
        return { ...current, watchlist: normalizeListResponse<WatchlistEntry>(value).items };
      }
      if (key === "commands") {
        return { ...current, commands: normalizeListResponse<BotCommand>(value).items };
      }
      if (key === "catalysts") {
        const response = normalizeListResponse<CatalystReview>(value);
        return {
          ...current,
          catalystReviews: response.items,
          catalystReviewsTotal: response.total,
        };
      }
      if (key === "digestLatest") return { ...current, latestDigest: value as Digest | null };
      if (key === "alertPolicy") return { ...current, alertPolicy: value as AlertPolicy };
      if (key === "presets") return { ...current, presets: value as ConfigurationPresets };
      return current;
    });
    setResourceErrors((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
  }, []);

  const loaders = useMemo<Record<ListResourceKey, () => Promise<unknown>>>(
    () => ({
      status: api.botStatus,
      sources: api.sources,
      sourceHealth: api.sourceHealth,
      events: () =>
        api.events({
          offset: eventsOffset,
          pageSize: EVENT_PAGE_SIZE,
          maxItems: eventsMaxItems,
          minScore: eventsMinScore,
        }),
      news: () =>
        newsFilters
          ? api.news(newsLimit, newsDomain || undefined, newsOffset, newsFilters)
          : api.news(newsLimit, newsDomain || undefined, newsOffset),
      newsDomains: api.newsDomains,
      newsFilterOptions: api.newsFilterOptions,
      alerts: () =>
        api.alerts({
          offset: alertsOffset,
          pageSize: ALERT_PAGE_SIZE,
          maxItems: alertsMaxItems,
          decision: alertsDecision,
        }),
      alertChannels: api.alertChannels,
      alertSuppressionRules: api.alertSuppressionRules,
      jobs: api.jobs,
      watchlist: api.watchlist,
      commands: api.commands,
      catalysts: () => api.maintenanceCatalysts(10, 0),
      digestLatest: api.digestLatest,
      alertPolicy: api.alertPolicy,
      presets: api.presets,
    }),
    [
      alertsDecision,
      alertsMaxItems,
      alertsOffset,
      eventsMaxItems,
      eventsMinScore,
      eventsOffset,
      newsDomain,
      newsFilters,
      newsLimit,
      newsOffset,
    ],
  );

  const loadResources = useCallback(
    async (keys: ListResourceKey[], invalidate = false) => {
      setLoading(true);
      keys.forEach((key) => {
        loadingKeys.current.add(key);
        if (invalidate) resourceCache.invalidate(key);
      });
      const results = await Promise.all(
        keys.map((key) => settle(key, resourceCache.get(key, loaders[key]))),
      );
      for (const result of results) {
        loadingKeys.current.delete(result.key as ResourceKey);
        if ("error" in result) {
          setResourceErrors((current) => ({ ...current, [result.key]: result.error }));
        } else {
          applyResult(result.key as ResourceKey, result.value);
        }
      }
      setLoading(loadingKeys.current.size > 0);
    },
    [applyResult, loaders, resourceCache],
  );

  const loadEventDetail = useCallback(
    async (id: string, invalidate = false) => {
      const key = `event:${id}`;
      if (invalidate) resourceCache.invalidate(key);
      const result = await settle("eventDetail", resourceCache.get(key, () => api.event(id)));
      if ("error" in result) {
        setResourceErrors((current) => ({ ...current, eventDetail: result.error }));
        return;
      }
      setState((current) => ({
        ...current,
        eventDetails: { ...current.eventDetails, [id]: result.value as EventDetail },
      }));
      setResourceErrors((current) => {
        const next = { ...current };
        delete next.eventDetail;
        return next;
      });
    },
    [resourceCache],
  );

  const loadOverviewSegments = useCallback(
    async (invalidate = false) => {
      await Promise.all(
        OVERVIEW_SEGMENTS.map(async (segment) => {
          const key = `overview-segment:${segment}`;
          if (invalidate) resourceCache.invalidate(key);
          const result = await settle(
            "events",
            resourceCache.get(key, () =>
              api.events({
                offset: 0,
                pageSize: OVERVIEW_SEGMENT_SIZE,
                maxItems: OVERVIEW_SEGMENT_SIZE,
                minScore: 0,
                segment,
              }),
            ),
          );
          // A single segment failing is non-fatal: leave its panel empty rather
          // than blanking the whole overview (the shared "events" load owns that).
          if ("error" in result) return;
          const response = normalizeListResponse<EventCluster>(result.value);
          setState((current) => ({
            ...current,
            overviewSegments: {
              ...current.overviewSegments,
              [segment]: { items: response.items, total: response.total },
            },
          }));
        }),
      );
    },
    [resourceCache],
  );

  const loadAlertDetail = useCallback(
    async (id: string, invalidate = false) => {
      const key = `alert:${id}`;
      if (invalidate) resourceCache.invalidate(key);
      const result = await settle("alertDetail", resourceCache.get(key, () => api.alert(id)));
      if ("error" in result) {
        setResourceErrors((current) => ({ ...current, alertDetail: result.error }));
        return;
      }
      setState((current) => ({
        ...current,
        alertDetails: { ...current.alertDetails, [id]: result.value as AlertDecision },
      }));
      setResourceErrors((current) => {
        const next = { ...current };
        delete next.alertDetail;
        return next;
      });
    },
    [resourceCache],
  );

  const loadNewsDetail = useCallback(
    async (id: string, invalidate = false) => {
      const key = `news:${id}`;
      if (invalidate) resourceCache.invalidate(key);
      const result = await settle("newsDetail", resourceCache.get(key, () => api.newsDetail(id)));
      if ("error" in result) {
        setResourceErrors((current) => ({ ...current, newsDetail: result.error }));
        return;
      }
      setState((current) => ({
        ...current,
        newsDetails: { ...current.newsDetails, [id]: result.value as NewsDetail },
      }));
      setResourceErrors((current) => {
        const next = { ...current };
        delete next.newsDetail;
        return next;
      });
    },
    [resourceCache],
  );

  const load = useCallback(
    async (invalidate = false) => {
      const keysByView: Record<View, ListResourceKey[]> = {
        overview: [
          "status",
          "events",
          "alerts",
          "sourceHealth",
          "watchlist",
          "alertPolicy",
          "catalysts",
          "digestLatest",
        ],
        events: ["status", "events"],
        news: ["status", "news", "newsDomains", "newsFilterOptions", "sources"],
        alerts:
          alertSubTab === "settings"
            ? ["status", "alertChannels", "alertSuppressionRules", "presets"]
            : ["status", "alerts"],
        sources: ["status", "sources", "sourceHealth", "presets"],
        watchlist: ["status", "watchlist", "presets"],
        commands: ["status", "commands", "sources", "events"],
        operations: ["status", "jobs", "alerts", "alertPolicy"],
        maintenance: ["status"],
      };
      await loadResources(keysByView[view], invalidate);
      if (view === "overview") void loadOverviewSegments(invalidate);
    },
    [alertSubTab, loadOverviewSegments, loadResources, view],
  );

  useEffect(() => {
    void loadResources([
      "status",
      "events",
      "alerts",
      "sourceHealth",
      "watchlist",
      "alertPolicy",
      "catalysts",
      "digestLatest",
    ]);
    void loadOverviewSegments();
  }, [loadOverviewSegments, loadResources]);

  useEffect(() => {
    if (view !== "overview") void load();
  }, [load, view]);

  useEffect(() => {
    if (previousNewsParams.current !== newsParams) {
      previousNewsParams.current = newsParams;
      if (view === "news") void loadResources(["news"], true);
    }
  }, [loadResources, newsParams, view]);

  useEffect(() => {
    if (previousEventsParams.current !== eventsParams) {
      previousEventsParams.current = eventsParams;
      if (view === "events" || view === "overview" || view === "commands") {
        void loadResources(["events"], true);
      }
    }
  }, [eventsParams, loadResources, view]);

  useEffect(() => {
    if (previousAlertsParams.current !== alertsParams) {
      previousAlertsParams.current = alertsParams;
      if (
        view === "alerts" ||
        view === "overview" ||
        view === "operations"
      ) {
        void loadResources(["alerts"], true);
      }
    }
  }, [alertsParams, loadResources, view]);

  useEffect(() => {
    let source: EventSource | null = null;
    let reconnectId: number | null = null;

    const connect = () => {
      source?.close();
      source = new EventSource(eventStreamUrl());
      source.onopen = () => setLiveUpdateError(null);
      source.onerror = () => {
        setLiveUpdateError("Live updates disconnected. Retrying...");
        source?.close();
        if (reconnectId === null) {
          reconnectId = window.setTimeout(() => {
            reconnectId = null;
            connect();
          }, 3_000);
        }
      };
      const refreshAlerts = () => {
        setLiveUpdateError(null);
        void loadResources(["status", "alerts"], true);
      };
      const refreshJobs = () => {
        setLiveUpdateError(null);
        void loadResources(["status", "jobs"], true);
      };
      const refreshCommands = () => {
        setLiveUpdateError(null);
        void loadResources(["status", "commands"], true);
      };
      source.addEventListener("alert.created", refreshAlerts);
      source.addEventListener("pipeline.completed", refreshJobs);
      source.addEventListener("command.updated", refreshCommands);
    };

    connect();
    return () => {
      if (reconnectId !== null) window.clearTimeout(reconnectId);
      source?.close();
    };
  }, [loadResources]);

  useEffect(() => {
    localStorage.setItem("mw-auto-refresh-ms", String(autoRefreshMs));
    if (!autoRefreshMs) return;
    const id = window.setInterval(() => void load(true), autoRefreshMs);
    return () => window.clearInterval(id);
  }, [autoRefreshMs, load]);

  const selectedEvent = useMemo(() => {
    const fromWindow = state.events.find((event) => event.id === selectedEventId);
    if (fromWindow) return fromWindow;
    // Events opened from the overview's per-segment lists may sit outside the
    // shared recency window, so fall back to those before the default.
    for (const segment of Object.values(state.overviewSegments)) {
      const match = segment.items.find((event) => event.id === selectedEventId);
      if (match) return match;
    }
    return state.events[0];
  }, [selectedEventId, state.events, state.overviewSegments]);
  const selectedEventDetail = selectedEvent ? state.eventDetails[selectedEvent.id] : undefined;
  const selectedNews = useMemo(
    () => state.news.find((item) => item.id === selectedNewsId) ?? null,
    [selectedNewsId, state.news],
  );
  const selectedNewsDetail = selectedNewsId ? state.newsDetails[selectedNewsId] : undefined;

  useEffect(() => {
    if (view === "events" && selectedEvent?.id) {
      void loadEventDetail(selectedEvent.id);
    }
  }, [loadEventDetail, selectedEvent?.id, view]);

  useEffect(() => {
    if (view === "news" && selectedNews?.id) {
      void loadNewsDetail(selectedNews.id);
    }
  }, [loadNewsDetail, selectedNews?.id, view]);

  const selectedAlert = useMemo(
    () => state.alerts.find((alert) => alert.id === selectedAlertId) ?? state.alerts[0],
    [selectedAlertId, state.alerts],
  );
  const selectedAlertDetail = selectedAlert
    ? state.alertDetails[selectedAlert.id] ?? selectedAlert
    : undefined;
  const selectedAlertEventDetail = selectedAlert
    ? state.eventDetails[selectedAlert.event_cluster_id]
    : undefined;

  useEffect(() => {
    if (view !== "alerts" || alertSubTab !== "decisions") return;
    if (!state.alerts.length) {
      if (selectedAlertId !== null) setSelectedAlertId(null);
      return;
    }
    if (!selectedAlertId || !state.alerts.some((alert) => alert.id === selectedAlertId)) {
      setSelectedAlertId(state.alerts[0].id);
    }
  }, [alertSubTab, selectedAlertId, state.alerts, view]);

  useEffect(() => {
    if (view === "alerts" && alertSubTab === "decisions" && selectedAlert?.id) {
      void loadAlertDetail(selectedAlert.id);
      void loadEventDetail(selectedAlert.event_cluster_id);
    }
  }, [
    alertSubTab,
    loadAlertDetail,
    loadEventDetail,
    selectedAlert?.event_cluster_id,
    selectedAlert?.id,
    view,
  ]);

  const filteredEvents = state.events.filter((event) =>
    `${event.canonical_headline} ${event.affected_entities.join(" ")} ${event.affected_tickers.join(" ")}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const errorCount = Object.keys(resourceErrors).length;
  const apiResourceCount = 14;
  const apiBadgeLabel =
    errorCount === 0 ? "API ok" : errorCount === apiResourceCount ? "API offline" : "API degraded";
  const apiBadgeTone =
    errorCount === 0 ? "success" : errorCount === apiResourceCount ? "error" : "warning";
  const workerRunning = state.status?.worker_running;
  const workerBadgeLabel =
    workerRunning === true
      ? "Worker ok"
      : workerRunning === false
        ? "Worker offline"
        : "Worker unknown";
  const workerBadgeTone =
    workerRunning === true ? "success" : workerRunning === false ? "error" : "warning";

  async function queue(
    commandType: string,
    payload: Record<string, unknown>,
    options?: { navigate?: boolean },
  ): Promise<BotCommand | null> {
    setActionError(null);
    try {
      const command = await api.createCommand(commandType, payload);
      resourceCache.invalidate();
      await load(true);
      if (options?.navigate !== false) setView("commands");
      return command;
    } catch (error) {
      setActionError(messageFromError(error, "Unable to queue command"));
      return null;
    }
  }

  // Poll a queued command until it reaches a terminal state, surfacing its live
  // status (so callers that stay in place don't have to navigate to Commands) and
  // refreshing overview resources once it succeeds.
  const trackCommand = useCallback(
    (command: BotCommand) => {
      const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);
      if (trackTimer.current) window.clearInterval(trackTimer.current);
      setTrackedCommand(command);
      if (TERMINAL.has(command.status)) return;
      const startedAt = Date.now();
      const stop = () => {
        if (trackTimer.current) window.clearInterval(trackTimer.current);
        trackTimer.current = null;
      };
      trackTimer.current = window.setInterval(async () => {
        try {
          const items = normalizeListResponse<BotCommand>(await api.commands()).items;
          const current = items.find((item) => item.id === command.id);
          if (current) setTrackedCommand(current);
          const done = current ? TERMINAL.has(current.status) : false;
          if (done || Date.now() - startedAt > 90_000) {
            stop();
            if (current?.status === "succeeded") {
              await loadResources(["digestLatest", "status"], true);
            }
            window.setTimeout(() => setTrackedCommand(null), 5_000);
          }
        } catch {
          stop();
        }
      }, 3_000);
    },
    [loadResources],
  );

  useEffect(() => () => {
    if (trackTimer.current) window.clearInterval(trackTimer.current);
  }, []);

  async function acknowledgeAlert(id: string) {
    setActionError(null);
    try {
      const alert = await api.acknowledgeAlert(id);
      resourceCache.invalidate(`alert:${id}`);
      setState((current) => ({
        ...current,
        alertDetails: { ...current.alertDetails, [id]: alert },
      }));
      await loadResources(["alerts"], true);
    } catch (error) {
      setActionError(messageFromError(error, "Unable to acknowledge alert"));
    }
  }

  async function dismissAlert(id: string) {
    setActionError(null);
    try {
      const alert = await api.dismissAlert(id);
      resourceCache.invalidate(`alert:${id}`);
      setState((current) => ({
        ...current,
        alertDetails: { ...current.alertDetails, [id]: alert },
      }));
      await loadResources(["alerts"], true);
    } catch (error) {
      setActionError(messageFromError(error, "Unable to update alert"));
    }
  }

  const unacknowledgedAlerts = state.alerts.filter(
    (alert) => alert.decision === "immediate_alert" && !alert.acknowledged_at,
  ).length;

  const updateNewsLimit = useCallback((limit: number) => {
    setNewsLimit(limit);
    setNewsOffset(0);
    setSelectedNewsId(null);
  }, []);

  const updateNewsDomain = useCallback((domain: string) => {
    setNewsDomain(domain);
    setNewsOffset(0);
    setSelectedNewsId(null);
  }, []);

  const updateNewsSourceId = useCallback((sourceId: string) => {
    setNewsSourceId(sourceId);
    setNewsOffset(0);
    setSelectedNewsId(null);
  }, []);

  const updateNewsStatus = useCallback((status: string) => {
    setNewsStatus(status);
    setNewsOffset(0);
    setSelectedNewsId(null);
  }, []);

  const updateNewsRegion = useCallback((region: string) => {
    setNewsRegion(region);
    setNewsOffset(0);
    setSelectedNewsId(null);
  }, []);

  const updateNewsOffset = useCallback((offset: number) => {
    setNewsOffset(Math.max(0, offset));
    setSelectedNewsId(null);
  }, []);

  const updateEventsMaxItems = useCallback((maxItems: number | null) => {
    setEventsMaxItems(maxItems);
    setEventsOffset(0);
    setSelectedEventId(null);
  }, []);

  const updateEventsMinScore = useCallback((score: number) => {
    setEventsMinScore(Math.max(0, Math.min(100, score)));
    setEventsOffset(0);
    setSelectedEventId(null);
  }, []);

  const updateEventsOffset = useCallback((offset: number) => {
    setEventsOffset(Math.max(0, offset));
    setSelectedEventId(null);
  }, []);

  const updateAlertsMaxItems = useCallback((maxItems: number | null) => {
    setAlertsMaxItems(maxItems);
    setAlertsOffset(0);
    setSelectedAlertId(null);
  }, []);

  const updateAlertsDecision = useCallback((decision: string | null) => {
    setAlertsDecision(decision);
    setAlertsOffset(0);
    setSelectedAlertId(null);
  }, []);

  const updateAlertsOffset = useCallback((offset: number) => {
    setAlertsOffset(Math.max(0, offset));
    setSelectedAlertId(null);
  }, []);

  return {
    view,
    setView,
    state,
    resourceErrors,
    loading,
    query,
    setQuery,
    eventsOffset,
    setEventsOffset: updateEventsOffset,
    eventsPageSize: EVENT_PAGE_SIZE,
    eventsMaxItems,
    setEventsMaxItems: updateEventsMaxItems,
    eventsMinScore,
    setEventsMinScore: updateEventsMinScore,
    alertsOffset,
    setAlertsOffset: updateAlertsOffset,
    alertsPageSize: ALERT_PAGE_SIZE,
    alertsMaxItems,
    setAlertsMaxItems: updateAlertsMaxItems,
    alertsDecision,
    setAlertsDecision: updateAlertsDecision,
    autoRefreshMs,
    setAutoRefreshMs,
    actionError,
    liveUpdateError,
    alertSubTab,
    setAlertSubTab,
    load,
    loadEventDetail,
    loadAlertDetail,
    selectedEvent,
    selectedEventDetail,
    selectedNewsId,
    selectedNewsDetail,
    selectedAlert,
    selectedAlertDetail,
    selectedAlertEventDetail,
    filteredEvents,
    errorCount,
    apiBadgeLabel,
    apiBadgeTone,
    workerBadgeLabel,
    workerBadgeTone,
    queue,
    trackCommand,
    trackedCommand,
    acknowledgeAlert,
    dismissAlert,
    unacknowledgedAlerts,
    setSelectedEventId,
    setSelectedNewsId,
    loadNewsDetail,
    newsLimit,
    setNewsLimit: updateNewsLimit,
    newsOffset,
    setNewsOffset: updateNewsOffset,
    newsDomain,
    setNewsDomain: updateNewsDomain,
    newsSourceId,
    setNewsSourceId: updateNewsSourceId,
    newsStatus,
    setNewsStatus: updateNewsStatus,
    newsRegion,
    setNewsRegion: updateNewsRegion,
    setSelectedAlertId,
  };
}
