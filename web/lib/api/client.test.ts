import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "./client";
import { ApiError, NetworkError, RefreshUnavailableError } from "./errors";
import { ResponseShapeError } from "./types";

type Call = { url: string; method: string; headers: Headers; body: unknown; credentials?: string };

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function apiError(status: number, code: string, headers: Record<string, string> = {}): Response {
  return json(
    status,
    { error: { code, message: `${code} message`, fields: {}, request_id: "req-1" } },
    headers,
  );
}

const USER = {
  id: "7d9f1f6c-3a1b-4c55-9a51-0f4b6f5f6a10",
  email: "ada@estatehub.example",
  full_name: "Ada Agent",
  status: "active",
  roles: ["agent"],
  last_login_at: null,
  created_at: "2026-11-03T09:00:00Z",
  updated_at: "2026-11-03T09:00:00Z",
};

/**
 * A fake API. `handlers` maps "METHOD path" to queued responses; the CSRF cookie value
 * changes on every successful refresh, like the real API.
 */
function fakeApi(handlers: Record<string, Array<Response | (() => Promise<Response>)>>) {
  const calls: Call[] = [];
  let csrf = "csrf-0";
  let refreshes = 0;
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({
      url,
      method,
      headers: new Headers(init?.headers),
      body: init?.body,
      credentials: init?.credentials,
    });
    const key = `${method} ${url.replace("/api/v1", "")}`;
    const next = handlers[key]?.shift();
    if (!next) throw new Error(`Unexpected request: ${key}`);
    const response = typeof next === "function" ? await next() : next;
    if (key === "POST /auth/refresh" && response.ok) {
      refreshes += 1;
      csrf = `csrf-${refreshes}`;
    }
    return response;
  });
  const onSessionLost = vi.fn();
  const client = new ApiClient({
    fetch: fetchImpl as unknown as typeof fetch,
    readCookie: (name) => (name === "estatehub_csrf" ? csrf : null),
    onSessionLost,
  });
  return { client, calls, onSessionLost, refreshCount: () => refreshes };
}

describe("ApiClient requests", () => {
  it("sends credentials and parses responses", async () => {
    const api = fakeApi({ "GET /auth/me": [json(200, USER)] });

    const user = await api.client.me();

    expect(user).toMatchObject({ email: USER.email, fullName: "Ada Agent", roles: ["agent"] });
    expect(api.calls[0]).toMatchObject({ url: "/api/v1/auth/me", credentials: "include" });
  });

  it("sends the CSRF header only on unsafe methods", async () => {
    const api = fakeApi({
      "GET /auth/me": [json(200, USER)],
      "POST /auth/logout": [json(204, null)],
    });

    await api.client.me();
    await api.client.logout();

    expect(api.calls[0].headers.get("X-CSRF-Token")).toBeNull();
    expect(api.calls[1].headers.get("X-CSRF-Token")).toBe("csrf-0");
  });

  it("posts the login form and never returns the token", async () => {
    const api = fakeApi({
      "POST /auth/token": [json(200, { access_token: "secret", token_type: "bearer", expires_in: 900 })],
    });

    const result = await api.client.login("ada@estatehub.example", "pass phrase here");

    expect(result).toBeUndefined();
    const body = api.calls[0].body as URLSearchParams;
    expect(body.get("username")).toBe("ada@estatehub.example");
    expect(body.get("password")).toBe("pass phrase here");
  });

  it("maps the standard error body, including Retry-After", async () => {
    const api = fakeApi({
      "POST /auth/token": [apiError(429, "auth_rate_limited", { "Retry-After": "120" })],
    });

    const error = await api.client.login("a@b.example", "x").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 429,
      code: "auth_rate_limited",
      requestId: "req-1",
      retryAfter: 120,
    });
  });

  it("tolerates non-JSON error bodies", async () => {
    const api = fakeApi({ "GET /auth/me": [new Response("<html>bad gateway</html>", { status: 502 })] });

    await expect(api.client.me()).rejects.toMatchObject({ status: 502, code: "http_error" });
  });

  it("reports network failures as NetworkError", async () => {
    const api = fakeApi({
      "GET /auth/me": [() => Promise.reject(new TypeError("Failed to fetch"))],
    });

    await expect(api.client.me()).rejects.toBeInstanceOf(NetworkError);
  });

  it("rejects responses with an unexpected shape", async () => {
    const api = fakeApi({ "GET /auth/me": [json(200, { email: 42 })] });

    await expect(api.client.me()).rejects.toBeInstanceOf(ResponseShapeError);
  });
});

