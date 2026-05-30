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

export type View =
  | "overview"
  | "events"
  | "news"
  | "alerts"
  | "sources"
  | "watchlist"
  | "commands"
  | "operations";

export type DashboardState = {
  status: BotStatus | null;
  sources: Source[];
  events: EventCluster[];
  news: NewsItem[];
  alerts: AlertDecision[];
  jobs: JobRun[];
  watchlist: WatchlistEntry[];
  commands: BotCommand[];
};

export type ResourceKey =
  | "status"
  | "sources"
  | "events"
  | "news"
  | "alerts"
  | "jobs"
  | "watchlist"
  | "commands";

export type ResourceErrors = Partial<Record<ResourceKey, string>>;

export type QueueCommand = (type: string, payload: Record<string, unknown>) => Promise<void>;

