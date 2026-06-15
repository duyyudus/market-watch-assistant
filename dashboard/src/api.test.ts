import { describe, expect, it } from "vitest";

import {
  buildAlertsPath,
  buildEventsPath,
  buildMaintenanceLLMCostsPath,
  buildMaintenancePipelineMetricsPath,
  buildRequestHeaders,
  defaultApiBaseUrl,
  normalizeListResponse,
} from "./api";
import { createResourceCache, debounceAsync } from "./lib/apiCache";

describe("normalizeListResponse", () => {
  it("keeps API list envelopes stable for dashboard pages", () => {
    const result = normalizeListResponse<{ id: string }>({ items: [{ id: "evt_1" }], total: 1 });

    expect(result.items).toEqual([{ id: "evt_1" }]);
    expect(result.total).toBe(1);
  });

  it("accepts plain arrays for defensive local fixtures", () => {
    const result = normalizeListResponse([{ id: "src_1" }]);

    expect(result.items).toEqual([{ id: "src_1" }]);
    expect(result.total).toBe(1);
  });

  it("uses the current host for network dashboard URLs", () => {
    expect(defaultApiBaseUrl("http:", "192.168.28.40")).toBe("http://192.168.28.40:8000");
  });

  it("adds a bearer token when dashboard auth is configured", () => {
    const headers = buildRequestHeaders("secret-token");

    expect(headers).toEqual({
      "Content-Type": "application/json",
      Authorization: "Bearer secret-token",
    });
  });

  it("omits authorization when dashboard auth is not configured", () => {
    const headers = buildRequestHeaders(undefined);

    expect(headers).toEqual({ "Content-Type": "application/json" });
  });

  it("builds observability maintenance endpoint paths", () => {
    expect(buildMaintenanceLLMCostsPath()).toBe("/maintenance/llm-costs");
    expect(buildMaintenancePipelineMetricsPath(20, 40)).toBe(
      "/maintenance/pipeline-metrics?limit=20&offset=40",
    );
  });

  it("builds event endpoint paths with pagination cap and score filter", () => {
    expect(
      buildEventsPath({
        offset: 100,
        pageSize: 100,
        maxItems: 500,
        minScore: 70,
      }),
    ).toBe("/events?limit=100&offset=100&max_items=500&min_score=70");
    expect(
      buildEventsPath({
        offset: 0,
        pageSize: 100,
        maxItems: null,
        minScore: 0,
      }),
    ).toBe("/events?limit=100&offset=0&min_score=0");
  });

  it("builds alert endpoint paths with pagination cap and decision filter", () => {
    expect(
      buildAlertsPath({
        offset: 100,
        pageSize: 100,
        maxItems: 500,
        decision: "immediate_alert",
      }),
    ).toBe("/alerts?limit=100&offset=100&max_items=500&decision=immediate_alert");
    expect(
      buildAlertsPath({
        offset: 0,
        pageSize: 100,
        maxItems: null,
        decision: null,
      }),
    ).toBe("/alerts?limit=100&offset=0");
  });
});

describe("createResourceCache", () => {
  it("deduplicates concurrent loads and serves fresh cached values", async () => {
    const cache = createResourceCache({ ttlMs: 1000, now: () => 100 });
    let calls = 0;
    const loader = async () => {
      calls += 1;
      return { calls };
    };

    const [first, second] = await Promise.all([
      cache.get("events", loader),
      cache.get("events", loader),
    ]);
    const third = await cache.get("events", loader);

    expect(first).toEqual({ calls: 1 });
    expect(second).toEqual({ calls: 1 });
    expect(third).toEqual({ calls: 1 });
    expect(calls).toBe(1);
  });

  it("invalidates keys and reloads expired entries", async () => {
    let now = 100;
    const cache = createResourceCache({ ttlMs: 50, now: () => now });
    let calls = 0;
    const loader = async () => {
      calls += 1;
      return calls;
    };

    expect(await cache.get("status", loader)).toBe(1);
    now = 200;
    expect(await cache.get("status", loader)).toBe(2);
    cache.invalidate("status");
    expect(await cache.get("status", loader)).toBe(3);
  });

  it("allows a failed in-flight request to be retried", async () => {
    const cache = createResourceCache({ ttlMs: 1000, now: () => 100 });
    let calls = 0;
    const loader = async () => {
      calls += 1;
      if (calls === 1) {
        throw new Error("temporary outage");
      }
      return "recovered";
    };

    await expect(cache.get("status", loader)).rejects.toThrow("temporary outage");

    await expect(cache.get("status", loader)).resolves.toBe("recovered");
    expect(calls).toBe(2);
  });
});

describe("debounceAsync", () => {
  it("coalesces rapid calls into one async operation", async () => {
    let calls = 0;
    const debounced = debounceAsync(async () => {
      calls += 1;
      return calls;
    }, 0);

    const [first, second] = await Promise.all([debounced(), debounced()]);

    expect(first).toBe(1);
    expect(second).toBe(1);
    expect(calls).toBe(1);
  });
});
