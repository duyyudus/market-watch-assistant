import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App, compareValues } from "./App";

const apiMock = vi.hoisted(() => ({
  botStatus: vi.fn(),
  sources: vi.fn(),
  events: vi.fn(),
  event: vi.fn(),
  news: vi.fn(),
  newsDomains: vi.fn(),
  newsFilterOptions: vi.fn(),
  newsDetail: vi.fn(),
  alerts: vi.fn(),
  alert: vi.fn(),
  sourceHealth: vi.fn(),
  alertChannels: vi.fn(),
  alertSuppressionRules: vi.fn(),
  createAlertChannel: vi.fn(),
  updateAlertChannel: vi.fn(),
  deleteAlertChannel: vi.fn(),
  testAlertChannel: vi.fn(),
  createAlertSuppressionRule: vi.fn(),
  updateAlertSuppressionRule: vi.fn(),
  deleteAlertSuppressionRule: vi.fn(),
  acknowledgeAlert: vi.fn(),
  dismissAlert: vi.fn(),
  jobs: vi.fn(),
  watchlist: vi.fn(),
  commands: vi.fn(),
  createCommand: vi.fn(),
  cancelCommand: vi.fn(),
  setSourceEnabled: vi.fn(),
  setAllSourcesEnabled: vi.fn(),
  createSource: vi.fn(),
  updateSource: vi.fn(),
  previewSource: vi.fn(),
  previewSourceArticle: vi.fn(),
  createWatchlistEntry: vi.fn(),
  updateWatchlistEntry: vi.fn(),
  deleteWatchlistEntry: vi.fn(),
  alertPolicy: vi.fn(),
  updateAlertPolicy: vi.fn(),
  presets: vi.fn(),
}));

class MockEventSource {
  static instances: MockEventSource[] = [];

  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private listeners: Record<string, Array<(event: MessageEvent) => void>> = {};
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners[type] = [...(this.listeners[type] ?? []), listener];
  }

  close = vi.fn();

  emit(type: string, data: unknown) {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    for (const listener of this.listeners[type] ?? []) {
      listener(event);
    }
    this.onmessage?.(event);
  }

  error() {
    this.onerror?.(new Event("error"));
  }
}

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    api: apiMock,
  };
});

function envelope<T>(items: T[]) {
  return { items, total: items.length };
}

