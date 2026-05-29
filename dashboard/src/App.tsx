import {
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Bell,
  Bot,
  ChevronRight,
  Database,
  Newspaper,
  Palette,
  Play,
  Radio,
  RefreshCcw,
  Search,
  Settings,
  ShieldCheck,
  Star,
  TerminalSquare,
} from "lucide-react";
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
} from "./api";
import { api, normalizeListResponse } from "./api";

type View =
  | "overview"
  | "events"
  | "news"
  | "alerts"
  | "sources"
  | "watchlist"
  | "commands"
  | "operations";

type DashboardState = {
  status: BotStatus | null;
  sources: Source[];
  events: EventCluster[];
  news: NewsItem[];
  alerts: AlertDecision[];
  jobs: JobRun[];
  watchlist: WatchlistEntry[];
  commands: BotCommand[];
};

type ResourceKey =
  | "status"
  | "sources"
  | "events"
  | "news"
  | "alerts"
  | "jobs"
  | "watchlist"
  | "commands";

type ResourceErrors = Partial<Record<ResourceKey, string>>;

const nav: { id: View; label: string; icon: typeof Activity }[] = [
  { id: "overview", label: "Overview", icon: Activity },
  { id: "events", label: "Events", icon: Database },
  { id: "news", label: "News", icon: Newspaper },
  { id: "alerts", label: "Alerts", icon: Bell },
  { id: "sources", label: "Sources", icon: Radio },
  { id: "watchlist", label: "Watchlist", icon: Star },
  { id: "commands", label: "Commands", icon: TerminalSquare },
  { id: "operations", label: "Operations", icon: Settings },
];

const emptyState: DashboardState = {
  status: null,
  sources: [],
  events: [],
  news: [],
  alerts: [],
  jobs: [],
  watchlist: [],
  commands: [],
};

const emptyErrors: ResourceErrors = {};

function classNames(...values: (string | false | null | undefined)[]) {
  return values.filter(Boolean).join(" ");
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`badge badge-sm badge-${tone}`}>{children}</span>;
}

function formatTime(value?: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function scoreTone(score: number) {
  if (score >= 80) return "error";
  if (score >= 55) return "warning";
  if (score >= 30) return "info";
  return "neutral";
}

function errorMessage(value: unknown) {
  return value instanceof Error ? value.message : "Failed to load data";
}

async function settle<T>(key: ResourceKey, request: Promise<T>) {
  try {
    return { key, value: await request };
  } catch (error) {
    return { key, error: errorMessage(error) };
  }
}

export function compareValues(a: any, b: any) {
  if (a === b) return 0;
  if (a == null) return -1;
  if (b == null) return 1;

  if (typeof a === "string" && typeof b === "string") {
    const aTime = Date.parse(a);
    const bTime = Date.parse(b);
    const isADate = a.includes("-") || a.includes(":");
    const isBDate = b.includes("-") || b.includes(":");
    if (isADate && isBDate && !isNaN(aTime) && !isNaN(bTime)) {
      return aTime - bTime;
    }
    return a.localeCompare(b);
  }

  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }

  if (typeof a === "boolean" && typeof b === "boolean") {
    return a === b ? 0 : a ? 1 : -1;
  }

  return String(a).localeCompare(String(b));
}

export function useSortableData<T>(
  items: T[],
  config: { key: string; direction: "asc" | "desc" }
) {
  const [sortConfig, setSortConfig] = useState(config);

  const sortedItems = useMemo(() => {
    let sortableItems = [...items];
    if (sortConfig.key) {
      sortableItems.sort((a: any, b: any) => {
        let aValue: any;
        let bValue: any;

        if (sortConfig.key === "time") {
          aValue = a.published_at ?? a.fetched_at;
          bValue = b.published_at ?? b.fetched_at;
        } else if (sortConfig.key === "sent") {
          aValue = a.sent_at ?? a.created_at;
          bValue = b.sent_at ?? b.created_at;
        } else if (sortConfig.key === "event_headline") {
          aValue = a.event?.headline ?? a.reason;
          bValue = b.event?.headline ?? b.reason;
        } else {
          aValue = a[sortConfig.key];
          bValue = b[sortConfig.key];
        }

        const comp = compareValues(aValue, bValue);
        return sortConfig.direction === "asc" ? comp : -comp;
      });
    }
    return sortableItems;
  }, [items, sortConfig]);

  const requestSort = (key: string) => {
    let direction: "asc" | "desc" = "asc";
    if (sortConfig.key === key && sortConfig.direction === "asc") {
      direction = "desc";
    }
    setSortConfig({ key, direction });
  };

  return { items: sortedItems, requestSort, sortConfig };
}

