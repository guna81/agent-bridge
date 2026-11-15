import { afterEach, expect, it, vi } from "vitest";
import { admin, ApiError, getToken, setToken } from "./api";
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });
it("sends the saved admin token and JSON body", async () => {
  setToken("test-token");
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ saved: true }) });
  vi.stubGlobal("fetch", fetch);
  expect(await admin("POST", "/status-bar/config", { indicator_enabled: false })).toEqual({ saved: true });
  expect(fetch).toHaveBeenCalledWith("/admin/status-bar/config", expect.objectContaining({ headers: { Authorization: "Bearer test-token", "Content-Type": "application/json" }, body: '{"indicator_enabled":false}' }));
  setToken("");
  expect(getToken()).toBe("");
});
it("preserves authentication failure status", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ error: { message: "Unauthorized" } }) }));
  await expect(admin("GET", "/settings")).rejects.toMatchObject({ status: 401, message: "Unauthorized" });
  await expect(admin("GET", "/settings")).rejects.toBeInstanceOf(ApiError);
});
it("reports HTTP errors even when the body is not JSON", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => { throw new Error("invalid JSON"); } }));
  await expect(admin("GET", "/settings")).rejects.toMatchObject({ status: 502, message: "HTTP 502" });
});
