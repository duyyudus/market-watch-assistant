import type {
  AlertPolicy,
  AlertDecision,
  BotCommand,
  BotStatus,
  ConfigurationPresets,
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
  | "operations"
  | "maintenance";


export type DashboardState = {
  status: BotStatus | null;
  sources: Source[];
  events: EventCluster[];
  news: NewsItem[];
  alerts: AlertDecision[];
  jobs: JobRun[];
  watchlist: WatchlistEntry[];
  commands: BotCommand[];
  alertPolicy: AlertPolicy | null;
  presets: ConfigurationPresets | null;
};

export type ResourceKey =
  | "status"
  | "sources"
  | "events"
  | "news"
  | "alerts"
  | "jobs"
  | "watchlist"
  | "commands"
  | "alertPolicy"
  | "presets";

export type ResourceErrors = Partial<Record<ResourceKey, string>>;

export type QueueCommand = (type: string, payload: Record<string, unknown>) => Promise<void>;