function mockSuccessfulLoad(overrides: Partial<typeof apiMock> = {}) {
  apiMock.botStatus.mockResolvedValue({
    mode: "shared_database",
    latest_job: {
      id: "job_1",
      job_name: "pipeline",
      status: "success",
      started_at: "2026-05-29T13:00:00Z",
      completed_at: "2026-05-29T13:01:00Z",
      result: null,
      error_message: null,
    },
    latest_job_available: true,
    pending_commands: 0,
    running_commands: 0,
    command_queue_available: true,
  });
  apiMock.sources.mockResolvedValue(
    envelope([
      {
        id: "src_1",
        name: "Federal Reserve",
        source_type: "official",
        category: "global_macro",
        region: "us",
        url: "https://example.com/rss",
        language: "en",
        enabled: true,
        polling_interval_seconds: 900,
        source_score: 100,
      },
    ]),
  );
  apiMock.events.mockResolvedValue(
    envelope([
      {
        id: "evt_1",
        canonical_headline: "Fed signals a slower rate path",
        summary: "Policy makers leaned less hawkish.",
        status: "reported",
        regions: ["us"],
        asset_classes: ["global_macro"],
        affected_entities: ["Federal Reserve"],
        affected_tickers: [],
        source_count: 2,
        final_score: 84,
        alert_level: "immediate_alert",
        last_updated_at: "2026-05-29T13:00:00Z",
      },
    ]),
  );
  apiMock.event.mockImplementation(async (id: string) => {
    if (id === "evt_2") {
      return {
        id: "evt_2",
        canonical_headline: "Treasury yields fall after jobs report",
        summary: "Labor data eased rates pressure.",
        status: "reported",
        regions: ["us"],
        asset_classes: ["rates"],
        affected_entities: ["Treasury"],
        affected_tickers: ["TLT"],
        source_count: 1,
        top_source_score: 75,
        confirmation_score: 60,
        novelty_score: 62,
        urgency_score: 55,
        market_impact_score: 66,
        relevance_score: 70,
        final_score: 61,
        alert_level: "digest_only",
        first_seen_at: "2026-05-29T14:00:00Z",
        last_updated_at: "2026-05-29T14:10:00Z",
        latest_alert: null,
        latest_investigation: null,
        score_history: [],
        timeline: [
          {
            news_item_id: "news_2",
            title: "Treasury yields fall after jobs report",
            source_name: "BLS",
            source_score: 75,
            url: "https://example.com/jobs",
            published_at: "2026-05-29T14:00:00Z",
            fetched_at: "2026-05-29T14:00:00Z",
            added_at: "2026-05-29T14:01:00Z",
            relation_type: "seed",
            similarity_score: 88,
          },
        ],
        llm_runs: [],
        market_moves: [],
      };
    }
    return {
      id: "evt_1",
      canonical_headline: "Fed signals a slower rate path",
      summary: "Policy makers leaned less hawkish.",
      status: "reported",
      regions: ["us"],
      asset_classes: ["global_macro"],
      affected_entities: ["Federal Reserve"],
      affected_tickers: ["SPY"],
      source_count: 2,
      top_source_score: 100,
      confirmation_score: 88,
      novelty_score: 85,
      urgency_score: 80,
      market_impact_score: 72,
      relevance_score: 100,
      final_score: 84,
      alert_level: "immediate_alert",
      first_seen_at: "2026-05-29T13:00:00Z",
      last_updated_at: "2026-05-29T13:10:00Z",
      latest_alert: null,
      latest_investigation: {
        id: "inv_1",
        status: "succeeded",
        result: { suggested_action: "monitor duration exposure" },
      },
      score_history: [
        {
          id: "score_1",
          event_cluster_id: "evt_1",
          final_score: 84,
          score_breakdown: {
            source_score: 100,
            impact_score: 75,
            relevance_score: 100,
            novelty_score: 85,
            urgency_score: 80,
            market_move_score: 72,
            confidence_score: 88,
            duplicate_penalty: 0,
            noise_penalty: 0,
            stale_penalty: 0,
            final_score: 84,
          },
          created_at: "2026-05-29T13:04:00Z",
        },
      ],
      timeline: [
        {
          news_item_id: "news_1",
          title: "Fed signals a slower rate path",
          source_name: "Federal Reserve",
          source_score: 100,
          url: "https://example.com/news",
          published_at: "2026-05-29T13:00:00Z",
          fetched_at: "2026-05-29T13:00:00Z",
          added_at: "2026-05-29T13:01:00Z",
          relation_type: "seed",
          similarity_score: 91,
        },
      ],
      llm_runs: [
        {
          id: "llm_1",
          provider: "openai",
          model: "gpt-4o",
          prompt_version: "1",
          result: { summary: "Less hawkish Fed path." },
          status: "succeeded",
          created_at: "2026-05-29T13:02:00Z",
        },
      ],
      market_moves: [
        {
          id: "move_1",
          asset_symbol: "SPY",
          asset_class: "equity",
          exchange: "NYSE",
          timestamp: "2026-05-29T13:10:00Z",
          window: "1h",
          price_change_pct: 1.7,
          volume_change_pct: 22.5,
        },
      ],
    };
  });
  apiMock.news.mockResolvedValue(
    envelope([
      {
        id: "news_1",
        title: "Fed signals a slower rate path",
        source_name: "Federal Reserve",
        source_type: "official",
        source_score: 100,
        url: "https://www.example.com/news",
        canonical_url: "https://example.com/news",
        region: "us",
        asset_classes: ["global_macro"],
        processing_status: "clustered",
        published_at: "2026-05-29T13:00:00Z",
        fetched_at: "2026-05-29T13:00:00Z",
      },
    ]),
  );
  apiMock.newsDomains.mockResolvedValue({ items: ["example.com", "oil.example.org"], total: 2 });
  apiMock.newsFilterOptions.mockResolvedValue({
    statuses: ["clustered", "new", "normalized"],
    regions: ["global", "us"],
  });
  apiMock.newsDetail.mockResolvedValue({
    id: "news_1",
    source_id: "src_1",
    title: "Fed signals a slower rate path",
    snippet: "Policy makers leaned less hawkish.",
    raw_content: "Full normalized article text.",
    url: "https://www.example.com/news",
    canonical_url: "https://example.com/news",
    source_name: "Federal Reserve",
    source_type: "official",
    source_score: 100,
    published_at: "2026-05-29T13:00:00Z",
    fetched_at: "2026-05-29T13:00:00Z",
    language: "en",
    region: "us",
    asset_classes: ["global_macro"],
    processing_status: "clustered",
    is_paywalled: false,
    full_text_available: true,
    full_text_extraction_status: "success",
    full_text_attempt_count: 1,
    full_text_last_attempted_at: "2026-05-29T13:02:00Z",
    full_text_last_http_status: 200,
    full_text_last_error: null,
    full_text_next_retry_at: null,
    entities: [
      {
        id: "ent_1",
        entity_type: "organization",
        raw_text: "Federal Reserve",
        normalized_name: "Federal Reserve",
        ticker: null,
        exchange: null,
        country: "US",
        confidence: 96,
      },
    ],
    clusters: [
      {
        event_cluster_id: "evt_1",
        relation_type: "seed",
        similarity_score: 91,
        decision_metadata: null,
        added_at: "2026-05-29T13:03:00Z",
      },
    ],
  });
  apiMock.alerts.mockResolvedValue(
    envelope([
      {
        id: "alert_2",
        event_cluster_id: "evt_2",
        decision: "digest_only",
        reason: "score_above_digest_threshold",
        score_breakdown: { final_score: 61, relevance_score: 70 },
        channel: "log",
        sent_at: null,
        created_at: "2026-05-29T14:05:00Z",
        event: { id: "evt_2", headline: "Treasury yields fall after jobs report", final_score: 61 },
        latest_delivery_status: "queued",
        latest_delivery_error: "waiting for digest window",
        acknowledged_at: null,
      },
      {
        id: "alert_1",
        event_cluster_id: "evt_1",
        decision: "immediate_alert",
        reason: "score_above_immediate_threshold",
        score_breakdown: { final_score: 84, relevance_score: 100 },
        channel: "telegram",
        sent_at: "2026-05-29T13:05:00Z",
        created_at: "2026-05-29T13:05:00Z",
        event: { id: "evt_1", headline: "Fed signals a slower rate path", final_score: 84 },
        latest_delivery_status: "sent",
        acknowledged_at: null,
      },
    ]),
  );
  apiMock.alert.mockImplementation(async (id: string) => {
    if (id === "alert_2") {
      return {
        id: "alert_2",
        event_cluster_id: "evt_2",
        decision: "digest_only",
        reason: "score_above_digest_threshold",
        score_breakdown: { final_score: 61, relevance_score: 70 },
        channel: "log",
        sent_at: null,
        created_at: "2026-05-29T14:05:00Z",
        event: {
          id: "evt_2",
          headline: "Treasury yields fall after jobs report",
          final_score: 61,
          status: "reported",
        },
        latest_delivery_status: "queued",
        latest_delivery_error: "waiting for digest window",
        acknowledged_at: null,
      };
    }
    return {
      id: "alert_1",
      event_cluster_id: "evt_1",
      decision: "immediate_alert",
      reason: "score_above_immediate_threshold",
      score_breakdown: { final_score: 84, relevance_score: 100 },
      channel: "telegram",
      sent_at: "2026-05-29T13:05:00Z",
      created_at: "2026-05-29T13:05:00Z",
      event: {
        id: "evt_1",
        headline: "Fed signals a slower rate path",
        final_score: 84,
        status: "reported",
      },
      latest_delivery_status: "sent",
      latest_delivery_error: null,
      acknowledged_at: null,
    };
  });
  apiMock.sourceHealth.mockResolvedValue(
    envelope([
      {
        source_id: "src_1",
        name: "Federal Reserve",
        enabled: true,
        category: "global_macro",
        region: "us",
        health_status: "healthy",
        latest_status: "success",
        last_fetched_at: "2026-05-29T12:55:00Z",
        consecutive_failure_count: 0,
        average_latency_ms: 120,
        daily_item_counts: [{ date: "2026-05-29", count: 5 }],
      },
    ]),
  );
  apiMock.alertChannels.mockResolvedValue(
    envelope([
      {
        id: "chan_1",
        name: "Primary Telegram",
        channel_type: "telegram",
        config: { chat_id: "chat_1" },
        enabled: true,
        is_default: true,
      },
    ]),
  );
  apiMock.alertSuppressionRules.mockResolvedValue(
    envelope([
      {
        id: "rule_1",
        name: "Quiet hours",
        rule_type: "quiet_hours",
        config: { start_hour: 23, end_hour: 7 },
        enabled: true,
      },
    ]),
  );
  apiMock.jobs.mockResolvedValue(
    envelope([
      {
        id: "job_1",
        job_name: "pipeline",
        status: "success",
        started_at: "2026-05-29T13:00:00Z",
        completed_at: "2026-05-29T13:01:00Z",
        result: { clusters: 1 },
        error_message: null,
      },
    ]),
  );
  apiMock.watchlist.mockResolvedValue(
    envelope([
      {
        id: "watch_1",
        symbol: "SPY",
        name: "S&P 500 ETF",
        entity_type: "etf",
        tier: "S",
        region: "us",
        asset_class: "equity",
        aliases: ["SPDR S&P 500"],
        enabled: true,
      },
    ]),
  );
  apiMock.commands.mockResolvedValue(envelope([]));
  apiMock.alertPolicy.mockResolvedValue({
    immediate_threshold: 80,
    watchlist_threshold: 55,
    digest_threshold: 30,
    default_channel: "log",
  });
  apiMock.presets.mockResolvedValue({
    sources: {
      source_types: ["rss", "google-rss", "official"],
      regions: ["global", "us", "vietnam", "crypto"],
      categories: ["global_macro", "crypto", "vietnam_equity"],
      languages: ["en", "vi"],
    },
    watchlist: {
      entity_types: ["equity", "etf", "crypto"],
      tiers: ["S", "A", "B", "C", "D"],
      regions: ["global", "us", "vietnam", "crypto"],
      asset_classes: ["equity", "crypto", "global_macro"],
    },
    alerts: {
      channels: [
        {
          type: "webhook",
          placeholder: "e.g. Discord Webhook Alerts",
          template: { url: "https://hooks.example.test/alert" },
          description: "Submits JSON payloads.",
          parameters: { url: "required" },
        },
      ],
      rules: [
        {
          type: "cooldown",
          placeholder: "e.g. 6-Hour Cooldown",
          template: { hours: 6 },
          description: "Dampens frequent repetitions.",
          parameters: { hours: "required" },
        },
      ],
    },
  });
  apiMock.createSource.mockResolvedValue({
    id: "src_2",
    name: "CoinDesk",
    source_type: "rss",
    category: "crypto",
    region: "global",
    url: "https://example.com/coindesk",
    language: "en",
    enabled: true,
    polling_interval_seconds: 600,
    source_score: 75,
  });
  apiMock.updateSource.mockResolvedValue({
    id: "src_1",
    name: "Federal Reserve Watch",
    source_type: "official",
    category: "rates",
    region: "us",
    url: "https://example.com/rss",
    language: "en",
    enabled: true,
    polling_interval_seconds: 900,
    source_score: 95,
  });
  apiMock.createWatchlistEntry.mockResolvedValue({
    id: "watch_2",
    symbol: "BTC",
    name: "Bitcoin",
    entity_type: "crypto",
    tier: "S",
    region: "global",
    asset_class: "crypto",
    aliases: ["digital gold"],
    enabled: true,
  });
  apiMock.updateWatchlistEntry.mockResolvedValue({
    id: "watch_1",
    symbol: "SPY",
    name: "SPDR S&P 500 ETF",
    entity_type: "etf",
    tier: "A",
    region: "us",
    asset_class: "equity",
    aliases: ["SPDR"],
    enabled: true,
  });
  apiMock.deleteWatchlistEntry.mockResolvedValue(undefined);
  apiMock.cancelCommand.mockResolvedValue({
    id: "cmd_cancelled",
    command_type: "pipeline.run",
    status: "cancelled",
    payload: {},
    created_at: "2026-05-29T13:00:00Z",
  });
  apiMock.updateAlertPolicy.mockResolvedValue({
    immediate_threshold: 85,
    watchlist_threshold: 60,
    digest_threshold: 35,
    default_channel: "telegram",
  });
  apiMock.createAlertChannel.mockResolvedValue({
    id: "chan_2",
    name: "Webhook",
    channel_type: "webhook",
    config: { url: "https://hooks.example.test/alert" },
    enabled: true,
    is_default: false,
  });
  apiMock.testAlertChannel.mockResolvedValue({
    id: "cmd_channel",
    command_type: "alert.test_channel",
    status: "pending",
    payload: { channel_id: "chan_1" },
  });
  apiMock.createAlertSuppressionRule.mockResolvedValue({
    id: "rule_2",
    name: "Cooldown",
    rule_type: "cooldown",
    config: { hours: 6 },
    enabled: true,
  });
  apiMock.acknowledgeAlert.mockResolvedValue({
    id: "alert_1",
    event_cluster_id: "evt_1",
    decision: "immediate_alert",
    reason: "score_above_immediate_threshold",
    channel: "telegram",
    acknowledged_at: "2026-05-29T14:00:00Z",
    event: { id: "evt_1", headline: "Fed signals a slower rate path", final_score: 84 },
  });
  apiMock.dismissAlert.mockResolvedValue({
    id: "alert_1",
    event_cluster_id: "evt_1",
    decision: "immediate_alert",
    reason: "score_above_immediate_threshold",
    suppression_reason: "dismissed",
  });
  Object.assign(apiMock, overrides);
}

