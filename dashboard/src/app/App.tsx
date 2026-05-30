import { Bot, Palette, RefreshCcw, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
  AlertDecision,
  BotCommand,
  BotStatus,
  EventCluster,
  JobRun,
  NewsItem,
  Source,
  WatchlistEntry,
} from "../api";
import { api, normalizeListResponse } from "../api";
import { Badge } from "../components/Badge";
import { Panel } from "../components/Panel";
import { AlertsTable } from "../features/alerts/AlertsTable";
import { CommandsTable } from "../features/commands/CommandsTable";
import { Events } from "../features/events/Events";
import { NewsTable } from "../features/news/NewsTable";
import { Operations } from "../features/operations/Operations";
import { Overview } from "../features/overview/Overview";
import { SourcesTable } from "../features/sources/SourcesTable";
import { WatchlistTable } from "../features/watchlist/WatchlistTable";
import { classNames } from "../lib/classNames";
import { settle } from "../lib/errors";
import type { DashboardState, ResourceErrors, View } from "../types/dashboard";
import { nav } from "./navigation";
import { emptyErrors, emptyState } from "./state";

export function App() {
  const [view, setView] = useState<View>("overview");
  const [state, setState] = useState<DashboardState>(emptyState);
  const [resourceErrors, setResourceErrors] = useState<ResourceErrors>(emptyErrors);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [theme, setTheme] = useState<string>(
    () => localStorage.getItem("mw-theme") ?? "emerald_terminal",
  );

  useEffect(() => {
    document.documentElement.classList.add("dark");
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("mw-theme", theme);
  }, [theme]);

  async function load() {
    setLoading(true);
    const results = await Promise.all([
      settle("status", api.botStatus()),
      settle("sources", api.sources()),
      settle("events", api.events()),
      settle("news", api.news()),
      settle("alerts", api.alerts()),
      settle("jobs", api.jobs()),
      settle("watchlist", api.watchlist()),
      settle("commands", api.commands()),
    ]);
    const nextErrors: ResourceErrors = {};
    const nextState: DashboardState = { ...emptyState };

    for (const result of results) {
      if ("error" in result) {
        nextErrors[result.key] = result.error;
        continue;
      }
      if (result.key === "status") nextState.status = result.value as BotStatus;
      if (result.key === "sources") {
        nextState.sources = normalizeListResponse<Source>(result.value).items;
      }
      if (result.key === "events") {
        nextState.events = normalizeListResponse<EventCluster>(result.value).items;
      }
      if (result.key === "news") {
        nextState.news = normalizeListResponse<NewsItem>(result.value).items;
      }
      if (result.key === "alerts") {
        nextState.alerts = normalizeListResponse<AlertDecision>(result.value).items;
      }
      if (result.key === "jobs") {
        nextState.jobs = normalizeListResponse<JobRun>(result.value).items;
      }
      if (result.key === "watchlist") {
        nextState.watchlist = normalizeListResponse<WatchlistEntry>(result.value).items;
      }
      if (result.key === "commands") {
        nextState.commands = normalizeListResponse<BotCommand>(result.value).items;
      }
    }

    setState(nextState);
    setResourceErrors(nextErrors);
    setLoading(false);
  }

  useEffect(() => {
    void load();
  }, []);

  const selectedEvent = useMemo(
    () => state.events.find((event) => event.id === selectedEventId) ?? state.events[0],
    [selectedEventId, state.events],
  );

  const activeNavItem = nav.find((item) => item.id === view);
  const HeaderIcon = activeNavItem?.icon ?? Bot;

  const filteredEvents = state.events.filter((event) =>
    `${event.canonical_headline} ${event.affected_entities.join(" ")} ${event.affected_tickers.join(" ")}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const errorCount = Object.keys(resourceErrors).length;
  const apiBadgeLabel = errorCount === 0 ? "API ok" : errorCount === 8 ? "API offline" : "API degraded";
  const apiBadgeTone = errorCount === 0 ? "success" : errorCount === 8 ? "error" : "warning";

  async function queue(commandType: string, payload: Record<string, unknown>) {
    await api.createCommand(commandType, payload);
    await load();
    setView("commands");
  }

  return (
    <div
      className="min-h-screen bg-base-100 text-base-content"
      data-testid="dashboard-root"
      data-theme={theme}
    >
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-zinc-800 bg-zinc-950 lg:block">
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
        <header className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md">
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

              <div className="dropdown dropdown-end dropdown-bottom">
                <label
                  tabIndex={0}
                  className="btn btn-sm btn-outline gap-1.5 font-medium text-zinc-300 cursor-pointer"
                >
                  <Palette className="h-4 w-4" />
                  Theme
                </label>
                <ul
                  tabIndex={0}
                  className="dropdown-content z-[20] menu p-2 shadow-2xl bg-zinc-900 border border-zinc-800 rounded-box w-52 mt-1"
                >
                  <li>
                    <button
                      onClick={() => setTheme("marketwatch")}
                      className={classNames(
                        "justify-between rounded-md text-left",
                        theme === "marketwatch" && "active bg-primary/10 text-primary",
                      )}
                      type="button"
                    >
                      <span>Minimalist Mono</span>
                      <span className="h-2.5 w-2.5 rounded-full bg-zinc-100 border border-zinc-500" />
                    </button>
                  </li>
                  <li>
                    <button
                      onClick={() => setTheme("emerald_terminal")}
                      className={classNames(
                        "justify-between rounded-md text-left",
                        theme === "emerald_terminal" && "active bg-primary/10 text-primary",
                      )}
                      type="button"
                    >
                      <span>Financial Emerald</span>
                      <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                    </button>
                  </li>
                  <li>
                    <button
                      onClick={() => setTheme("amber_bronze")}
                      className={classNames(
                        "justify-between rounded-md text-left",
                        theme === "amber_bronze" && "active bg-primary/10 text-primary",
                      )}
                      type="button"
                    >
                      <span>Amber Bronze</span>
                      <span className="h-2.5 w-2.5 rounded-full bg-amber-600" />
                    </button>
                  </li>
                </ul>
              </div>

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
            <Overview state={state} errors={resourceErrors} queue={queue} retry={load} />
          ) : view === "events" ? (
            <Events
              events={filteredEvents}
              error={resourceErrors.events}
              query={query}
              selectedEvent={selectedEvent}
              setQuery={setQuery}
              setSelectedEventId={setSelectedEventId}
              queue={queue}
              retry={load}
            />
          ) : view === "news" ? (
            <NewsTable rows={state.news} error={resourceErrors.news} retry={load} />
          ) : view === "alerts" ? (
            <Panel title="Alert decisions">
              <AlertsTable rows={state.alerts} error={resourceErrors.alerts} retry={load} />
            </Panel>
          ) : view === "sources" ? (
            <SourcesTable rows={state.sources} error={resourceErrors.sources} reload={load} />
          ) : view === "watchlist" ? (
            <WatchlistTable rows={state.watchlist} error={resourceErrors.watchlist} retry={load} />
          ) : view === "commands" ? (
            <Panel title="Command queue">
              <CommandsTable
                rows={state.commands}
                error={resourceErrors.commands}
                retry={load}
                queue={queue}
              />
            </Panel>
          ) : (
            <Operations
              jobs={state.jobs}
              alerts={state.alerts}
              sources={state.sources}
              errors={resourceErrors}
              queue={queue}
              retry={load}
            />
          )}
        </section>
      </main>
    </div>
  );
}

