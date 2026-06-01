export function defaultApiBaseUrl(protocol: string, hostname: string): string {
  return `${protocol}//${hostname || "localhost"}:8000`;
}

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  defaultApiBaseUrl(window.location.protocol, window.location.hostname);
const API_AUTH_TOKEN = import.meta.env.VITE_API_AUTH_TOKEN;

export type ListEnvelope<T> = {
  items: T[];
  total: number;
};

export type Source = {
  id: string;
  name: string;
  source_type: string;
  category: string;
  region: string;
  url: string;
  language: string;
  enabled: boolean;
  polling_interval_seconds: number;
  source_score: number;
};

export type SourcePayload = {
  name: string;
  url: string;
  source_type: string;
  category: string;
  region: string;
  language: string;
  source_score: number;
  polling_interval_seconds: number;
  enabled: boolean;
};

export type EventCluster = {
  id: string;
  canonical_headline: string;
  summary?: string | null;
  status: string;
  regions: string[];
  asset_classes: string[];
  affected_entities: string[];
  affected_tickers: string[];
  source_count: number;
  final_score: number;
  alert_level?: string | null;
  last_updated_at?: string | null;
  latest_alert?: AlertDecision | null;
  latest_investigation?: { id: string; status: string; result?: unknown } | null;
};

export type NewsItem = {
  id: string;
  title: string;
  source_name: string;
  source_type: string;
  source_score: number;
  region: string;
  asset_classes: string[];
  processing_status: string;
  published_at?: string | null;
  fetched_at?: string | null;
};

export type AlertDecision = {
  id: string;
  event_cluster_id: string;
  decision: string;
  reason: string;
  channel?: string | null;
  sent_at?: string | null;
  acknowledged_at?: string | null;
  suppression_reason?: string | null;
  created_at?: string | null;
  event?: { id: string; headline: string; final_score?: number; status?: string } | null;
  latest_delivery_status?: string | null;
};

