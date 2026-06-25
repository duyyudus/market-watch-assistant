import type {
  AlertPolicy,
  AlertDecision,
  AlertChannel,
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
  NewsItem,
  Source,
  SourceHealth,
  WatchlistEntry,
  WatchlistSpotlightItem,
} from "../api";

export type View =
  | "overview"
  | "events"
  | "news"
  | "alerts"
  | "sources"
  | "watchlist"
  | "commands"
  | "maintenance";


export type DashboardState = {
  status: BotStatus | null;
  sources: Source[];
  sourceHealth: SourceHealth[];
  events: EventCluster[];
  eventsTotal: number;
  eventDetails: Record<string, EventDetail>;
  overviewSegments: Record<string, { items: EventCluster[]; total: number }>;
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
  // Dedicated recent-immediate-alert feed for the overview "Needs you now" panel,
  // fetched independently of the Alerts-tab pagination/filter state.
  overviewAlerts: AlertDecision[];
  alertDetails: Record<string, AlertDecision>;
  alertChannels: AlertChannel[];
  alertSuppressionRules: AlertSuppressionRule[];
  jobs: JobRun[];
  watchlist: WatchlistEntry[];
  watchlistSpotlight: WatchlistSpotlightItem[];
  commands: BotCommand[];
  catalystReviews: CatalystReview[];
  catalystReviewsTotal: number;
  latestDigest: Digest | null;
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
  | "overviewAlerts"
  | "alertDetail"
  | "alertChannels"
  | "alertSuppressionRules"
  | "jobs"
  | "watchlist"
  | "watchlistSpotlight"
  | "commands"
  | "catalysts"
  | "digestLatest"
  | "alertPolicy"
  | "presets";

export type ResourceErrors = Partial<Record<ResourceKey, string>>;

export type QueueCommand = (
  type: string,
  payload: Record<string, unknown>,
  options?: { navigate?: boolean },
) => Promise<BotCommand | null>;

export type TrackCommand = (command: BotCommand) => void;
