import { describe, expect, it } from "vitest";

import { buildRequestHeaders, defaultApiBaseUrl, normalizeListResponse } from "./api";
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