export type AlertChannel = {
  id: string;
  name: string;
  channel_type: string;
  config: Record<string, unknown>;
  enabled: boolean;
  is_default: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AlertChannelPayload = {
  name: string;
  channel_type: string;
  config: Record<string, unknown>;
  enabled: boolean;
  is_default: boolean;
};

export type AlertSuppressionRule = {
  id: string;
  name: string;
  rule_type: string;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AlertSuppressionRulePayload = {
  name: string;
  rule_type: string;
  config: Record<string, unknown>;
  enabled: boolean;
};

export type JobRun = {
  id: string;
  job_name: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
};

export type WatchlistEntry = {
  id: string;
  symbol?: string | null;
  name: string;
  entity_type: string;
  tier: string;
  region?: string | null;
  asset_class?: string | null;
  aliases: string[];
  enabled: boolean;
};

export type WatchlistPayload = {
  symbol?: string | null;
  name: string;
  entity_type: string;
  tier: string;
  region?: string | null;
  asset_class?: string | null;
  aliases: string[];
  enabled: boolean;
};

export type AlertPolicy = {
  immediate_threshold: number;
  watchlist_threshold: number;
  digest_threshold: number;
  default_channel: string;
};

export type AlertPresetItem = {
  type: string;
  placeholder: string;
  template: Record<string, any>;
  description: string;
  parameters: Record<string, string>;
};

export type ConfigurationPresets = {
  sources: {
    source_types: string[];
    regions: string[];
    categories: string[];
    languages: string[];
  };
  watchlist: {
    entity_types: string[];
    tiers: string[];
    regions: string[];
    asset_classes: string[];
  };
  alerts: {
    channels: AlertPresetItem[];
    rules: AlertPresetItem[];
  };
};

export type BotCommand = {
  id: string;
  command_type: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  payload: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  requested_by?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type BotStatus = {
  mode: string;
  latest_job: JobRun | null;
  latest_job_available?: boolean;
  pending_commands: number;
  running_commands: number;
  command_queue_available?: boolean;
};

export type FetchLog = {
  id: string;
  source_id: string;
  fetched_at: string;
  status: string;
  http_status?: number | null;
  error_message?: string | null;
  item_count?: number | null;
  duration_ms: number;
  content_hash?: string | null;
};

export type ScoreHistory = {
  id: string;
  event_cluster_id: string;
  score_breakdown: Record<string, any>;
  final_score: number;
  created_at: string;
};

export type CatalystReview = {
  id: string;
  asset_symbol: string;
  asset_class: string;
  move_window: string;
  price_change_pct: number;
  volume_change_pct?: number | null;
  detected_event_cluster_id?: string | null;
  status: string;
  agent_summary?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type EmbeddingStats = {
  total_news_items: number;
  news_items_with_embeddings: number;
  embedding_coverage_pct: number;
  total_event_clusters: number;
  event_clusters_with_embeddings: number;
  cluster_embedding_coverage_pct: number;
  news_providers: string[];
  news_models: string[];
  cluster_providers: string[];
  cluster_models: string[];
};

export type LLMRun = {
  id: string;
  target_type: string;
  target_id: string;
  provider: string;
  model: string;
  prompt_version: string;
  prompt_hash: string;
  input_snapshot: Record<string, any>;
  result?: Record<string, any> | null;
  status: string;
  error_message?: string | null;
  usage?: {
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    total_tokens?: number | null;
    [key: string]: any;
  } | null;
  created_at: string;
  updated_at?: string | null;
};

export type RetentionJob = {
  id: string;
  status: string;
  deleted_counts: Record<string, number>;
  started_at: string;
  completed_at?: string | null;
};

export function normalizeListResponse<T>(value: unknown): ListEnvelope<T> {
  if (Array.isArray(value)) {
    return { items: value as T[], total: value.length };
  }
  const envelope = value as Partial<ListEnvelope<T>>;
  return {
    items: envelope.items ?? [],
    total: envelope.total ?? envelope.items?.length ?? 0,
  };
}

export function buildRequestHeaders(token: string | undefined): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { ...buildRequestHeaders(API_AUTH_TOKEN), ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  botStatus: () => request<BotStatus>("/bot/status"),
  sources: () => request<ListEnvelope<Source>>("/sources"),
  events: () => request<ListEnvelope<EventCluster>>("/events?limit=100"),
  event: (id: string) => request<EventCluster>(`/events/${id}`),
  news: () => request<ListEnvelope<NewsItem>>("/news?limit=100"),
  alerts: () => request<ListEnvelope<AlertDecision>>("/alerts?limit=100"),
  alertChannels: () => request<ListEnvelope<AlertChannel>>("/alert-channels"),
  alertSuppressionRules: () =>
    request<ListEnvelope<AlertSuppressionRule>>("/alert-suppression-rules"),
  jobs: () => request<ListEnvelope<JobRun>>("/jobs/runs?limit=50"),
  watchlist: () => request<ListEnvelope<WatchlistEntry>>("/watchlist"),
  alertPolicy: () => request<AlertPolicy>("/settings/alert-policy"),
  presets: () => request<ConfigurationPresets>("/settings/presets"),
  commands: () => request<ListEnvelope<BotCommand>>("/bot/commands"),
  createSource: (payload: SourcePayload) =>
    request<Source>("/sources", { method: "POST", body: JSON.stringify(payload) }),
  updateSource: (id: string, payload: SourcePayload) =>
    request<Source>(`/sources/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  createWatchlistEntry: (payload: WatchlistPayload) =>
    request<WatchlistEntry>("/watchlist", { method: "POST", body: JSON.stringify(payload) }),
  updateWatchlistEntry: (id: string, payload: WatchlistPayload) =>
    request<WatchlistEntry>(`/watchlist/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteWatchlistEntry: (id: string) => request<void>(`/watchlist/${id}`, { method: "DELETE" }),
  updateAlertPolicy: (payload: AlertPolicy) =>
    request<AlertPolicy>("/settings/alert-policy", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  createAlertChannel: (payload: AlertChannelPayload) =>
    request<AlertChannel>("/alert-channels", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateAlertChannel: (id: string, payload: Partial<AlertChannelPayload>) =>
    request<AlertChannel>(`/alert-channels/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteAlertChannel: (id: string) =>
    request<void>(`/alert-channels/${id}`, { method: "DELETE" }),
  testAlertChannel: (id: string, message: string) =>
    request<BotCommand>(`/alert-channels/${id}/test`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  createAlertSuppressionRule: (payload: AlertSuppressionRulePayload) =>
    request<AlertSuppressionRule>("/alert-suppression-rules", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateAlertSuppressionRule: (id: string, payload: Partial<AlertSuppressionRulePayload>) =>
    request<AlertSuppressionRule>(`/alert-suppression-rules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteAlertSuppressionRule: (id: string) =>
    request<void>(`/alert-suppression-rules/${id}`, { method: "DELETE" }),
  acknowledgeAlert: (id: string) =>
    request<AlertDecision>(`/alerts/${id}/acknowledge`, { method: "POST" }),
  dismissAlert: (id: string) =>
    request<AlertDecision>(`/alerts/${id}/dismiss`, { method: "POST" }),
  createCommand: (command_type: string, payload: Record<string, unknown>) =>
    request<BotCommand>("/bot/commands", {
      method: "POST",
      body: JSON.stringify({ command_type, payload }),
    }),
  setSourceEnabled: (id: string, enabled: boolean) =>
    request<Source>(`/sources/${id}/${enabled ? "enable" : "disable"}`, { method: "POST" }),
  cancelCommand: (id: string) =>
    request<BotCommand>(`/bot/commands/${id}/cancel`, { method: "POST" }),
  maintenanceFetchLogs: (limit?: number, offset?: number) =>
    request<ListEnvelope<FetchLog>>(`/maintenance/fetch-logs?limit=${limit || 100}&offset=${offset || 0}`),
  maintenanceScoreHistory: (limit?: number, offset?: number) =>
    request<ListEnvelope<ScoreHistory>>(`/maintenance/score-history?limit=${limit || 100}&offset=${offset || 0}`),
  maintenanceCatalysts: (limit?: number, offset?: number) =>
    request<ListEnvelope<CatalystReview>>(`/maintenance/catalysts?limit=${limit || 100}&offset=${offset || 0}`),
  maintenanceEmbeddingStats: () =>
    request<EmbeddingStats>("/maintenance/embeddings/stats"),
  maintenanceLLMRuns: (limit?: number, offset?: number) =>
    request<ListEnvelope<LLMRun>>(`/maintenance/llm-runs?limit=${limit || 100}&offset=${offset || 0}`),
  maintenanceRetentionJobs: (limit?: number, offset?: number) =>
    request<ListEnvelope<RetentionJob>>(`/maintenance/retention-jobs?limit=${limit || 100}&offset=${offset || 0}`),
};