function SortableHeader({
  label,
  sortKey,
  currentSortKey,
  direction,
  onSort,
}: {
  label: string;
  sortKey: string;
  currentSortKey: string;
  direction: "asc" | "desc";
  onSort: (key: string) => void;
}) {
  const isActive = currentSortKey === sortKey;
  return (
    <th
      className="py-3 px-4 font-semibold text-left cursor-pointer hover:bg-zinc-800/40 select-none transition-colors duration-150 group"
      onClick={() => onSort(sortKey)}
    >
      <div className="flex items-center gap-1.5">
        <span>{label}</span>
        {isActive ? (
          direction === "asc" ? (
            <ArrowUp className="h-3.5 w-3.5 text-primary" />
          ) : (
            <ArrowDown className="h-3.5 w-3.5 text-primary" />
          )
        ) : (
          <ArrowUpDown className="h-3.5 w-3.5 text-zinc-600 opacity-30 group-hover:opacity-100 transition-opacity" />
        )}
      </div>
    </th>
  );
}

export function App() {
  const [view, setView] = useState<View>("overview");
  const [state, setState] = useState<DashboardState>(emptyState);
  const [resourceErrors, setResourceErrors] = useState<ResourceErrors>(emptyErrors);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("mw-theme") ?? "emerald_terminal");

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
      if (result.key === "jobs") nextState.jobs = normalizeListResponse<JobRun>(result.value).items;
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
            <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Assistant console</div>
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
                    : "text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-100"
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
                <label tabIndex={0} className="btn btn-sm btn-outline gap-1.5 font-medium text-zinc-300 cursor-pointer">
                  <Palette className="h-4 w-4" />
                  Theme
                </label>
                <ul tabIndex={0} className="dropdown-content z-[20] menu p-2 shadow-2xl bg-zinc-900 border border-zinc-800 rounded-box w-52 mt-1">
                  <li>
                    <button 
                      onClick={() => setTheme("marketwatch")}
                      className={classNames("justify-between rounded-md text-left", theme === "marketwatch" && "active bg-primary/10 text-primary")}
                      type="button"
                    >
                      <span>Minimalist Mono</span>
                      <span className="h-2.5 w-2.5 rounded-full bg-zinc-100 border border-zinc-500" />
                    </button>
                  </li>
                  <li>
                    <button 
                      onClick={() => setTheme("emerald_terminal")}
                      className={classNames("justify-between rounded-md text-left", theme === "emerald_terminal" && "active bg-primary/10 text-primary")}
                      type="button"
                    >
                      <span>Financial Emerald</span>
                      <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                    </button>
                  </li>
                  <li>
                    <button 
                      onClick={() => setTheme("amber_bronze")}
                      className={classNames("justify-between rounded-md text-left", theme === "amber_bronze" && "active bg-primary/10 text-primary")}
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
              {errorCount} dashboard resource{errorCount === 1 ? "" : "s"} unavailable. Loaded sections remain usable.
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
              <CommandsTable rows={state.commands} error={resourceErrors.commands} retry={load} queue={queue} />
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