async function renderLoadedApp() {
  render(<App />);
  await waitFor(() => expect(apiMock.botStatus).toHaveBeenCalled());
}

function switchTo(view: string) {
  const selectors = screen.getAllByRole("combobox");
  fireEvent.change(selectors[selectors.length - 1], { target: { value: view } });
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("dark"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  mockSuccessfulLoad();
});

describe("App theme", () => {
  it("uses the dark emerald_dark theme", async () => {
    await renderLoadedApp();

    expect(screen.getByTestId("dashboard-root")).toHaveAttribute("data-theme", "emerald_dark");
    expect(document.documentElement).toHaveClass("dark");
  });

  it("persists system theme mode and follows prefers-color-scheme", async () => {
    localStorage.setItem("mw-theme-mode", "system");
    await renderLoadedApp();

    expect(screen.getByTestId("dashboard-root")).toHaveAttribute("data-theme", "emerald_dark");
    fireEvent.click(screen.getByRole("button", { name: /theme/i }));
    fireEvent.click(screen.getByRole("button", { name: /light/i }));

    expect(localStorage.getItem("mw-theme-mode")).toBe("light");
    expect(screen.getByTestId("dashboard-root")).toHaveAttribute("data-theme", "emerald_light");
  });
});

describe("App data states", () => {
  it("loads only overview resources on initial render", async () => {
    await renderLoadedApp();

    expect(apiMock.botStatus).toHaveBeenCalledTimes(1);
    expect(apiMock.events).toHaveBeenCalledTimes(1);
    expect(apiMock.alerts).toHaveBeenCalledTimes(1);
    expect(apiMock.sources).not.toHaveBeenCalled();
    expect(apiMock.news).not.toHaveBeenCalled();
    expect(apiMock.watchlist).not.toHaveBeenCalled();
    expect(apiMock.alertChannels).not.toHaveBeenCalled();
    expect(apiMock.presets).not.toHaveBeenCalled();
  });

  it("renders successful dashboard data", async () => {
    await renderLoadedApp();

    expect(await screen.findAllByText("Fed signals a slower rate path")).not.toHaveLength(0);
    switchTo("sources");
    expect(await screen.findAllByText("Federal Reserve")).not.toHaveLength(0);
    expect(screen.getByText("API ok")).toBeInTheDocument();
  });

  it("refreshes affected resources when live dashboard events arrive", async () => {
    await renderLoadedApp();

    expect(MockEventSource.instances[0].url).toContain("/events/stream");
    apiMock.alerts.mockClear();
    act(() => MockEventSource.instances[0].emit("alert.created", { id: "alert_2" }));

    await waitFor(() => expect(apiMock.alerts).toHaveBeenCalledTimes(1));
  });

  it("shows live update connection errors", async () => {
    await renderLoadedApp();

    act(() => MockEventSource.instances[0].error());

    expect(await screen.findByText(/live updates disconnected/i)).toBeInTheDocument();
  });

  it("renders detailed event timeline scoring analysis and actions", async () => {
    await renderLoadedApp();
    switchTo("events");

    fireEvent.click(await screen.findByTestId("event-card-evt_1"));

    expect(await screen.findByText("Timeline")).toBeInTheDocument();
    expect(screen.getByText("Scoring")).toBeInTheDocument();
    expect(screen.getByText("Market moves")).toBeInTheDocument();
    expect(screen.getByText("Less hawkish Fed path.")).toBeInTheDocument();
    expect(screen.getByText("monitor duration exposure")).toBeInTheDocument();
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("Source")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rescore/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm/i })).toBeInTheDocument();
  });

  it("renders source health subtab and queues source test fetch", async () => {
    apiMock.createCommand.mockResolvedValue({
      id: "cmd_source",
      command_type: "source.fetch",
      status: "pending",
      payload: { source_id: "src_1" },
    });
    await renderLoadedApp();
    switchTo("sources");

    fireEvent.click(await screen.findByRole("button", { name: /health/i }));

    expect(await screen.findByText("healthy")).toBeInTheDocument();
    expect(screen.getByText("120ms avg")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /test fetch Federal Reserve/i }));

    await waitFor(() =>
      expect(apiMock.createCommand).toHaveBeenCalledWith("source.fetch", {
        source_id: "src_1",
      }),
    );
  });

  it("shows failed queued command errors", async () => {
    apiMock.createCommand.mockRejectedValueOnce(new Error("queue offline"));
    await renderLoadedApp();
    switchTo("sources");

    fireEvent.click(await screen.findByRole("button", { name: /health/i }));
    fireEvent.click(await screen.findByRole("button", { name: /test fetch Federal Reserve/i }));

    expect(await screen.findByText("queue offline")).toBeInTheDocument();
  });

  it("renders disabled source health as neutral disabled state", async () => {
    apiMock.sourceHealth.mockResolvedValue(
      envelope([
        {
          source_id: "src_1",
          name: "Federal Reserve",
          enabled: false,
          category: "global_macro",
          region: "us",
          health_status: "disabled",
          latest_status: "success",
          last_fetched_at: "2026-05-29T12:55:00Z",
          consecutive_failure_count: 0,
          average_latency_ms: 120,
          daily_item_counts: [{ date: "2026-05-29", count: 5 }],
        },
      ]),
    );
    await renderLoadedApp();
    switchTo("sources");

    fireEvent.click(await screen.findByRole("button", { name: /health/i }));

    expect(await screen.findAllByText("disabled")).not.toHaveLength(0);
    expect(screen.queryByText("degraded")).not.toBeInTheDocument();
  });

  it("shows source toggle errors", async () => {
    apiMock.setSourceEnabled.mockRejectedValueOnce(new Error("source update failed"));
    await renderLoadedApp();
    switchTo("sources");

    const sourceCard = await screen.findByTestId("source-card-src_1");
    fireEvent.click(within(sourceCard).getByRole("checkbox", { name: /disable Federal Reserve/i }));

    expect(await screen.findByText("source update failed")).toBeInTheDocument();
  });

  it("persists auto refresh preference and reloads on interval", async () => {
    await renderLoadedApp();
    vi.useFakeTimers();

    fireEvent.change(screen.getByLabelText("Auto-refresh"), { target: { value: "30000" } });
    expect(localStorage.getItem("mw-auto-refresh-ms")).toBe("30000");

    apiMock.botStatus.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });

    expect(apiMock.botStatus).toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Auto-refresh"), { target: { value: "0" } });
    vi.useRealTimers();
  });

  it("renders compact card views for responsive event alert and source lists", async () => {
    await renderLoadedApp();

    expect(await screen.findByTestId("event-card-evt_1")).toBeInTheDocument();
    switchTo("alerts");
    expect(await screen.findByTestId("alert-card-alert_1")).toBeInTheDocument();
    switchTo("sources");
    expect(await screen.findByTestId("source-card-src_1")).toBeInTheDocument();
  });

  it("renders empty states instead of blank tables", async () => {
    apiMock.events.mockResolvedValue(envelope([]));
    apiMock.news.mockResolvedValue(envelope([]));

    await renderLoadedApp();

    expect(await screen.findByText("No priority events yet")).toBeInTheDocument();
    switchTo("news");
    expect(screen.getByText("No normalized news yet")).toBeInTheDocument();
  });

  it("loads normalized news with the default limit and fetches selected article detail", async () => {
    await renderLoadedApp();

    switchTo("news");
    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(100, undefined, 0, { status: "normalized" }),
    );
    await waitFor(() => expect(apiMock.newsDomains).toHaveBeenCalled());
    await waitFor(() => expect(apiMock.newsFilterOptions).toHaveBeenCalled());
    expect(await screen.findByRole("option", { name: "oil.example.org" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Federal Reserve · official" })).toBeInTheDocument();

    fireEvent.click(await screen.findByTestId("news-row-news_1"));

    await waitFor(() => expect(apiMock.newsDetail).toHaveBeenCalledWith("news_1"));
    expect(await screen.findByText("Full normalized article text.")).toBeInTheDocument();
  });

  it("reloads normalized news when the fetch limit changes", async () => {
    await renderLoadedApp();

    switchTo("news");
    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(100, undefined, 0, { status: "normalized" }),
    );
    apiMock.news.mockClear();

    fireEvent.change(await screen.findByLabelText("Items per page"), { target: { value: "200" } });

    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(200, undefined, 0, { status: "normalized" }),
    );
  });

  it("loads the next news page using fetch limit as page size", async () => {
    apiMock.news.mockResolvedValue({
      items: [
        {
          id: "news_1",
          title: "Fed signals a slower rate path",
          source_name: "Federal Reserve",
          source_type: "official",
          source_score: 100,
          url: "https://www.example.com/news",
          canonical_url: "https://example.com/news",
          region: "us",
          asset_classes: ["global_macro"],
          processing_status: "clustered",
          published_at: "2026-05-29T13:00:00Z",
          fetched_at: "2026-05-29T13:00:00Z",
        },
      ],
      total: 150,
    });
    await renderLoadedApp();

    switchTo("news");
    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(100, undefined, 0, { status: "normalized" }),
    );
    apiMock.news.mockClear();

    fireEvent.click(await screen.findByRole("button", { name: "Next page" }));

    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(100, undefined, 100, {
        status: "normalized",
      }),
    );
  });

  it("reloads normalized news when source status and region filters change", async () => {
    await renderLoadedApp();

    switchTo("news");
    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(100, undefined, 0, { status: "normalized" }),
    );

    apiMock.news.mockClear();
    fireEvent.change(await screen.findByLabelText("Source"), { target: { value: "src_1" } });
    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(100, undefined, 0, {
        sourceId: "src_1",
        status: "normalized",
      }),
    );

    apiMock.news.mockClear();
    fireEvent.change(await screen.findByLabelText("Status"), { target: { value: "new" } });
    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(100, undefined, 0, {
        sourceId: "src_1",
        status: "new",
      }),
    );

    apiMock.news.mockClear();
    fireEvent.change(await screen.findByLabelText("Region"), { target: { value: "global" } });
    await waitFor(() =>
      expect(apiMock.news).toHaveBeenCalledWith(100, undefined, 0, {
        sourceId: "src_1",
        status: "new",
        region: "global",
      }),
    );
  });

  it("keeps successful pages visible when one endpoint fails", async () => {
    apiMock.news.mockRejectedValue(new Error("news unavailable"));

    await renderLoadedApp();

    switchTo("sources");
    expect(await screen.findAllByText("Federal Reserve")).not.toHaveLength(0);

    switchTo("news");
    expect(await screen.findByText("API degraded")).toBeInTheDocument();
    expect(await screen.findByText("Normalized news unavailable")).toBeInTheDocument();
    expect(screen.getByText("news unavailable")).toBeInTheDocument();
  });

  it("renders Phase 2 watchlist configuration controls", async () => {
    await renderLoadedApp();
    switchTo("watchlist");

    expect(await screen.findByText("SPY")).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(within(main).getByRole("button", { name: /add watchlist entry/i })).toBeInTheDocument();
    expect(within(main).getByRole("button", { name: /edit SPY/i })).toBeInTheDocument();
  });

  it("creates and edits sources from the dashboard", async () => {
    await renderLoadedApp();
    switchTo("sources");
    await screen.findByTestId("source-card-src_1");

    fireEvent.click(screen.getByRole("button", { name: /add source/i }));
    const main = screen.getByRole("main");
    expect(within(main).getByRole("combobox", { name: "Source type" })).toBeInTheDocument();
    expect(within(main).getByRole("combobox", { name: "Region" })).toBeInTheDocument();
    expect(within(main).getByRole("combobox", { name: "Category" })).toBeInTheDocument();
    expect(within(main).getByRole("combobox", { name: "Language" })).toBeInTheDocument();
    expect(within(main).queryByRole("option", { name: "blog" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "CoinDesk" } });
    fireEvent.change(screen.getByLabelText("Source URL"), {
      target: { value: "https://example.com/coindesk" },
    });
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "global" } });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "crypto" } });
    fireEvent.change(screen.getByLabelText("Source score"), { target: { value: "75" } });
    fireEvent.change(screen.getByLabelText("Polling interval"), { target: { value: "600" } });
    fireEvent.click(screen.getByRole("button", { name: /^save source$/i }));

    await waitFor(() =>
      expect(apiMock.createSource).toHaveBeenCalledWith({
        name: "CoinDesk",
        url: "https://example.com/coindesk",
        source_type: "rss",
        category: "crypto",
        region: "global",
        language: "en",
        source_score: 75,
        polling_interval_seconds: 600,
        enabled: true,
      }),
    );

    fireEvent.click(screen.getAllByRole("button", { name: /edit Federal Reserve/i })[0]);
    fireEvent.change(screen.getByLabelText("Source name"), {
      target: { value: "Federal Reserve Watch" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save source$/i }));

    await waitFor(() =>
      expect(apiMock.updateSource).toHaveBeenCalledWith(
        "src_1",
        expect.objectContaining({ name: "Federal Reserve Watch" }),
      ),
    );
  });

  it("previews a new source feed and article text from the create form", async () => {
    apiMock.previewSource.mockResolvedValue({
      status: "success",
      url: "https://example.com/coindesk.xml",
      source_type: "rss",
      http_status: 200,
      duration_ms: 24,
      item_count: 1,
      items: [
        {
          title: "Bitcoin ETF inflows rise",
          url: "https://example.com/bitcoin-etf",
          description: "Fresh inflows hit spot Bitcoin ETFs.",
          published_at: "2026-05-29T13:00:00Z",
          guid: "btc-1",
        },
      ],
    });
    apiMock.previewSourceArticle.mockResolvedValue({
      status: "success",
      url: "https://example.com/bitcoin-etf",
      http_status: 200,
      duration_ms: 31,
      text: "Full article text was extracted from the publisher.",
      text_length: 50,
      truncated: false,
    });

    await renderLoadedApp();
    switchTo("sources");
    await screen.findByTestId("source-card-src_1");

    fireEvent.click(screen.getByRole("button", { name: /add source/i }));
    const previewButton = screen.getByRole("button", { name: /poll preview/i });
    expect(previewButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Source URL"), {
      target: { value: "https://example.com/coindesk.xml" },
    });
    expect(previewButton).not.toBeDisabled();
    fireEvent.click(previewButton);

    await waitFor(() =>
      expect(apiMock.previewSource).toHaveBeenCalledWith({
        url: "https://example.com/coindesk.xml",
        source_type: "rss",
        limit: 10,
      }),
    );
    expect(await screen.findByText("Bitcoin ETF inflows rise")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /preview article Bitcoin ETF inflows rise/i }));
    await waitFor(() =>
      expect(apiMock.previewSourceArticle).toHaveBeenCalledWith({
        url: "https://example.com/bitcoin-etf",
        fallback_snippet: "Fresh inflows hit spot Bitcoin ETFs.",
        fallback_title: "Bitcoin ETF inflows rise",
        source_type: "rss",
        max_chars: 20000,
      }),
    );
    expect(await screen.findByText("Snippet")).toBeInTheDocument();
    expect(await screen.findByText(/Full article text was extracted/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Source URL"), {
      target: { value: "https://example.com/changed.xml" },
    });
    expect(screen.queryByText("Bitcoin ETF inflows rise")).not.toBeInTheDocument();
  });

  it("skips article text preview for google rss sources", async () => {
    apiMock.previewSource.mockResolvedValue({
      status: "success",
      url: "https://example.com/bloomberg.xml",
      source_type: "google-rss",
      http_status: 200,
      duration_ms: 24,
      item_count: 1,
      items: [
        {
          title: "Oil supply shock analysis",
          url: "https://www.bloomberg.com/news/articles/oil-supply-shock",
          description: "",
          published_at: "2026-06-06T13:00:00Z",
          guid: "oil-1",
        },
      ],
    });
    apiMock.previewSourceArticle.mockResolvedValue({
      status: "skipped",
      url: "https://www.bloomberg.com/news/articles/oil-supply-shock",
      http_status: null,
      duration_ms: 31,
      text: "",
      text_length: 0,
      truncated: false,
      error_message: "google_rss_feed_only",
    });

    await renderLoadedApp();
    switchTo("sources");
    await screen.findByTestId("source-card-src_1");

    fireEvent.click(screen.getByRole("button", { name: /add source/i }));
    fireEvent.change(screen.getByLabelText("Source URL"), {
      target: { value: "https://example.com/bloomberg.xml" },
    });
    fireEvent.change(screen.getByLabelText("Source type"), { target: { value: "google-rss" } });
    fireEvent.click(screen.getByRole("button", { name: /poll preview/i }));

    expect(await screen.findByText("Oil supply shock analysis")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /preview article Oil supply shock analysis/i }));
    await waitFor(() =>
      expect(apiMock.previewSourceArticle).toHaveBeenCalledWith({
        url: "https://www.bloomberg.com/news/articles/oil-supply-shock",
        fallback_snippet: "",
        fallback_title: "Oil supply shock analysis",
        source_type: "google-rss",
        max_chars: 20000,
      }),
    );

    expect(await screen.findByText(/google_rss_feed_only/i)).toBeInTheDocument();
    expect(screen.getByText("skipped · HTTP - · 31ms · 0 chars")).toBeInTheDocument();
    expect(screen.getByText("No article text available.")).toBeInTheDocument();
    expect(screen.queryByText(/^Unable to preview article$/i)).not.toBeInTheDocument();
  });

  it("previews an existing source feed and article text from the edit form", async () => {
    apiMock.previewSource.mockResolvedValue({
      status: "success",
      url: "https://example.com/rss",
      source_type: "rss",
      http_status: 200,
      duration_ms: 18,
      item_count: 1,
      items: [
        {
          title: "Fed minutes preview",
          url: "https://example.com/fed-minutes",
          description: "Policy makers discuss rates.",
          published_at: "2026-05-29T13:00:00Z",
          guid: "fed-1",
        },
      ],
    });
    apiMock.previewSourceArticle.mockResolvedValue({
      status: "success",
      url: "https://example.com/fed-minutes",
      http_status: 200,
      duration_ms: 22,
      text: "Existing source article text was extracted.",
      text_length: 43,
      truncated: false,
    });

    await renderLoadedApp();
    switchTo("sources");
    await screen.findByTestId("source-card-src_1");

    fireEvent.click(screen.getAllByRole("button", { name: /edit Federal Reserve/i })[0]);
    fireEvent.change(screen.getByLabelText("Source type"), { target: { value: "rss" } });
    const previewButton = screen.getByRole("button", { name: /poll preview/i });
    expect(previewButton).not.toBeDisabled();
    fireEvent.click(previewButton);

    await waitFor(() =>
      expect(apiMock.previewSource).toHaveBeenCalledWith({
        url: "https://example.com/rss",
        source_type: "rss",
        limit: 10,
      }),
    );
    expect(await screen.findByText("Fed minutes preview")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /preview article Fed minutes preview/i }));
    await waitFor(() =>
      expect(apiMock.previewSourceArticle).toHaveBeenCalledWith({
        url: "https://example.com/fed-minutes",
        fallback_snippet: "Policy makers discuss rates.",
        fallback_title: "Fed minutes preview",
        source_type: "rss",
        max_chars: 20000,
      }),
    );
    expect(await screen.findByText(/Existing source article text was extracted/i)).toBeInTheDocument();
  });

  it("disables all sources from the aggregate source toggle", async () => {
    await renderLoadedApp();
    switchTo("sources");
    await screen.findByTestId("source-card-src_1");

    fireEvent.click(screen.getByRole("checkbox", { name: "All sources" }));

    await waitFor(() => expect(apiMock.setAllSourcesEnabled).toHaveBeenCalledWith(false));
    await waitFor(() => expect(apiMock.sources).toHaveBeenCalledTimes(2));
  });

  it("enables all sources from the aggregate source toggle when some are disabled", async () => {
    apiMock.sources.mockResolvedValue(
      envelope([
        {
          id: "src_1",
          name: "Federal Reserve",
          source_type: "official",
          category: "global_macro",
          region: "us",
          url: "https://example.com/rss",
          language: "en",
          enabled: true,
          polling_interval_seconds: 900,
          source_score: 100,
        },
        {
          id: "src_2",
          name: "CoinDesk",
          source_type: "rss",
          category: "crypto",
          region: "crypto",
          url: "https://example.com/coindesk",
          language: "en",
          enabled: false,
          polling_interval_seconds: 600,
          source_score: 75,
        },
      ]),
    );

    await renderLoadedApp();
    switchTo("sources");
    await screen.findByTestId("source-card-src_1");

    fireEvent.click(screen.getByRole("checkbox", { name: "All sources" }));

    await waitFor(() => expect(apiMock.setAllSourcesEnabled).toHaveBeenCalledWith(true));
  });

  it("creates edits and deletes watchlist entries from the dashboard", async () => {
    await renderLoadedApp();
    switchTo("watchlist");
    await screen.findByText("SPY");

    fireEvent.click(screen.getByRole("button", { name: /add watchlist entry/i }));
    const main = screen.getByRole("main");
    expect(within(main).getByRole("combobox", { name: "Entity type" })).toBeInTheDocument();
    expect(within(main).getByRole("combobox", { name: "Tier" })).toBeInTheDocument();
    expect(within(main).getByRole("combobox", { name: "Region" })).toBeInTheDocument();
    expect(within(main).getByRole("combobox", { name: "Asset class" })).toBeInTheDocument();
    expect(within(main).queryByRole("option", { name: "commodity" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "BTC" } });
    fireEvent.change(screen.getByLabelText("Entity name"), { target: { value: "Bitcoin" } });
    fireEvent.change(screen.getByLabelText("Entity type"), { target: { value: "crypto" } });
    fireEvent.change(screen.getByLabelText("Tier"), { target: { value: "S" } });
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "global" } });
    fireEvent.change(screen.getByLabelText("Asset class"), { target: { value: "crypto" } });
    fireEvent.change(screen.getByLabelText("Aliases"), { target: { value: "digital gold" } });
    fireEvent.click(screen.getByRole("button", { name: /^save watchlist entry$/i }));

    await waitFor(() =>
      expect(apiMock.createWatchlistEntry).toHaveBeenCalledWith({
        symbol: "BTC",
        name: "Bitcoin",
        entity_type: "crypto",
        tier: "S",
        region: "global",
        asset_class: "crypto",
        aliases: ["digital gold"],
        enabled: true,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /edit SPY/i }));
    fireEvent.change(screen.getByLabelText("Entity name"), {
      target: { value: "SPDR S&P 500 ETF" },
    });
    fireEvent.change(screen.getByLabelText("Tier"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: /^save watchlist entry$/i }));

    await waitFor(() =>
      expect(apiMock.updateWatchlistEntry).toHaveBeenCalledWith(
        "watch_1",
        expect.objectContaining({ name: "SPDR S&P 500 ETF", tier: "A" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /delete SPY/i }));

    // Verify modal is open and click the delete confirm button inside it
    const modal = screen.getByRole("dialog");
    expect(within(modal).getByText("Delete watchlist entry?")).toBeInTheDocument();
    const confirmButton = within(modal).getByRole("button", { name: /^delete$/i });
    fireEvent.click(confirmButton);

    await waitFor(() => expect(apiMock.deleteWatchlistEntry).toHaveBeenCalledWith("watch_1"));
  });

  it("trims watchlist aliases while editing", async () => {
    await renderLoadedApp();
    switchTo("watchlist");

    fireEvent.click(await screen.findByRole("button", { name: /edit SPY/i }));
    fireEvent.change(screen.getByLabelText("Aliases"), {
      target: { value: "SPY, S&P 500,  SPDR" },
    });

    expect(screen.getByLabelText("Aliases")).toHaveValue("SPY, S&P 500, SPDR");
  });

  it("saves alert policy settings from operations", async () => {
    await renderLoadedApp();
    switchTo("operations");

    fireEvent.change(screen.getByLabelText("Immediate threshold"), { target: { value: "85" } });
    fireEvent.change(screen.getByLabelText("Watchlist threshold"), { target: { value: "60" } });
    fireEvent.change(screen.getByLabelText("Digest threshold"), { target: { value: "35" } });
    fireEvent.change(screen.getByLabelText("Default channel"), {
      target: { value: "telegram" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save alert policy/i }));

    await waitFor(() =>
      expect(apiMock.updateAlertPolicy).toHaveBeenCalledWith({
        immediate_threshold: 85,
        watchlist_threshold: 60,
        digest_threshold: 35,
        default_channel: "telegram",
      }),
    );
  });

  it("acknowledges alerts and manages delivery controls", async () => {
    await renderLoadedApp();
    switchTo("alerts");

    expect(await screen.findByText("1 unacknowledged")).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByTestId("alert-row-alert_1")).getByRole("button", {
        name: /acknowledge/i,
      }),
    );

    await waitFor(() => expect(apiMock.acknowledgeAlert).toHaveBeenCalledWith("alert_1"));

    // Switch to settings sub-tab to make inputs visible in DOM
    fireEvent.click(screen.getByRole("button", { name: /settings/i }));
    const channelType = await screen.findByLabelText("Channel type");
    fireEvent.change(channelType, { target: { value: "webhook" } });

    fireEvent.change(screen.getByLabelText("Channel name"), { target: { value: "Webhook" } });
    fireEvent.change(screen.getByLabelText("Channel config"), {
      target: { value: '{"url":"https://hooks.example.test/alert"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: /save channel/i }));

    await waitFor(() =>
      expect(apiMock.createAlertChannel).toHaveBeenCalledWith({
        name: "Webhook",
        channel_type: "webhook",
        config: { url: "https://hooks.example.test/alert" },
        enabled: true,
        is_default: false,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /test Primary Telegram/i }));
    await waitFor(() =>
      expect(apiMock.testAlertChannel).toHaveBeenCalledWith(
        "chan_1",
        "Dashboard test alert",
      ),
    );

    fireEvent.change(screen.getByLabelText("Rule name"), { target: { value: "Cooldown" } });
    fireEvent.click(screen.getByRole("button", { name: /save suppression rule/i }));

    await waitFor(() =>
      expect(apiMock.createAlertSuppressionRule).toHaveBeenCalledWith({
        name: "Cooldown",
        rule_type: "cooldown",
        config: { hours: 6 },
        enabled: true,
      }),
    );
  });

  it("shows alert action errors", async () => {
    apiMock.acknowledgeAlert.mockRejectedValueOnce(new Error("alert update failed"));
    await renderLoadedApp();
    switchTo("alerts");

    fireEvent.click(
      within(await screen.findByTestId("alert-row-alert_1")).getByRole("button", {
        name: /acknowledge/i,
      }),
    );

    expect(await screen.findByText("alert update failed")).toBeInTheDocument();
  });

  it("formats alert decisions with every underscore replaced", async () => {
    apiMock.alerts.mockResolvedValue(
      envelope([
        {
          id: "alert_multi",
          event_cluster_id: "evt_1",
          decision: "some_multi_word_value",
          reason: "score_above_immediate_threshold",
          channel: "telegram",
          sent_at: "2026-05-29T13:05:00Z",
          created_at: "2026-05-29T13:05:00Z",
          event: { id: "evt_1", headline: "Fed signals a slower rate path", final_score: 84 },
          latest_delivery_status: "sent",
          acknowledged_at: null,
        },
      ]),
    );
    await renderLoadedApp();
    switchTo("alerts");

    expect(await screen.findAllByText("some multi word value")).not.toHaveLength(0);
  });

  it("shows alert detail metadata and related event news for the selected alert", async () => {
    await renderLoadedApp();
    switchTo("alerts");

    const detailPanel = (await screen.findByRole("heading", { name: "Alert detail" })).closest(
      "section",
    )!;
    expect(
      within(detailPanel).getAllByText("Treasury yields fall after jobs report").length,
    ).toBeGreaterThan(0);
    expect(within(detailPanel).getByText("score_above_digest_threshold")).toBeInTheDocument();
    expect(within(detailPanel).getByText("waiting for digest window")).toBeInTheDocument();
    expect(within(detailPanel).getByText("Related news")).toBeInTheDocument();
    expect(within(detailPanel).getByText("BLS · seed · 88")).toBeInTheDocument();
    expect(within(detailPanel).getByText("final score")).toBeInTheDocument();
    expect(within(detailPanel).getAllByText("61").length).toBeGreaterThan(0);
    expect(apiMock.alert).toHaveBeenCalledWith("alert_2");
    expect(apiMock.event).toHaveBeenCalledWith("evt_2");

    fireEvent.click(screen.getByTestId("alert-row-alert_1"));

    expect(
      await within(detailPanel).findByText("score_above_immediate_threshold"),
    ).toBeInTheDocument();
    expect(within(detailPanel).getByText("Federal Reserve · seed · 91")).toBeInTheDocument();
    expect(apiMock.alert).toHaveBeenCalledWith("alert_1");
    expect(apiMock.event).toHaveBeenCalledWith("evt_1");
  });

  it("dismisses alerts and updates state", async () => {
    await renderLoadedApp();
    switchTo("alerts");

    expect((await screen.findAllByText("unacknowledged")).length).toBeGreaterThan(0);

    // Setup mock for subsequent reload
    apiMock.alerts.mockResolvedValue(
      envelope([
        {
          id: "alert_1",
          event_cluster_id: "evt_1",
          decision: "immediate_alert",
          reason: "score_above_immediate_threshold",
          channel: "telegram",
          sent_at: "2026-05-29T13:05:00Z",
          created_at: "2026-05-29T13:05:00Z",
          event: { id: "evt_1", headline: "Fed signals a slower rate path", final_score: 84 },
          latest_delivery_status: "sent",
          acknowledged_at: "2026-05-29T14:00:00Z",
          suppression_reason: "dismissed",
        },
      ]),
    );

    fireEvent.click(
      within(screen.getByTestId("alert-row-alert_1")).getByRole("button", { name: /dismiss/i }),
    );

    await waitFor(() => expect(apiMock.dismissAlert).toHaveBeenCalledWith("alert_1"));
    expect(await screen.findByText("dismissed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /acknowledge/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dismiss/i })).not.toBeInTheDocument();
  });

  it("acknowledges alerts and hides buttons", async () => {
    await renderLoadedApp();
    switchTo("alerts");

    expect((await screen.findAllByText("unacknowledged")).length).toBeGreaterThan(0);

    // Setup mock for subsequent reload
    apiMock.alerts.mockResolvedValue(
      envelope([
        {
          id: "alert_1",
          event_cluster_id: "evt_1",
          decision: "immediate_alert",
          reason: "score_above_immediate_threshold",
          channel: "telegram",
          sent_at: "2026-05-29T13:05:00Z",
          created_at: "2026-05-29T13:05:00Z",
          event: { id: "evt_1", headline: "Fed signals a slower rate path", final_score: 84 },
          latest_delivery_status: "sent",
          acknowledged_at: "2026-05-29T14:00:00Z",
          suppression_reason: null,
        },
      ]),
    );

    fireEvent.click(
      within(screen.getByTestId("alert-row-alert_1")).getByRole("button", {
        name: /acknowledge/i,
      }),
    );

    await waitFor(() => expect(apiMock.acknowledgeAlert).toHaveBeenCalledWith("alert_1"));
    expect(await screen.findByText("acknowledged")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /acknowledge/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dismiss/i })).not.toBeInTheDocument();
  });
});

