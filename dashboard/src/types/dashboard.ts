import type {
  AlertPolicy,
  AlertDecision,
  AlertChannel,
  AlertSuppressionRule,
  BotCommand,
  BotStatus,
  ConfigurationPresets,
  EventCluster,
  EventDetail,
  JobRun,
  NewsDetail,
  NewsItem,
  Source,
  SourceHealth,
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
  sourceHealth: SourceHealth[];
  events: EventCluster[];
  eventsTotal: number;
  eventDetails: Record<string, EventDetail>;
  news: NewsItem[];
  newsTotal: number;
  newsDomains: string[];
  newsFilterOptions: {
    statuses: string[];
    regions: string[];
  };
  newsDetails: Record<string, NewsDetail>;
  alerts: AlertDecision[];
  alertsTotal: number;
  alertDetails: Record<string, AlertDecision>;
  alertChannels: AlertChannel[];
  alertSuppressionRules: AlertSuppressionRule[];
  jobs: JobRun[];
  watchlist: WatchlistEntry[];
  commands: BotCommand[];
  alertPolicy: AlertPolicy | null;
  presets: ConfigurationPresets | null;
};

export type ResourceKey =
  | "status"
  | "sources"
  | "sourceHealth"
  | "events"
  | "eventDetail"
  | "news"
  | "newsDomains"
  | "newsFilterOptions"
  | "newsDetail"
  | "alerts"
  | "alertDetail"
  | "alertChannels"
  | "alertSuppressionRules"
  | "jobs"
  | "watchlist"
  | "commands"
  | "alertPolicy"
  | "presets";

export type ResourceErrors = Partial<Record<ResourceKey, string>>;

export type QueueCommand = (type: string, payload: Record<string, unknown>) => Promise<void>;
