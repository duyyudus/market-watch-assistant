import { Bot, Palette, RefreshCcw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "../components/Badge";
import { DashboardErrorBoundary } from "../components/ErrorBoundary";
import { Panel } from "../components/Panel";
import { Alerts } from "../features/alerts/Alerts";
import { CommandsTable } from "../features/commands/CommandsTable";
import { Events } from "../features/events/Events";
import { Maintenance } from "../features/maintenance/Maintenance";
import { NewsTable } from "../features/news/NewsTable";
import { Overview } from "../features/overview/Overview";
import { SourcesTable } from "../features/sources/SourcesTable";
import { WatchlistTable } from "../features/watchlist/WatchlistTable";
import { classNames } from "../lib/classNames";
import type { View } from "../types/dashboard";
import { nav } from "./navigation";
import { useDashboardData } from "./useDashboardData";

const AUTO_REFRESH_OPTIONS = [
  { label: "Off", value: 0 },
  { label: "30s", value: 30_000 },
  { label: "60s", value: 60_000 },
  { label: "5m", value: 300_000 },
];

export function App() {
  const {
    view,
    setView,
    state,
    resourceErrors,
    loading,
    query,
    setQuery,
    eventsOffset,
    setEventsOffset,
    eventsPageSize,
    eventsMaxItems,
    setEventsMaxItems,
    eventsMinScore,
    setEventsMinScore,
    eventsRegion,
    setEventsRegion,
    alertsOffset,
    setAlertsOffset,
    alertsPageSize,
    alertsMaxItems,
    setAlertsMaxItems,
    alertsDecision,
    setAlertsDecision,
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
    setSelectedEventId,
    setSelectedNewsId,
    loadNewsDetail,
    newsLimit,
    setNewsLimit,
    newsOffset,
    setNewsOffset,
    newsDomain,
    setNewsDomain,
    newsSourceId,
    setNewsSourceId,
    newsStatus,
    setNewsStatus,
    newsRegion,
    setNewsRegion,
    setSelectedAlertId,
  } = useDashboardData();
  const [themeMode, setThemeMode] = useState<string>(
    () => localStorage.getItem("mw-theme-mode") ?? "dark",
  );
  const [systemPrefersDark, setSystemPrefersDark] = useState(() =>
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true,
  );

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

  const activeNavItem = nav.find((item) => item.id === view);
  const HeaderIcon = activeNavItem?.icon ?? Bot;

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
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Badge tone={apiBadgeTone}>{apiBadgeLabel}</Badge>
              <Badge tone={workerBadgeTone}>{workerBadgeLabel}</Badge>
              {state.status?.command_queue_available === false ? (
                <Badge tone="warning">queue unavailable</Badge>
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
          {liveUpdateError ? (
            <div className="alert alert-warning mb-4 text-sm">{liveUpdateError}</div>
          ) : null}
          {actionError ? <div className="alert alert-error mb-4 text-sm">{actionError}</div> : null}
          {loading ? <div className="loading loading-spinner loading-md" /> : null}
          <div className="lg:hidden">
            <select
              aria-label="View"
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
          <DashboardErrorBoundary resetKey={`${view}:${alertSubTab}`}>
            {view === "overview" ? (
              <Overview
                state={state}
                errors={resourceErrors}
                retry={() => load(true)}
                loadEventDetail={(id) => void loadEventDetail(id)}
                queue={queue}
                trackCommand={trackCommand}
                trackedCommand={trackedCommand}
                openEvent={(id) => {
                  setSelectedEventId(id);
                  void loadEventDetail(id);
                  setView("events");
                }}
                openSources={() => setView("sources")}
                openMaintenance={() => setView("maintenance")}
              />
            ) : view === "events" ? (
              <Events
                events={filteredEvents}
                error={resourceErrors.events}
                query={query}
                maxItems={eventsMaxItems}
                minScore={eventsMinScore}
                region={eventsRegion}
                regionOptions={state.eventFilterOptions.regions}
                offset={eventsOffset}
                pageSize={eventsPageSize}
                total={state.eventsTotal}
                selectedEvent={selectedEvent}
                selectedEventDetail={selectedEventDetail}
                setQuery={setQuery}
                setMaxItems={setEventsMaxItems}
                setMinScore={setEventsMinScore}
                setRegion={setEventsRegion}
                setOffset={setEventsOffset}
                setSelectedEventId={(id) => {
                  setSelectedEventId(id);
                  void loadEventDetail(id);
                }}
                queue={queue}
                retry={() => load(true)}
              />
            ) : view === "news" ? (
              <NewsTable
                rows={state.news}
                error={resourceErrors.news}
                detailError={resourceErrors.newsDetail}
                retry={() => load(true)}
                selectedNewsId={selectedNewsId}
                selectedNewsDetail={selectedNewsDetail ?? null}
                selectNews={(id) => {
                  setSelectedNewsId(id);
                  void loadNewsDetail(id);
                }}
                limit={newsLimit}
                setLimit={setNewsLimit}
                offset={newsOffset}
                total={state.newsTotal}
                setOffset={setNewsOffset}
                domain={newsDomain}
                setDomain={setNewsDomain}
                domainOptions={state.newsDomains}
                sourceId={newsSourceId}
                setSourceId={setNewsSourceId}
                sourceOptions={state.sources}
                status={newsStatus}
                setStatus={setNewsStatus}
                statusOptions={state.newsFilterOptions.statuses}
                region={newsRegion}
                setRegion={setNewsRegion}
                regionOptions={state.newsFilterOptions.regions}
              />
            ) : view === "alerts" ? (
              <Alerts
                activeTab={alertSubTab}
                onTabChange={setAlertSubTab}
                alerts={state.alerts}
                alertError={resourceErrors.alerts}
                maxItems={alertsMaxItems}
                decision={alertsDecision}
                offset={alertsOffset}
                pageSize={alertsPageSize}
                total={state.alertsTotal}
                setMaxItems={setAlertsMaxItems}
                setDecision={setAlertsDecision}
                setOffset={setAlertsOffset}
                selectedAlertId={selectedAlert?.id}
                selectedAlertDetail={selectedAlertDetail}
                selectedAlertEventDetail={selectedAlertEventDetail}
                newsDetails={state.newsDetails}
                alertDetailError={resourceErrors.alertDetail}
                eventDetailError={resourceErrors.eventDetail}
                newsDetailError={resourceErrors.newsDetail}
                retryAlerts={() => load(true)}
                retrySelectedAlertDetail={async () => {
                  if (selectedAlert?.id) {
                    await loadAlertDetail(selectedAlert.id, true);
                    await loadEventDetail(selectedAlert.event_cluster_id, true);
                  }
                }}
                loadNewsDetail={(id) => void loadNewsDetail(id)}
                onSelectAlert={(id) => setSelectedAlertId(id)}
                alertPolicy={state.alertPolicy}
                alertPolicyError={resourceErrors.alertPolicy}
                channels={state.alertChannels}
                rules={state.alertSuppressionRules}
                reload={() => load(true)}
                presets={state.presets}
              />
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
            ) : (
              <Maintenance
                jobs={state.jobs}
                errors={resourceErrors}
                retry={() => load(true)}
              />
            )}
          </DashboardErrorBoundary>
        </section>
      </main>
    </div>
  );
}
