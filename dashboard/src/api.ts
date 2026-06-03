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
  auto_quality_score?: number | null;
  quality_metrics?: Record<string, unknown> | null;
  quality_calculated_at?: string | null;
  effective_source_score?: number | null;
};

export type SourceHealth = {
  source_id: string;
  name: string;
  enabled: boolean;
  category: string;
  region: string;
  health_status: "healthy" | "degraded" | "failing";
  latest_status?: string | null;
  last_fetched_at?: string | null;
  consecutive_failure_count: number;
  average_latency_ms?: number | null;
  daily_item_counts: Array<{ date: string; count: number }>;
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

export type EventTimelineItem = {
  news_item_id: string;
  title: string;
  source_name: string;
  source_score: number;
  url: string;
  published_at?: string | null;
  fetched_at?: string | null;
  added_at?: string | null;
  relation_type: string;
  similarity_score?: number | null;
};

export type EventMarketMove = {
  id: string;
  asset_symbol: string;
  asset_class: string;
  exchange?: string | null;
  timestamp: string;
  window: string;
  price_change_pct: number;
  volume_change_pct?: number | null;
  value_traded_change_pct?: number | null;
  z_score?: number | null;
};

export type EventLLMRun = {
  id: string;
  provider: string;
  model: string;
  prompt_version: string;
  result?: Record<string, any> | null;
  status: string;
  error_message?: string | null;
  usage?: Record<string, any> | null;
  created_at: string;
  updated_at?: string | null;
};

export type EventScoreHistoryItem = {
  id: string;
  event_cluster_id: string;
  score_breakdown: Record<string, any>;
  final_score: number;
  created_at: string;
};

export type EventDetail = EventCluster & {
  top_source_score: number;
  confirmation_score: number;
  novelty_score: number;
  urgency_score: number;
  market_impact_score: number;
  relevance_score: number;
  first_seen_at?: string | null;
  latest_investigation?: {
    id: string;
    status: string;
    trigger_reason?: string | null;
    result?: Record<string, any> | null;
    evidence?: Array<Record<string, any>>;
    error_message?: string | null;
    created_at?: string | null;
  } | null;
  score_history: EventScoreHistoryItem[];
  timeline: EventTimelineItem[];
  llm_runs: EventLLMRun[];
  market_moves: EventMarketMove[];
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
  score_breakdown: Record<string, any>;
  channel?: string | null;
  sent_at?: string | null;
  acknowledged_at?: string | null;
  suppression_reason?: string | null;
  created_at?: string | null;
  event?: { id: string; headline: string; final_score?: number; status?: string } | null;
  latest_delivery_status?: string | null;
  latest_delivery_error?: string | null;
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

export type LLMCostBucket = {
  date: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
};

export type LLMCostBreakdown = {
  model?: string | null;
  analysis_type?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
};

export type LLMCostSummary = {
  daily: LLMCostBucket[];
  weekly: LLMCostBucket;
  by_model: LLMCostBreakdown[];
  by_analysis_type: LLMCostBreakdown[];
};

export type PipelineStageMetric = {
  stage_name: string;
  start_time?: string | null;
  end_time?: string | null;
  duration_ms: number;
  items_in?: number | null;
  items_out?: number | null;
  status: string;
};

export type SlowPipelineStage = {
  stage_name: string;
  duration_ms: number;
  average_duration_ms: number;
  threshold_ms: number;
};

export type PipelineMetricsRun = {
  job_run_id: string;
  started_at?: string | null;
  completed_at?: string | null;
  status: string;
  duration_ms: number;
  stages: PipelineStageMetric[];
  slow_stages: SlowPipelineStage[];
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

export function eventStreamUrl(): string {
  return `${API_BASE_URL}/events/stream`;
}

export function buildMaintenanceLLMCostsPath(): string {
  return "/maintenance/llm-costs";
}

export function buildMaintenancePipelineMetricsPath(limit?: number, offset?: number): string {
  return `/maintenance/pipeline-metrics?limit=${limit || 20}&offset=${offset || 0}`;
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
  sourceHealth: () => request<ListEnvelope<SourceHealth>>("/sources/health"),
  events: () => request<ListEnvelope<EventCluster>>("/events?limit=100"),
  event: (id: string) => request<EventDetail>(`/events/${id}`),
  news: () => request<ListEnvelope<NewsItem>>("/news?limit=100"),
  alerts: () => request<ListEnvelope<AlertDecision>>("/alerts?limit=100"),
  alert: (id: string) => request<AlertDecision>(`/alerts/${id}`),
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
  maintenanceLLMCosts: () => request<LLMCostSummary>(buildMaintenanceLLMCostsPath()),
  maintenancePipelineMetrics: (limit?: number, offset?: number) =>
    request<ListEnvelope<PipelineMetricsRun>>(
      buildMaintenancePipelineMetricsPath(limit, offset),
    ),
  maintenanceRetentionJobs: (limit?: number, offset?: number) =>
    request<ListEnvelope<RetentionJob>>(`/maintenance/retention-jobs?limit=${limit || 100}&offset=${offset || 0}`),
};