describe("compareValues utility", () => {
  it("compares numbers correctly", () => {
    expect(compareValues(5, 10)).toBeLessThan(0);
    expect(compareValues(10, 5)).toBeGreaterThan(0);
    expect(compareValues(5, 5)).toBe(0);
  });

  it("compares strings correctly", () => {
    expect(compareValues("apple", "banana")).toBeLessThan(0);
    expect(compareValues("banana", "apple")).toBeGreaterThan(0);
    expect(compareValues("apple", "apple")).toBe(0);
  });

  it("compares timestamps correctly", () => {
    const time1 = "2026-05-29T13:00:00Z";
    const time2 = "2026-05-29T14:00:00Z";
    expect(compareValues(time1, time2)).toBeLessThan(0);
    expect(compareValues(time2, time1)).toBeGreaterThan(0);
    expect(compareValues(time1, time1)).toBe(0);
  });

  it("handles null values consistently", () => {
    expect(compareValues(null, "apple")).toBeLessThan(0);
    expect(compareValues("apple", null)).toBeGreaterThan(0);
    expect(compareValues(null, null)).toBe(0);
  });

  it("compares booleans correctly", () => {
    expect(compareValues(false, true)).toBeLessThan(0);
    expect(compareValues(true, false)).toBeGreaterThan(0);
    expect(compareValues(true, true)).toBe(0);
  });
});

