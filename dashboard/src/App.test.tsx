import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App, compareValues } from "./App";

const apiMock = vi.hoisted(() => ({
  botStatus: vi.fn(),
  sources: vi.fn(),
  events: vi.fn(),
  news: vi.fn(),
  alerts: vi.fn(),
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
  createSource: vi.fn(),
  updateSource: vi.fn(),
  createWatchlistEntry: vi.fn(),
  updateWatchlistEntry: vi.fn(),
  deleteWatchlistEntry: vi.fn(),
  alertPolicy: vi.fn(),
  updateAlertPolicy: vi.fn(),
  presets: vi.fn(),
}));

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
  apiMock.news.mockResolvedValue(
    envelope([
      {
        id: "news_1",
        title: "Fed signals a slower rate path",
        source_name: "Federal Reserve",
        source_type: "official",
        source_score: 100,
        region: "us",
        asset_classes: ["global_macro"],
        processing_status: "clustered",
        published_at: "2026-05-29T13:00:00Z",
        fetched_at: "2026-05-29T13:00:00Z",
      },
    ]),
  );
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
        acknowledged_at: null,
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
      source_types: ["rss", "official"],
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
  fireEvent.change(screen.getByRole("combobox"), { target: { value: view } });
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  mockSuccessfulLoad();
});

describe("App theme", () => {
  it("uses the dark emerald_terminal theme", async () => {
    await renderLoadedApp();

    expect(screen.getByTestId("dashboard-root")).toHaveAttribute("data-theme", "emerald_terminal");
    expect(document.documentElement).toHaveClass("dark");
  });
});

describe("App data states", () => {
  it("renders successful dashboard data", async () => {
    await renderLoadedApp();

    expect(await screen.findAllByText("Fed signals a slower rate path")).not.toHaveLength(0);
    switchTo("sources");
    expect(screen.getByText("Federal Reserve")).toBeInTheDocument();
    expect(screen.getByText("API ok")).toBeInTheDocument();
  });

  it("renders empty states instead of blank tables", async () => {
    apiMock.events.mockResolvedValue(envelope([]));
    apiMock.news.mockResolvedValue(envelope([]));

    await renderLoadedApp();

    expect(await screen.findByText("No priority events yet")).toBeInTheDocument();
    switchTo("news");
    expect(screen.getByText("No normalized news yet")).toBeInTheDocument();
  });

  it("keeps successful pages visible when one endpoint fails", async () => {
    apiMock.news.mockRejectedValue(new Error("news unavailable"));

    await renderLoadedApp();

    expect(await screen.findByText("API degraded")).toBeInTheDocument();
    switchTo("sources");
    expect(screen.getByText("Federal Reserve")).toBeInTheDocument();

    switchTo("news");
    expect(screen.getByText("Normalized news unavailable")).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: /edit Federal Reserve/i }));
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

  it("creates edits and deletes watchlist entries from the dashboard", async () => {
    await renderLoadedApp();
    switchTo("watchlist");

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
    fireEvent.click(screen.getByRole("button", { name: /acknowledge/i }));

    await waitFor(() => expect(apiMock.acknowledgeAlert).toHaveBeenCalledWith("alert_1"));

    // Switch to controls sub-tab to make inputs visible in DOM
    fireEvent.click(screen.getByRole("button", { name: /setting/i }));

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

  it("dismisses alerts and updates state", async () => {
    await renderLoadedApp();
    switchTo("alerts");

    expect(await screen.findByText("unacknowledged")).toBeInTheDocument();

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

    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));

    await waitFor(() => expect(apiMock.dismissAlert).toHaveBeenCalledWith("alert_1"));
    expect(await screen.findByText("dismissed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /acknowledge/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dismiss/i })).not.toBeInTheDocument();
  });

  it("acknowledges alerts and hides buttons", async () => {
    await renderLoadedApp();
    switchTo("alerts");

    expect(await screen.findByText("unacknowledged")).toBeInTheDocument();

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

    fireEvent.click(screen.getByRole("button", { name: /acknowledge/i }));

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
