import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App, compareValues } from "./App";

const apiMock = vi.hoisted(() => ({
  botStatus: vi.fn(),
  sources: vi.fn(),
  events: vi.fn(),
  news: vi.fn(),
  alerts: vi.fn(),
  jobs: vi.fn(),
  watchlist: vi.fn(),
  commands: vi.fn(),
  createCommand: vi.fn(),
  setSourceEnabled: vi.fn(),
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

  it("keeps the watchlist page read-only in Phase 1", async () => {
    await renderLoadedApp();
    switchTo("watchlist");

    expect(await screen.findByText("SPY")).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(within(main).queryByRole("button", { name: /add|create|edit|delete|remove/i })).not.toBeInTheDocument();
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