describe("Phase 3 command center", () => {
  it("shows migration guidance when command queue is unavailable", async () => {
    mockSuccessfulLoad({
      botStatus: vi.fn().mockResolvedValue({
        mode: "shared_database",
        latest_job: null,
        latest_job_available: true,
        pending_commands: 0,
        running_commands: 0,
        command_queue_available: false,
      }),
    });

    await renderLoadedApp();
    switchTo("commands");

    expect(await screen.findByText("Command queue unavailable")).toBeInTheDocument();
    expect(screen.getByText(/uv run market-watch migrate/)).toBeInTheDocument();
  });

  it("disables command buttons when queue is unavailable", async () => {
    mockSuccessfulLoad({
      botStatus: vi.fn().mockResolvedValue({
        mode: "shared_database",
        latest_job: null,
        latest_job_available: true,
        pending_commands: 0,
        running_commands: 0,
        command_queue_available: false,
      }),
    });

    await renderLoadedApp();
    switchTo("commands");

    await waitFor(() => expect(screen.getByText("Command queue unavailable")).toBeInTheDocument());

    const liveButton = screen.getByRole("button", { name: /live run/i });
    expect(liveButton).toBeDisabled();
  });

  it("queues a source fetch command using source selector", async () => {
    apiMock.createCommand.mockResolvedValue({
      id: "cmd_src",
      command_type: "source.fetch",
      status: "pending",
      payload: { source_id: "src_1" },
      created_at: "2026-05-30T01:00:00Z",
    });

    await renderLoadedApp();
    switchTo("commands");

    const sourceSelect = await screen.findByLabelText("Select source");
    fireEvent.change(sourceSelect, { target: { value: "src_1" } });

    const fetchButton = screen.getByRole("button", { name: /fetch/i });
    fireEvent.click(fetchButton);

    await waitFor(() =>
      expect(apiMock.createCommand).toHaveBeenCalledWith("source.fetch", {
        source_id: "src_1",
      }),
    );
  });

  it("queues event merge, split, compaction, and quality refresh commands", async () => {
    apiMock.events.mockResolvedValue(
      envelope([
        {
          id: "evt_1",
          canonical_headline: "Fed signals a slower rate path",
          status: "reported",
          regions: ["us"],
          asset_classes: ["global_macro"],
          affected_entities: ["Federal Reserve"],
          affected_tickers: [],
          source_count: 2,
          final_score: 84,
        },
        {
          id: "evt_2",
          canonical_headline: "Treasury yields fall after jobs report",
          status: "reported",
          regions: ["us"],
          asset_classes: ["rates"],
          affected_entities: ["Treasury"],
          affected_tickers: [],
          source_count: 1,
          final_score: 70,
        },
      ]),
    );

    await renderLoadedApp();
    switchTo("commands");

    fireEvent.change(await screen.findByLabelText("Select event"), {
      target: { value: "evt_1" },
    });
    fireEvent.change(screen.getByLabelText("Select merge target event"), {
      target: { value: "evt_2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Merge" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", {
      name: /execute/i,
    }));

    await waitFor(() =>
      expect(apiMock.createCommand).toHaveBeenCalledWith("event.merge", {
        source_event_id: "evt_1",
        target_event_id: "evt_2",
      }),
    );

    fireEvent.change(screen.getByLabelText("Split news item IDs"), {
      target: { value: "news_1, news_2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Split" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", {
      name: /execute/i,
    }));

    await waitFor(() =>
      expect(apiMock.createCommand).toHaveBeenCalledWith("event.split", {
        event_id: "evt_1",
        news_item_ids: ["news_1", "news_2"],
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /refresh quality/i }));
    fireEvent.click(screen.getByRole("button", { name: /preview compaction/i }));

    expect(apiMock.createCommand).toHaveBeenCalledWith("source.quality.refresh", {});
    expect(apiMock.createCommand).toHaveBeenCalledWith("event.compact_archived", {
      older_than: "30d",
      limit: 500,
      apply: false,
    });
  });

  it("requires confirmation for live pipeline run", async () => {
    await renderLoadedApp();
    switchTo("commands");

    const liveButton = await screen.findByRole("button", { name: /live run/i });
    fireEvent.click(liveButton);

    expect(apiMock.createCommand).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/run live pipeline/i)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: /execute/i }));

    await waitFor(() =>
      expect(apiMock.createCommand).toHaveBeenCalledWith("pipeline.run", { dry_run: false }),
    );
  });

  it("requires confirmation for retention run", async () => {
    await renderLoadedApp();
    switchTo("commands");

    const retentionButton = await screen.findByRole("button", { name: /run retention/i });
    fireEvent.click(retentionButton);

    expect(apiMock.createCommand).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/permanently delete/i)).toBeInTheDocument();
  });

  it("displays command statuses with proper badges", async () => {
    apiMock.commands.mockResolvedValue(
      envelope([
        {
          id: "cmd_1",
          command_type: "pipeline.run",
          status: "succeeded",
          payload: { dry_run: true },
          result: { clusters: 3 },
          created_at: "2026-05-30T01:00:00Z",
          completed_at: "2026-05-30T01:01:00Z",
        },
        {
          id: "cmd_2",
          command_type: "retention.run",
          status: "failed",
          payload: {},
          error_message: "connection refused",
          created_at: "2026-05-30T00:30:00Z",
        },
        {
          id: "cmd_3",
          command_type: "source.fetch",
          status: "pending",
          payload: { source_id: "src_1" },
          created_at: "2026-05-30T00:20:00Z",
        },
      ]),
    );

    await renderLoadedApp();
    switchTo("commands");

    expect(await screen.findByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });
});