function Overview({
  state,
  errors,
  queue,
  retry,
}: {
  state: DashboardState;
  errors: ResourceErrors;
  queue: (type: string, payload: Record<string, unknown>) => Promise<void>;
  retry: () => Promise<void>;
}) {
  const enabledSources = state.sources.filter((source) => source.enabled).length;
  const immediateAlerts = state.alerts.filter((alert) => alert.decision === "immediate_alert").length;
  const failedJobs = state.jobs.filter((job) => job.status !== "success").length;

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="High score events" value={state.events.filter((event) => event.final_score >= 80).length} />
        <Metric label="Enabled sources" value={`${enabledSources}/${state.sources.length}`} />
        <Metric label="Immediate alerts" value={immediateAlerts} />
        <Metric label="Job failures" value={failedJobs} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Panel title="Priority events">
          <EventRows events={state.events.slice(0, 8)} error={errors.events} retry={retry} />
        </Panel>
        <Panel title="Manual controls">
          <div className="grid gap-2">
            <button className="btn btn-primary btn-sm justify-start" onClick={() => queue("pipeline.run", { dry_run: true })} type="button">
              <Play className="h-4 w-4" />
              Dry-run pipeline
            </button>
            <button className="btn btn-outline btn-sm justify-start" onClick={() => queue("alert.dispatch", { channel: "telegram", limit: 20, dry_run: true })} type="button">
              <Bell className="h-4 w-4" />
              Preview alert dispatch
            </button>
          </div>
        </Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Recent alerts">
          <AlertsTable rows={state.alerts.slice(0, 5)} compact error={errors.alerts} retry={retry} />
        </Panel>
        <Panel title="Recent jobs">
          <JobsTable rows={state.jobs.slice(0, 6)} error={errors.jobs} retry={retry} />
        </Panel>
        <Panel title="Command queue">
          <CommandsTable rows={state.commands.slice(0, 6)} compact error={errors.commands} retry={retry} queue={queue} />
        </Panel>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-5 shadow-lg shadow-black/10 backdrop-blur-md">
      <div className="text-xs font-bold uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="mt-2 text-4xl font-black text-zinc-100 tracking-tight">{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 shadow-lg shadow-black/10 backdrop-blur-md overflow-hidden">
      <div className="border-b border-zinc-800/60 bg-zinc-900/40 px-5 py-4">
        <h3 className="text-sm font-bold text-zinc-200 tracking-widest uppercase">{title}</h3>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function EmptyState({
  icon: Icon = Database,
  title,
  body,
  action,
}: {
  icon?: typeof Activity;
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-36 flex-col items-center justify-center rounded-lg border border-dashed border-zinc-800 bg-zinc-950/30 px-5 py-8 text-center">
      <Icon className="h-6 w-6 text-zinc-500" />
      <h4 className="mt-3 text-sm font-bold text-zinc-200">{title}</h4>
      <p className="mt-1 max-w-md text-sm text-base-content/60">{body}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

function SectionError({
  title,
  message,
  retry,
}: {
  title: string;
  message: string;
  retry: () => Promise<void>;
}) {
  return (
    <div className="rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm">
      <div className="font-bold text-warning">{title}</div>
      <div className="mt-1 break-words text-base-content/70">{message}</div>
      <button className="btn btn-warning btn-xs mt-3" onClick={() => void retry()} type="button">
        <RefreshCcw className="h-3.5 w-3.5" />
        Retry
      </button>
    </div>
  );
}

function Events(props: {
  events: EventCluster[];
  error?: string;
  query: string;
  selectedEvent?: EventCluster;
  setQuery: (value: string) => void;
  setSelectedEventId: (value: string) => void;
  queue: (type: string, payload: Record<string, unknown>) => Promise<void>;
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
              <input value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder="Search events, tickers, entities" />
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
              <Badge tone={scoreTone(props.selectedEvent.final_score)}>{props.selectedEvent.final_score}</Badge>
              <h2 className="mt-2 text-xl font-bold text-zinc-100">{props.selectedEvent.canonical_headline}</h2>
              <p className="mt-1 text-sm text-base-content/70">{props.selectedEvent.summary ?? "No summary yet."}</p>
            </div>
            <div className="grid gap-2 text-sm">
              <Detail label="Status" value={props.selectedEvent.status} />
              <Detail label="Regions" value={props.selectedEvent.regions.join(", ") || "-"} />
              <Detail label="Assets" value={props.selectedEvent.asset_classes.join(", ") || "-"} />
              <Detail label="Entities" value={props.selectedEvent.affected_entities.join(", ") || "-"} />
              <Detail label="Tickers" value={props.selectedEvent.affected_tickers.join(", ") || "-"} />
              <Detail label="Sources" value={props.selectedEvent.source_count} />
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <button className="btn btn-sm btn-outline" onClick={() => props.queue("event.rescore", { event_id: props.selectedEvent!.id })} type="button">
                Rescore
              </button>
              <button className="btn btn-sm btn-outline" onClick={() => props.queue("investigation.run_event", { event_id: props.selectedEvent!.id })} type="button">
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

function EventRows({
  events,
  onSelect,
  error,
  retry,
}: {
  events: EventCluster[];
  onSelect?: (id: string) => void;
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedEvents, requestSort, sortConfig } = useSortableData(events, {
    key: "last_updated_at",
    direction: "desc",
  });

  if (error) {
    return <SectionError title="Event clusters unavailable" message={error} retry={retry} />;
  }

  if (sortedEvents.length === 0) {
    return (
      <EmptyState
        icon={Database}
        title="No priority events yet"
        body="No event clusters match the current data set or search filter."
        action={
          <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
            <RefreshCcw className="h-4 w-4" />
            Refresh
          </button>
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="table w-full">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
            <SortableHeader
              label="Score"
              sortKey="final_score"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Headline"
              sortKey="canonical_headline"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Status"
              sortKey="status"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Sources"
              sortKey="source_count"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Updated"
              sortKey="last_updated_at"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/40">
          {sortedEvents.map((event) => (
            <tr
              key={event.id}
              className={classNames(
                "group border-b border-zinc-800/30 transition-colors duration-150",
                onSelect && "cursor-pointer hover:bg-zinc-800/20"
              )}
              onClick={() => onSelect?.(event.id)}
            >
              <td className="py-3 px-4">
                <Badge tone={scoreTone(event.final_score)}>{event.final_score}</Badge>
              </td>
              <td className="py-3 px-4 max-w-[520px] whitespace-normal text-sm font-semibold text-zinc-200 group-hover:text-primary transition-colors duration-150">
                {event.canonical_headline}
              </td>
              <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{event.status}</td>
              <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{event.source_count}</td>
              <td className="py-3 px-4 text-zinc-500 font-normal text-xs">{formatTime(event.last_updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NewsTable({
  rows,
  error,
  retry,
}: {
  rows: NewsItem[];
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "time",
    direction: "desc",
  });

  return (
    <Panel title="Normalized news">
      {error ? (
        <SectionError title="Normalized news unavailable" message={error} retry={retry} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Newspaper}
          title="No normalized news yet"
          body="Ingested news will appear here after source fetch and normalization jobs run."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
      <div className="overflow-x-auto">
        <table className="table w-full">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
              <SortableHeader
                label="Title"
                sortKey="title"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Source"
                sortKey="source_name"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Status"
                sortKey="processing_status"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Region"
                sortKey="region"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Time"
                sortKey="time"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/40">
            {sortedRows.map((row) => (
              <tr key={row.id} className="border-b border-zinc-800/30">
                <td className="py-3 px-4 max-w-[620px] whitespace-normal text-sm font-semibold text-zinc-200">{row.title}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.source_name}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.processing_status}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.region}</td>
                <td className="py-3 px-4 text-zinc-500 font-normal text-xs">{formatTime(row.published_at ?? row.fetched_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </Panel>
  );
}

function AlertsTable({
  rows,
  compact = false,
  error,
  retry,
}: {
  rows: AlertDecision[];
  compact?: boolean;
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "sent",
    direction: "desc",
  });

  if (error) {
    return <SectionError title="Alert decisions unavailable" message={error} retry={retry} />;
  }

  if (sortedRows.length === 0) {
    return (
      <EmptyState
        icon={Bell}
        title="No alert decisions yet"
        body="Alert decisions will appear after scored events cross alert or digest thresholds."
        action={
          <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
            <RefreshCcw className="h-4 w-4" />
            Refresh
          </button>
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="table w-full">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
            <SortableHeader
              label="Decision"
              sortKey="decision"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            <SortableHeader
              label="Event"
              sortKey="event_headline"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
            {!compact ? (
              <SortableHeader
                label="Channel"
                sortKey="channel"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
            ) : null}
            <SortableHeader
              label="Sent"
              sortKey="sent"
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              onSort={requestSort}
            />
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/40">
          {sortedRows.map((row) => (
            <tr key={row.id} className="border-b border-zinc-800/30">
              <td className="py-3 px-4">
                <span className={classNames(
                  "px-2 py-0.5 rounded text-xs font-bold uppercase whitespace-nowrap",
                  row.decision === "immediate_alert" ? "bg-red-500/10 text-red-400 border border-red-500/20" : "bg-zinc-800 text-zinc-400"
                )}>
                  {row.decision.replace("_", " ")}
                </span>
              </td>
              <td className="py-3 px-4 max-w-[460px] whitespace-normal text-sm font-semibold text-zinc-200">
                {row.event?.headline ?? row.reason}
              </td>
              {!compact ? <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.channel ?? "-"}</td> : null}
              <td className="py-3 px-4 text-zinc-500 font-normal text-xs">{formatTime(row.sent_at ?? row.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourcesTable({
  rows,
  error,
  reload,
}: {
  rows: Source[];
  error?: string;
  reload: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "name",
    direction: "asc",
  });

  async function toggle(row: Source) {
    await api.setSourceEnabled(row.id, !row.enabled);
    await reload();
  }
  return (
    <Panel title="Sources">
      {error ? (
        <SectionError title="Sources unavailable" message={error} retry={reload} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Radio}
          title="No sources configured"
          body="Source configuration will appear here after feed sources are added to the shared database."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void reload()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
      <div className="overflow-x-auto">
        <table className="table w-full">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
              <SortableHeader
                label="Name"
                sortKey="name"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Region"
                sortKey="region"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Category"
                sortKey="category"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Score"
                sortKey="source_score"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Interval"
                sortKey="polling_interval_seconds"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Enabled"
                sortKey="enabled"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/40">
            {sortedRows.map((row) => (
              <tr key={row.id} className="border-b border-zinc-800/30">
                <td className="py-3 px-4 text-sm font-semibold text-zinc-200">{row.name}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.region}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.category}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.source_score}</td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.polling_interval_seconds}s</td>
                <td className="py-3 px-4"><input className="toggle toggle-sm" checked={row.enabled} onChange={() => void toggle(row)} type="checkbox" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </Panel>
  );
}

function WatchlistTable({
  rows,
  error,
  retry,
}: {
  rows: WatchlistEntry[];
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "symbol",
    direction: "asc",
  });

  return (
    <Panel title="Watchlist">
      {error ? (
        <SectionError title="Watchlist unavailable" message={error} retry={retry} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Star}
          title="No watchlist entries yet"
          body="Tracked assets and entities will appear here after they are added through CLI or Phase 2 configuration UI."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
      <>
      <div className="flex items-center justify-between border-b border-zinc-800/40 pb-3 mb-4 text-xs text-zinc-500">
        <span>{sortedRows.length} assets watched</span>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-zinc-500">Sort by:</span>
          <button
            onClick={() => requestSort("symbol")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "symbol" && "text-primary font-semibold"
            )}
            type="button"
          >
            Symbol
            {sortConfig.key === "symbol" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
          <button
            onClick={() => requestSort("name")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "name" && "text-primary font-semibold"
            )}
            type="button"
          >
            Name
            {sortConfig.key === "name" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
          <button
            onClick={() => requestSort("tier")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "tier" && "text-primary font-semibold"
            )}
            type="button"
          >
            Tier
            {sortConfig.key === "tier" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sortedRows.map((row) => (
          <div key={row.id} className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4 transition-all duration-150 hover:border-zinc-700/80">
            <div className="flex items-center justify-between">
              <div className="text-base font-bold text-zinc-100">{row.symbol ?? row.name}</div>
              <Badge tone={row.enabled ? "success" : "neutral"}>{row.tier}</Badge>
            </div>
            <div className="mt-1.5 text-sm text-base-content/75">{row.name}</div>
            <div className="mt-2.5 text-xs text-base-content/60">{row.region ?? "global"} · {row.asset_class ?? row.entity_type}</div>
          </div>
        ))}
      </div>
      </>
      )}
    </Panel>
  );
}

function CommandsTable({
  rows,
  compact = false,
  error,
  retry,
  queue,
}: {
  rows: BotCommand[];
  compact?: boolean;
  error?: string;
  retry: () => Promise<void>;
  queue: (type: string, payload: Record<string, unknown>) => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "created_at",
    direction: "desc",
  });

  if (error) {
    return <SectionError title="Command queue unavailable" message={error} retry={retry} />;
  }

  return (
    <div className="space-y-3">
      {!compact ? (
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-sm btn-primary" onClick={() => queue("pipeline.run", { dry_run: true })} type="button">Dry-run pipeline</button>
          <button className="btn btn-sm btn-outline" onClick={() => queue("retention.preview", {})} type="button">Preview retention</button>
        </div>
      ) : null}
      {sortedRows.length === 0 ? (
        <EmptyState
          icon={TerminalSquare}
          title="No commands queued"
          body="Manual bot commands will appear here after an operator queues one."
          action={
            compact ? null : (
              <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
                <RefreshCcw className="h-4 w-4" />
                Refresh
              </button>
            )
          }
        />
      ) : (
      <div className="overflow-x-auto">
        <table className="table w-full">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
              <SortableHeader
                label="Command"
                sortKey="command_type"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Status"
                sortKey="status"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              <SortableHeader
                label="Created"
                sortKey="created_at"
                currentSortKey={sortConfig.key}
                direction={sortConfig.direction}
                onSort={requestSort}
              />
              {!compact ? (
                <SortableHeader
                  label="Payload"
                  sortKey="payload"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
              ) : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/40">
            {sortedRows.map((row) => (
              <tr key={row.id} className="border-b border-zinc-800/30">
                <td className="py-3 px-4 text-sm font-semibold text-zinc-200">{row.command_type}</td>
                <td className="py-3 px-4 text-xs">
                  <Badge tone={row.status === "failed" ? "error" : row.status === "succeeded" ? "success" : "info"}>{row.status}</Badge>
                </td>
                <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{formatTime(row.created_at)}</td>
                {!compact ? <td className="py-3 px-4 text-zinc-400 font-normal text-xs max-w-[360px] truncate">{JSON.stringify(row.payload)}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
}

function JobsTable({
  rows,
  error,
  retry,
}: {
  rows: JobRun[];
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "started_at",
    direction: "desc",
  });

  if (error) {
    return <SectionError title="Job history unavailable" message={error} retry={retry} />;
  }

  if (sortedRows.length === 0) {
    return (
      <EmptyState
        icon={Activity}
        title="No job runs yet"
        body="Pipeline and maintenance job runs will appear after the bot records activity."
        action={
          <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
            <RefreshCcw className="h-4 w-4" />
            Refresh
          </button>
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b border-zinc-800/40 pb-2 text-xs text-zinc-500">
        <span>Job Name</span>
        <div className="flex items-center gap-3">
          <button
            onClick={() => requestSort("job_name")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "job_name" && "text-primary font-semibold"
            )}
            type="button"
          >
            Name
            {sortConfig.key === "job_name" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
          <button
            onClick={() => requestSort("status")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "status" && "text-primary font-semibold"
            )}
            type="button"
          >
            Status
            {sortConfig.key === "status" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
          <button
            onClick={() => requestSort("started_at")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "started_at" && "text-primary font-semibold"
            )}
            type="button"
          >
            Time
            {sortConfig.key === "started_at" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
        </div>
      </div>
      <div className="space-y-2.5">
        {sortedRows.map((row) => (
          <div key={row.id} className="flex items-center justify-between gap-3 text-sm py-1 border-b border-zinc-800/30 last:border-0">
            <div className="flex flex-col">
              <span className="font-semibold text-zinc-200">{row.job_name}</span>
              {row.started_at && (
                <span className="text-[10px] text-zinc-500 mt-0.5">
                  {formatTime(row.started_at)}
                </span>
              )}
            </div>
            <span className="flex items-center gap-2">
              <Badge tone={row.status === "success" ? "success" : "error"}>{row.status}</Badge>
              <ChevronRight className="h-4 w-4 text-base-content/50" />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Operations({
  jobs,
  alerts,
  sources,
  errors,
  queue,
  retry,
}: {
  jobs: JobRun[];
  alerts: AlertDecision[];
  sources: Source[];
  errors: ResourceErrors;
  queue: (type: string, payload: Record<string, unknown>) => Promise<void>;
  retry: () => Promise<void>;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Job history"><JobsTable rows={jobs} error={errors.jobs} retry={retry} /></Panel>
      <Panel title="Alert operations">
        {errors.alerts ? (
          <SectionError title="Alert operations unavailable" message={errors.alerts} retry={retry} />
        ) : (
          <div className="space-y-2">
            <button className="btn btn-sm btn-outline w-full justify-start" onClick={() => queue("alert.dispatch", { channel: "telegram", limit: 20, dry_run: true })} type="button">Dry-run dispatch</button>
            <div className="text-sm text-base-content/60">{alerts.length} recent alert decisions</div>
          </div>
        )}
      </Panel>
      <Panel title="Source actions">
        {errors.sources ? (
          <SectionError title="Source actions unavailable" message={errors.sources} retry={retry} />
        ) : sources.length === 0 ? (
          <EmptyState
            icon={Radio}
            title="No source actions available"
            body="Fetch controls appear after sources are configured."
          />
        ) : (
          <div className="space-y-2">
            {sources.slice(0, 6).map((source) => (
              <button key={source.id} className="btn btn-sm btn-ghost w-full justify-between text-sm" onClick={() => queue("source.fetch", { source_id: source.id })} type="button">
                <span>{source.name}</span><Radio className="h-4 w-4" />
              </button>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-base-200 py-1">
      <span className="text-base-content/60">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}