describe("ApiClient refresh", () => {
  it("refreshes once and retries with the rotated CSRF token", async () => {
    const api = fakeApi({
      "POST /auth/change-password": [apiError(401, "token_expired"), json(204, null)],
      "POST /auth/refresh": [json(200, {})],
    });

    await api.client.changePassword({
      currentPassword: "old passphrase",
      newPassword: "new passphrase!",
      confirmation: "new passphrase!",
    });

    expect(api.calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST /api/v1/auth/change-password",
      "POST /api/v1/auth/refresh",
      "POST /api/v1/auth/change-password",
    ]);
    expect(api.calls[1].headers.get("X-CSRF-Token")).toBe("csrf-0");
    expect(api.calls[2].headers.get("X-CSRF-Token")).toBe("csrf-1");
    expect(api.onSessionLost).not.toHaveBeenCalled();
  });

  it.each(["token_expired", "authentication_required", "invalid_token"])(
    "refreshes for %s",
    async (code) => {
      const api = fakeApi({
        "GET /auth/me": [apiError(401, code), json(200, USER)],
        "POST /auth/refresh": [json(200, {})],
      });

      await expect(api.client.me()).resolves.toMatchObject({ email: USER.email });
      expect(api.refreshCount()).toBe(1);
    },
  );

  it("shares one in-flight refresh between concurrent requests", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const api = fakeApi({
      "GET /auth/me": [apiError(401, "token_expired"), apiError(401, "token_expired"), json(200, USER), json(200, USER)],
      "GET /auth/me/permissions": [
        apiError(401, "token_expired"),
        json(200, { roles: ["agent"], permissions: ["deals:read"] }),
      ],
      "POST /auth/refresh": [async () => (await gate, json(200, {}))],
    });

    const pending = Promise.all([api.client.me(), api.client.me(), api.client.myPermissions()]);
    await vi.waitFor(() =>
      expect(api.calls.filter((c) => c.url.endsWith("/auth/refresh"))).toHaveLength(1),
    );
    release();
    const [first, second, permissions] = await pending;

    expect(first.email).toBe(USER.email);
    expect(second.email).toBe(USER.email);
    expect(permissions.permissions).toEqual(["deals:read"]);
    expect(api.calls.filter((c) => c.url.endsWith("/auth/refresh"))).toHaveLength(1);
  });

  it("retries at most once", async () => {
    const api = fakeApi({
      "GET /auth/me": [apiError(401, "token_expired"), apiError(401, "token_expired")],
      "POST /auth/refresh": [json(200, {})],
    });

    await expect(api.client.me()).rejects.toMatchObject({ status: 401 });
    expect(api.calls).toHaveLength(3);
    expect(api.onSessionLost).toHaveBeenCalledExactlyOnceWith("still_unauthorized");
  });

  it("reports a lost session when the refresh fails", async () => {
    const api = fakeApi({
      "GET /auth/me": [apiError(401, "token_expired")],
      "POST /auth/refresh": [apiError(401, "invalid_session")],
    });

    await expect(api.client.me()).rejects.toMatchObject({ code: "token_expired" });
    expect(api.onSessionLost).toHaveBeenCalledExactlyOnceWith("refresh_rejected");
    expect(api.calls).toHaveLength(2);
  });

  it.each([
    ["a network failure", () => Promise.reject(new TypeError("offline"))],
    ["an aborted request", () => Promise.reject(new DOMException("aborted", "AbortError"))],
    ["a rate limit", async () => apiError(429, "auth_rate_limited", { "Retry-After": "30" })],
    ["a server error", async () => apiError(503, "service_unavailable")],
  ])("does not end the session after %s during refresh", async (_, refresh) => {
    const api = fakeApi({
      "GET /auth/me": [apiError(401, "token_expired")],
      "POST /auth/refresh": [refresh],
    });

    await expect(api.client.me()).rejects.toBeInstanceOf(RefreshUnavailableError);
    expect(api.onSessionLost).not.toHaveBeenCalled();
  });

  it("treats a CSRF rejection during refresh as a lost session", async () => {
    const api = fakeApi({
      "GET /auth/me": [apiError(401, "token_expired")],
      "POST /auth/refresh": [apiError(403, "csrf_failed")],
    });

    await expect(api.client.me()).rejects.toMatchObject({ status: 401 });
    expect(api.onSessionLost).toHaveBeenCalledExactlyOnceWith("refresh_rejected");
  });

  it.each([
    ["POST /auth/token", (c: ApiClient) => c.login("a@b.example", "wrong password")],
    ["POST /auth/logout", (c: ApiClient) => c.logout()],
  ])("never refreshes for %s", async (key, call) => {
    const api = fakeApi({ [key]: [apiError(401, "invalid_credentials")] });

    await expect(call(api.client)).rejects.toMatchObject({ status: 401 });
    expect(api.calls).toHaveLength(1);
    expect(api.onSessionLost).not.toHaveBeenCalled();
  });

  it("does not refresh for other errors", async () => {
    const api = fakeApi({ "GET /auth/me": [apiError(403, "permission_denied")] });

    await expect(api.client.me()).rejects.toMatchObject({ status: 403 });
    expect(api.calls).toHaveLength(1);
  });
});
