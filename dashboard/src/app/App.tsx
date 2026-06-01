import { Bot, Palette, RefreshCcw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AlertDecision,
  AlertChannel,
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
import { Badge } from "../components/Badge";
import { Panel } from "../components/Panel";
import { AlertsTable } from "../features/alerts/AlertsTable";
import { AlertControls } from "../features/alerts/AlertControls";
import { CommandsTable } from "../features/commands/CommandsTable";
import { Events } from "../features/events/Events";
import { NewsTable } from "../features/news/NewsTable";
import { Operations } from "../features/operations/Operations";
import { Overview } from "../features/overview/Overview";
import { SourcesTable } from "../features/sources/SourcesTable";
import { WatchlistTable } from "../features/watchlist/WatchlistTable";
import { Maintenance } from "../features/maintenance/Maintenance";
import { classNames } from "../lib/classNames";
import { createResourceCache } from "../lib/apiCache";
import { settle } from "../lib/errors";
import type { DashboardState, ResourceErrors, ResourceKey, View } from "../types/dashboard";
import { nav } from "./navigation";
import { emptyErrors, emptyState } from "./state";

const AUTO_REFRESH_OPTIONS = [
  { label: "Off", value: 0 },
  { label: "30s", value: 30_000 },
  { label: "60s", value: 60_000 },
  { label: "5m", value: 300_000 },
];

export function App() {
  const [view, setView] = useState<View>("overview");
  const [state, setState] = useState<DashboardState>(emptyState);
  const [resourceErrors, setResourceErrors] = useState<ResourceErrors>(emptyErrors);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [themeMode, setThemeMode] = useState<string>(
    () => localStorage.getItem("mw-theme-mode") ?? "dark",
  );
  const [autoRefreshMs, setAutoRefreshMs] = useState<number>(
    () => Number(localStorage.getItem("mw-auto-refresh-ms") ?? "0"),
  );
  const [alertSubTab, setAlertSubTab] = useState<"decisions" | "controls">("decisions");
  const [systemPrefersDark, setSystemPrefersDark] = useState(() =>
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true,
  );
  const loadingKeys = useRef(new Set<ResourceKey>());
  const resourceCache = useRef(createResourceCache({ ttlMs: 15_000 })).current;

  const effectiveTheme =
    themeMode === "light"
      ? "emerald_light"
      : themeMode === "system"
        ? systemPrefersDark
          ? "emerald_dark"
          : "emerald_light"
        : "emerald_dark";

  useEffect(() => {
    document.documentElement.classList.toggle("dark", effectiveTheme !== "emerald_light");
    document.documentElement.dataset.theme = effectiveTheme;
    localStorage.setItem("mw-theme-mode", themeMode);
  }, [effectiveTheme, themeMode]);

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media) return;
    const update = () => setSystemPrefersDark(media.matches);
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);

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

  const loaders: Record<Exclude<ResourceKey, "eventDetail">, () => Promise<unknown>> = {
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
  };

  const loadResources = useCallback(
    async (keys: Array<Exclude<ResourceKey, "eventDetail">>, invalidate = false) => {
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
    [applyResult],
  );

  const loadEventDetail = useCallback(async (id: string, invalidate = false) => {
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
  }, []);

  async function load(invalidate = false) {
    const keysByView: Record<View, Array<Exclude<ResourceKey, "eventDetail">>> = {
      overview: ["status", "events", "alerts"],
      events: ["status", "events"],
      news: ["status", "news"],
      alerts:
        alertSubTab === "controls"
          ? ["status", "alertChannels", "alertSuppressionRules", "presets"]
          : ["status", "alerts"],
      sources: ["status", "sources", "sourceHealth", "presets"],
      watchlist: ["status", "watchlist", "presets"],
      commands: ["status", "commands", "sources", "events"],
      operations: ["status", "jobs", "alerts", "alertPolicy"],
      maintenance: ["status"],
    };
    await loadResources(keysByView[view], invalidate);
  }

  useEffect(() => {
    void loadResources(["status", "events", "alerts"]);
  }, [loadResources]);

  useEffect(() => {
    if (view !== "overview") void load();
  }, [view, alertSubTab]);

  useEffect(() => {
    const source = new EventSource(eventStreamUrl());
    const refreshAlerts = () => void loadResources(["status", "alerts"], true);
    const refreshJobs = () => void loadResources(["status", "jobs"], true);
    const refreshCommands = () => void loadResources(["status", "commands"], true);
    source.addEventListener("alert.created", refreshAlerts);
    source.addEventListener("pipeline.completed", refreshJobs);
    source.addEventListener("command.updated", refreshCommands);
    return () => source.close();
  }, [loadResources]);

  useEffect(() => {
    localStorage.setItem("mw-auto-refresh-ms", String(autoRefreshMs));
    if (!autoRefreshMs) return;
    const id = window.setInterval(() => void load(true), autoRefreshMs);
    return () => window.clearInterval(id);
  }, [autoRefreshMs, view, alertSubTab]);

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

  const activeNavItem = nav.find((item) => item.id === view);
  const HeaderIcon = activeNavItem?.icon ?? Bot;

  const filteredEvents = state.events.filter((event) =>
    `${event.canonical_headline} ${event.affected_entities.join(" ")} ${event.affected_tickers.join(" ")}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const errorCount = Object.keys(resourceErrors).length;
  const apiResourceCount = 12;
  const apiBadgeLabel =
    errorCount === 0 ? "API ok" : errorCount === apiResourceCount ? "API offline" : "API degraded";
  const apiBadgeTone = errorCount === 0 ? "success" : errorCount === apiResourceCount ? "error" : "warning";

  async function queue(commandType: string, payload: Record<string, unknown>) {
    await api.createCommand(commandType, payload);
    resourceCache.invalidate();
    await load(true);
    setView("commands");
  }

  async function acknowledgeAlert(id: string) {
    await api.acknowledgeAlert(id);
    await loadResources(["alerts"], true);
  }

  async function dismissAlert(id: string) {
    await api.dismissAlert(id);
    await loadResources(["alerts"], true);
  }

  const unacknowledgedAlerts = state.alerts.filter(
    (alert) => alert.decision === "immediate_alert" && !alert.acknowledged_at,
  ).length;

  return (
    <div
      className="min-h-screen bg-base-100 text-base-content"
      data-testid="dashboard-root"
      data-theme={effectiveTheme}
    >
      <aside
        className="fixed inset-y-0 left-0 hidden w-64 border-r border-zinc-800 bg-zinc-950 lg:block dark"
        data-theme="emerald_dark"
      >
        <div className="flex h-16 items-center gap-3 border-b border-zinc-800 px-5">
          <ShieldCheck className="h-6 w-6 text-primary animate-pulse" />
          <div>
            <div className="text-sm font-bold text-zinc-100 tracking-wide">Market Watch</div>
            <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
              Assistant console
            </div>
          </div>
        </div>
        <nav className="space-y-1 p-4">
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={classNames(
                  "nav-button rounded-md transition-all duration-150 text-sm",
                  view === item.id
                    ? "bg-primary/10 border-l-[3px] border-primary text-primary font-semibold rounded-l-none"
                    : "text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-100",
                )}
                onClick={() => setView(item.id)}
                type="button"
              >
                <Icon className="h-4 w-4" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>
      <main className="lg:pl-64">
        <header
          className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md dark"
          data-theme="emerald_dark"
        >
          <div className="flex min-h-16 flex-wrap items-center justify-between gap-3 px-4 py-3 lg:px-6">
            <div className="flex items-center gap-3">
              <HeaderIcon className="h-5 w-5 text-secondary" />
              <div>
                <h1 className="text-lg font-bold text-zinc-100 tracking-tight">
                  {activeNavItem ? activeNavItem.label : "Market Watch Assistant"}
                </h1>
                <p className="text-xs text-base-content/60">
                  {state.status?.latest_job
                    ? `Latest ${state.status.latest_job.job_name}: ${state.status.latest_job.status}`
                    : "Waiting for bot activity"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone={apiBadgeTone}>{apiBadgeLabel}</Badge>
              {state.status?.command_queue_available === false ? (
                <Badge tone="warning">queue unavailable</Badge>
              ) : null}
              <Badge tone="info">{state.status?.pending_commands ?? 0} pending</Badge>
              {unacknowledgedAlerts > 0 ? (
                <Badge tone="warning">{unacknowledgedAlerts} unacknowledged</Badge>
              ) : null}

              <div className="dropdown dropdown-end dropdown-bottom">
                <button
                  tabIndex={0}
                  className="btn btn-sm btn-outline gap-1.5 font-medium text-zinc-300 cursor-pointer"
                  type="button"
                >
                  <Palette className="h-4 w-4" />
                  Theme
                </button>
                <ul
                  tabIndex={0}
                  className="dropdown-content z-[20] menu p-2 shadow-2xl bg-zinc-900 border border-zinc-800 rounded-box w-52 mt-1"
                >
                  <li>
                    <button
                      onClick={() => setThemeMode("system")}
                      className={classNames(
                        "justify-between rounded-md text-left",
                        themeMode === "system" && "active bg-primary/10 text-primary",
                      )}
                      type="button"
                    >
                      <span>System</span>
                      <span className="h-2.5 w-2.5 rounded-full bg-zinc-100 border border-zinc-500" />
                    </button>
                  </li>
                  <li>
                    <button
                      onClick={() => setThemeMode("dark")}
                      className={classNames(
                        "justify-between rounded-md text-left",
                        themeMode === "dark" && "active bg-primary/10 text-primary",
                      )}
                      type="button"
                    >
                      <span>Dark</span>
                      <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                    </button>
                  </li>
                  <li>
                    <button
                      onClick={() => setThemeMode("light")}
                      className={classNames(
                        "justify-between rounded-md text-left",
                        themeMode === "light" && "active bg-primary/10 text-primary",
                      )}
                      type="button"
                    >
                      <span>Light</span>
                      <span className="h-2.5 w-2.5 rounded-full bg-zinc-100" />
                    </button>
                  </li>
                </ul>
              </div>

              <label className="select select-bordered select-sm flex items-center gap-2">
                <span className="sr-only">Auto-refresh</span>
                <select
                  aria-label="Auto-refresh"
                  className="bg-transparent"
                  onChange={(event) => setAutoRefreshMs(Number(event.target.value))}
                  value={autoRefreshMs}
                >
                  {AUTO_REFRESH_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      Auto {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <button className="btn btn-sm btn-outline" onClick={() => void load()} type="button">
                <RefreshCcw className="h-4 w-4" />
                Refresh
              </button>
            </div>
          </div>
        </header>
        <section className="px-4 py-5 lg:px-6">
          {errorCount > 0 ? (
            <div className="alert alert-warning mb-4 text-sm">
              {errorCount} dashboard resource{errorCount === 1 ? "" : "s"} unavailable. Loaded
              sections remain usable.
            </div>
          ) : null}
          {loading ? <div className="loading loading-spinner loading-md" /> : null}
          <div className="lg:hidden">
            <select
              className="select select-bordered mb-4 w-full"
              onChange={(event) => setView(event.target.value as View)}
              value={view}
            >
              {nav.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          {view === "overview" ? (
            <Overview state={state} errors={resourceErrors} retry={() => load(true)} />
          ) : view === "events" ? (
            <Events
              events={filteredEvents}
              error={resourceErrors.events}
              query={query}
              selectedEvent={selectedEvent}
              selectedEventDetail={selectedEventDetail}
              setQuery={setQuery}
              setSelectedEventId={(id) => {
                setSelectedEventId(id);
                void loadEventDetail(id);
              }}
              queue={queue}
              retry={() => load(true)}
            />
          ) : view === "news" ? (
            <NewsTable rows={state.news} error={resourceErrors.news} retry={() => load(true)} />
          ) : view === "alerts" ? (
            <div className="space-y-4">
              <div className="tabs tabs-boxed border border-zinc-800/60 bg-zinc-950/60 p-1 flex flex-wrap gap-1">
                <button
                  className={`tab tab-sm sm:tab-md transition-all duration-200 flex items-center gap-2 ${alertSubTab === "decisions"
                      ? "tab-active bg-indigo-600/90 text-white font-bold"
                      : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  onClick={() => setAlertSubTab("decisions")}
                  type="button"
                >
                  Overview
                </button>
                <button
                  className={`tab tab-sm sm:tab-md transition-all duration-200 flex items-center gap-2 ${alertSubTab === "controls"
                      ? "tab-active bg-indigo-600/90 text-white font-bold"
                      : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  onClick={() => setAlertSubTab("controls")}
                  type="button"
                >
                  Setting
                </button>
              </div>

              {alertSubTab === "decisions" ? (
                <Panel title="Alert decisions">
                  <AlertsTable
                    rows={state.alerts}
                    error={resourceErrors.alerts}
                    retry={() => load(true)}
                    acknowledge={acknowledgeAlert}
                    dismiss={dismissAlert}
                  />
                </Panel>
              ) : (
                <AlertControls
                  channels={state.alertChannels}
                  rules={state.alertSuppressionRules}
                  reload={() => load(true)}
                  presets={state.presets}
                />
              )}
            </div>
          ) : view === "sources" ? (
            <SourcesTable
              rows={state.sources}
              health={state.sourceHealth}
              error={resourceErrors.sources}
              presets={state.presets?.sources ?? null}
              reload={() => load(true)}
              queue={queue}
            />
          ) : view === "watchlist" ? (
            <WatchlistTable
              rows={state.watchlist}
              error={resourceErrors.watchlist}
              presets={state.presets?.watchlist ?? null}
              retry={() => load(true)}
            />
          ) : view === "commands" ? (
            <Panel title="Command queue">
              <CommandsTable
                rows={state.commands}
                error={resourceErrors.commands}
                retry={() => load(true)}
                queue={queue}
                queueUnavailable={state.status?.command_queue_available === false}
                sources={state.sources}
                events={state.events}
              />
            </Panel>
          ) : view === "operations" ? (
            <Operations
              jobs={state.jobs}
              alerts={state.alerts}
              errors={resourceErrors}
              alertPolicy={state.alertPolicy}
              queue={queue}
              retry={() => load(true)}
            />
          ) : (
            <Maintenance />
          )}
        </section>
      </main>
    </div>
  );
}
