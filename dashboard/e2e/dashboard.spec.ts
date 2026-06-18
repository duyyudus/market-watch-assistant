import { expect, test, type Page, type Route } from "@playwright/test";

type Source = {
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

type WatchlistEntry = {
  id: string;
  symbol: string | null;
  name: string;
  entity_type: string;
  tier: string;
  region: string | null;
  asset_class: string | null;
  aliases: string[];
  enabled: boolean;
};

type AlertDecision = {
  id: string;
  event_cluster_id: string;
  decision: string;
  reason: string;
  channel: string;
  sent_at: string;
  acknowledged_at: string | null;
  suppression_reason?: string | null;
  created_at: string;
  event: { id: string; headline: string; final_score: number };
};

type BotCommand = {
  id: string;
  command_type: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  payload: Record<string, unknown>;
  requested_by?: string | null;
  created_at: string;
};

function envelope<T>(items: T[]) {
  return { items, total: items.length };
}

async function installApiMocks(page: Page) {
  const sources: Source[] = [
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
  ];
  const watchlist: WatchlistEntry[] = [
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
  ];
  const alerts: AlertDecision[] = [
    {
      id: "alert_1",
      event_cluster_id: "evt_1",
      decision: "immediate_alert",
      reason: "score_above_immediate_threshold",
      channel: "telegram",
      sent_at: "2026-05-29T13:05:00Z",
      acknowledged_at: null,
      created_at: "2026-05-29T13:05:00Z",
      event: { id: "evt_1", headline: "Fed signals a slower rate path", final_score: 84 },
    },
  ];
  const commands: BotCommand[] = [];

  await page.route("http://localhost:8000/events/stream", (route) =>
    route.fulfill({ status: 204, body: "" }),
  );
  await page.route("http://localhost:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "GET" && path === "/bot/status") {
      return json(route, {
        mode: "shared_database",
        latest_job: null,
        latest_job_available: true,
        pending_commands: commands.filter((command) => command.status === "pending").length,
        running_commands: commands.filter((command) => command.status === "running").length,
        command_queue_available: true,
      });
    }
    if (method === "GET" && path === "/settings/presets") {
      return json(route, {
        sources: {
          source_types: ["official", "rss"],
          regions: ["global", "us", "vietnam"],
          categories: ["global_macro", "crypto", "equity"],
          languages: ["en", "vi"],
        },
        watchlist: {
          entity_types: ["etf", "equity", "crypto"],
          tiers: ["S", "A", "B", "C", "D"],
          regions: ["global", "us", "vietnam"],
          asset_classes: ["equity", "crypto", "global_macro"],
        },
        alerts: { channels: [], rules: [] },
      });
    }
    if (method === "GET" && path === "/sources") return json(route, envelope(sources));
    if (method === "GET" && path === "/sources/health") {
      return json(
        route,
        envelope(
          sources.map((source) => ({
            source_id: source.id,
            name: source.name,
            enabled: source.enabled,
            category: source.category,
            region: source.region,
            health_status: "healthy",
            latest_status: "success",
            last_fetched_at: "2026-05-29T12:55:00Z",
            consecutive_failure_count: 0,
            average_latency_ms: 120,
            daily_item_counts: [{ date: "2026-05-29", count: 2 }],
          })),
        ),
      );
    }
    if (method === "POST" && path === "/sources/src_1/disable") {
      sources[0] = { ...sources[0], enabled: false };
      return json(route, sources[0]);
    }
    if (method === "POST" && path === "/sources/src_1/enable") {
      sources[0] = { ...sources[0], enabled: true };
      return json(route, sources[0]);
    }
    if (method === "GET" && path === "/watchlist") return json(route, envelope(watchlist));
    if (method === "POST" && path === "/watchlist") {
      const payload = await request.postDataJSON();
      const entry = { id: "watch_new", ...payload };
      watchlist.push(entry);
      return json(route, entry, 201);
    }
    if (method === "PATCH" && path === "/watchlist/watch_1") {
      const payload = await request.postDataJSON();
      watchlist[0] = { ...watchlist[0], ...payload };
      return json(route, watchlist[0]);
    }
    if (method === "DELETE" && path === "/watchlist/watch_1") {
      watchlist.splice(0, 1);
      return route.fulfill({ status: 204, body: "" });
    }
    if (method === "GET" && path === "/alerts") return json(route, envelope(alerts));
    if (method === "GET" && path === "/bot/commands") return json(route, envelope(commands));
    if (method === "POST" && path === "/bot/commands") {
      const payload = await request.postDataJSON();
      const command = {
        id: `cmd_${commands.length + 1}`,
        command_type: payload.command_type,
        status: "pending" as const,
        payload: payload.payload ?? {},
        requested_by: "dashboard",
        created_at: "2026-05-29T13:10:00Z",
      };
      commands.unshift(command);
      return json(route, command, 201);
    }
    if (method === "GET" && path === "/events") return json(route, envelope([]));
    if (method === "GET" && path === "/news") return json(route, envelope([]));
    if (method === "GET" && path === "/alert-channels") return json(route, envelope([]));
    if (method === "GET" && path === "/alert-suppression-rules") return json(route, envelope([]));
    if (method === "GET" && path === "/jobs/runs") return json(route, envelope([]));
    if (method === "GET" && path === "/settings/alert-policy") {
      return json(route, {
        immediate_threshold: 80,
        watchlist_threshold: 55,
        digest_threshold: 30,
        default_channel: "log",
      });
    }

    return json(route, { detail: `Unhandled mock route: ${method} ${path}` }, 404);
  });
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
  await page.goto("/");
});

test("can enable and disable sources without a live backend", async ({ page }) => {
  await page.getByRole("button", { name: "Sources" }).click();
  await expect(page.getByRole("cell", { name: "Federal Reserve", exact: true })).toBeVisible();

  await page.locator("table").getByLabel("Disable Federal Reserve").click();

  await expect(page.locator("table").getByLabel("Enable Federal Reserve")).toBeVisible();
});

test("can create edit and delete watchlist entries", async ({ page }) => {
  await page.getByRole("button", { name: "Watchlist" }).click();

  await page.getByRole("button", { name: "Add watchlist entry" }).click();
  await page.getByLabel("Symbol").fill("BTC");
  await page.getByLabel("Entity name").fill("Bitcoin");
  await page.getByRole("button", { name: "Save watchlist entry" }).click();
  await expect(page.getByText("Bitcoin")).toBeVisible();

  await page.getByLabel("Edit SPY").click();
  await page.getByLabel("Entity name").fill("SPY Trust");
  await page.getByRole("button", { name: "Save watchlist entry" }).click();
  await expect(page.getByText("SPY Trust")).toBeVisible();

  await page.getByLabel("Delete SPY").click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText("SPY Trust")).not.toBeVisible();
});

test("can queue manual commands", async ({ page }) => {
  await page.getByRole("button", { name: "Commands" }).click();
  await page.getByRole("button", { name: "Preview dispatch" }).click();

  await expect(page.getByText("alert.dispatch")).toBeVisible();
  await expect(page.getByText("pending", { exact: true })).toBeVisible();
});
