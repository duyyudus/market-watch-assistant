import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AlertChannel,
  AlertDecision,
  AlertPolicy,
  AlertSuppressionRule,
  BotCommand,
  BotStatus,
  ConfigurationPresets,
  EventCluster,
  EventDetail,
  JobRun,
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

type ListResourceKey = Exclude<ResourceKey, "alertDetail" | "eventDetail">;
export type AlertSubTab = "decisions" | "settings";

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
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [autoRefreshMs, setAutoRefreshMs] = useState<number>(
    () => Number(localStorage.getItem("mw-auto-refresh-ms") ?? "0"),
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [liveUpdateError, setLiveUpdateError] = useState<string | null>(null);
  const [alertSubTab, setAlertSubTab] = useState<AlertSubTab>("decisions");
  const loadingKeys = useRef(new Set<ResourceKey>());
  const resourceCache = useRef(createResourceCache({ ttlMs: 15_000 })).current;

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
        return { ...current, events: normalizeListResponse<EventCluster>(value).items };
      }
      if (key === "news") return { ...current, news: normalizeListResponse<NewsItem>(value).items };
      if (key === "alerts") {
        return { ...current, alerts: normalizeListResponse<AlertDecision>(value).items };
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
      events: api.events,
      news: api.news,
      alerts: api.alerts,
      alertChannels: api.alertChannels,
      alertSuppressionRules: api.alertSuppressionRules,
      jobs: api.jobs,
      watchlist: api.watchlist,
      commands: api.commands,
      alertPolicy: api.alertPolicy,
      presets: api.presets,
    }),
    [],
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

  const load = useCallback(
    async (invalidate = false) => {
      const keysByView: Record<View, ListResourceKey[]> = {
        overview: ["status", "events", "alerts"],
        events: ["status", "events"],
        news: ["status", "news"],
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
    },
    [alertSubTab, loadResources, view],
  );

  useEffect(() => {
    void loadResources(["status", "events", "alerts"]);
  }, [loadResources]);

  useEffect(() => {
    if (view !== "overview") void load();
  }, [load, view]);

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

  const selectedEvent = useMemo(
    () => state.events.find((event) => event.id === selectedEventId) ?? state.events[0],
    [selectedEventId, state.events],
  );
  const selectedEventDetail = selectedEvent ? state.eventDetails[selectedEvent.id] : undefined;

  useEffect(() => {
    if (view === "events" && selectedEvent?.id) {
      void loadEventDetail(selectedEvent.id);
    }
  }, [loadEventDetail, selectedEvent?.id, view]);

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
  const apiResourceCount = 12;
  const apiBadgeLabel =
    errorCount === 0 ? "API ok" : errorCount === apiResourceCount ? "API offline" : "API degraded";
  const apiBadgeTone =
    errorCount === 0 ? "success" : errorCount === apiResourceCount ? "error" : "warning";

  async function queue(commandType: string, payload: Record<string, unknown>) {
    setActionError(null);
    try {
      await api.createCommand(commandType, payload);
      resourceCache.invalidate();
      await load(true);
      setView("commands");
    } catch (error) {
      setActionError(messageFromError(error, "Unable to queue command"));
    }
  }

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

  return {
    view,
    setView,
    state,
    resourceErrors,
    loading,
    query,
    setQuery,
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
    selectedAlert,
    selectedAlertDetail,
    selectedAlertEventDetail,
    filteredEvents,
    errorCount,
    apiBadgeLabel,
    apiBadgeTone,
    queue,
    acknowledgeAlert,
    dismissAlert,
    unacknowledgedAlerts,
    setSelectedEventId,
    setSelectedAlertId,
  };
}
