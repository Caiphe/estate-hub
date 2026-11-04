import { API_BASE_PATH, CSRF_COOKIE_NAME, CSRF_HEADER_NAME } from "../auth/config";
import { ApiError, NetworkError, RefreshUnavailableError, toApiError } from "./errors";
import {
  parseCurrentUser,
  parseEffectivePermissions,
  type CurrentUser,
  type EffectivePermissions,
} from "./types";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// 401 codes that a fresh access token can fix: the token expired, the browser dropped
// the expired cookie, or the token version moved on (for example after a role change).
const REFRESHABLE_CODES = new Set(["token_expired", "authentication_required", "invalid_token"]);
// Requests that must never trigger a refresh themselves.
const NO_REFRESH_PATHS = new Set(["/auth/token", "/auth/refresh", "/auth/logout"]);

export type RequestOptions = {
  method?: string;
  /** Sent as JSON. */
  json?: unknown;
  /** Sent as application/x-www-form-urlencoded. */
  form?: Record<string, string>;
  /** Cancels the request. An abort rejects with the signal's reason, not NetworkError. */
  signal?: AbortSignal;
};

/**
 * - `refreshed`: new cookies are set; retry.
 * - `rejected`: the API refused the refresh session (it also cleared the cookies).
 * - `unavailable`: no verdict (network failure, aborted request, 429, 5xx); the session
 *   may still be valid, so nobody is signed out.
 */
export type RefreshOutcome = "refreshed" | "rejected" | "unavailable";

/**
 * - `refresh_rejected`: the API ended the session and cleared its cookies.
 * - `still_unauthorized`: a fresh token was still refused; cookies may remain.
 */
export type SessionLostReason = "refresh_rejected" | "still_unauthorized";

export type ApiClientOptions = {
  baseUrl?: string;
  fetch?: typeof fetch;
  /** Reads a cookie visible to scripts. Only the CSRF cookie is ever read. */
  readCookie?: (name: string) => string | null;
  /** Called when the session cannot be recovered by a refresh. */
  onSessionLost?: (reason: SessionLostReason) => void;
};

function documentCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

/**
 * Typed client for the EstateHub API.
 *
 * Tokens live only in HTTP-only cookies sent with `credentials: "include"`; this client
 * never sees, stores, or returns them. Unsafe methods carry the CSRF header, read from
 * the CSRF cookie at send time because it rotates on every refresh. A refreshable 401
 * triggers one refresh, shared by every request waiting at that moment, and then one
 * retry.
 */
export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly readCookie: (name: string) => string | null;
  private readonly onSessionLost: (reason: SessionLostReason) => void;
  private refreshInFlight: Promise<RefreshOutcome> | null = null;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? API_BASE_PATH;
    this.fetchImpl = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
    this.readCookie = options.readCookie ?? documentCookie;
    this.onSessionLost = options.onSessionLost ?? (() => {});
  }

  async request<T = undefined>(
    path: string,
    options: RequestOptions = {},
    parse?: (data: unknown) => T,
  ): Promise<T> {
    let response = await this.send(path, options);
    if (this.shouldRefresh(path, response)) {
      const failure = await toApiError(response.clone());
      if (!REFRESHABLE_CODES.has(failure.code)) throw failure;
      const outcome = await this.refresh();
      if (outcome === "unavailable") throw new RefreshUnavailableError();
      if (outcome === "rejected") {
        this.onSessionLost("refresh_rejected");
        throw failure;
      }
      response = await this.send(path, options);
      if (response.status === 401) {
        this.onSessionLost("still_unauthorized");
      }
    }
    if (!response.ok) throw await toApiError(response);
    if (response.status === 204) return undefined as T;
    const data: unknown = await response.json();
    return parse ? parse(data) : (data as T);
  }

  /** Rotate the session. Concurrent callers share one request. */
  refresh(): Promise<RefreshOutcome> {
    this.refreshInFlight ??= this.send("/auth/refresh", { method: "POST" })
      .then((response): RefreshOutcome => {
        if (response.ok) return "refreshed";
        // 401: the session is gone. 403: the CSRF pair is broken and cannot recover.
        return response.status === 401 || response.status === 403 ? "rejected" : "unavailable";
      })
      .catch((): RefreshOutcome => "unavailable")
      .finally(() => {
        this.refreshInFlight = null;
      });
    return this.refreshInFlight;
  }

  // --- Endpoints -------------------------------------------------------------------------

  /** Sign in. The token in the response body is deliberately discarded. */
  async login(email: string, password: string): Promise<void> {
    await this.request("/auth/token", {
      method: "POST",
      form: { username: email, password },
    }, () => undefined);
  }

  async logout(): Promise<void> {
    await this.request("/auth/logout", { method: "POST" });
  }

  me(): Promise<CurrentUser> {
    return this.request("/auth/me", {}, parseCurrentUser);
  }

  myPermissions(): Promise<EffectivePermissions> {
    return this.request("/auth/me/permissions", {}, parseEffectivePermissions);
  }

  async changePassword(input: {
    currentPassword: string;
    newPassword: string;
    confirmation: string;
  }): Promise<void> {
    await this.request("/auth/change-password", {
      method: "POST",
      json: {
        current_password: input.currentPassword,
        new_password: input.newPassword,
        new_password_confirmation: input.confirmation,
      },
    });
  }

  // --- Internals -------------------------------------------------------------------------

  private shouldRefresh(path: string, response: Response): boolean {
    return response.status === 401 && !NO_REFRESH_PATHS.has(path);
  }

  private async send(path: string, options: RequestOptions): Promise<Response> {
    const method = (options.method ?? "GET").toUpperCase();
    const headers = new Headers({ Accept: "application/json" });
    let body: BodyInit | undefined;
    if (options.json !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.json);
    } else if (options.form) {
      body = new URLSearchParams(options.form);
    }
    if (UNSAFE_METHODS.has(method)) {
      const csrf = this.readCookie(CSRF_COOKIE_NAME);
      if (csrf) headers.set(CSRF_HEADER_NAME, csrf);
    }
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body,
        credentials: "include",
        cache: "no-store",
        signal: options.signal,
      });
    } catch (error) {
      if (options.signal?.aborted) throw options.signal.reason ?? error;
      throw new NetworkError();
    }
  }
}

export { ApiError, NetworkError, RefreshUnavailableError };
