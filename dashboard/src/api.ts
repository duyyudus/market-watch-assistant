export function defaultApiBaseUrl(protocol: string, hostname: string): string {
  return `${protocol}//${hostname || "localhost"}:8000`;
}

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  defaultApiBaseUrl(window.location.protocol, window.location.hostname);

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
  created_at?: string | null;
  event?: { id: string; headline: string; final_score?: number; status?: string } | null;
  latest_delivery_status?: string | null;
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
};

export type BotCommand = {
  id: string;
  command_type: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  payload: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at?: string | null;
};

export type BotStatus = {
  mode: string;
  latest_job: JobRun | null;
  latest_job_available?: boolean;
  pending_commands: number;
  running_commands: number;
  command_queue_available?: boolean;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
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
  createCommand: (command_type: string, payload: Record<string, unknown>) =>
    request<BotCommand>("/bot/commands", {
      method: "POST",
      body: JSON.stringify({ command_type, payload }),
    }),
  setSourceEnabled: (id: string, enabled: boolean) =>
    request<Source>(`/sources/${id}/${enabled ? "enable" : "disable"}`, { method: "POST" }),
};
