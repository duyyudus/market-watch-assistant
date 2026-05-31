import { describe, expect, it } from "vitest";

import { buildRequestHeaders, defaultApiBaseUrl, normalizeListResponse } from "./api";

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
