/**
 * Authentication settings shared by the proxy, the API client, and pages.
 *
 * Cookie names must match the API's ESTATEHUB_AUTH_*_COOKIE_NAME settings.
 */
export const ACCESS_COOKIE_NAME =
  process.env.NEXT_PUBLIC_AUTH_ACCESS_COOKIE_NAME ?? "estatehub_access";
export const CSRF_COOKIE_NAME = process.env.NEXT_PUBLIC_AUTH_CSRF_COOKIE_NAME ?? "estatehub_csrf";
export const CSRF_HEADER_NAME = "X-CSRF-Token";

/** Same-origin path; next.config.ts rewrites it to INTERNAL_API_BASE_URL. */
export const API_BASE_PATH = "/api/v1";

export const LOGIN_PATH = "/login";
export const WORKSPACE_HOME = "/dashboard";
/** Path prefixes that require a signed-in staff member. */
// Keep in sync with the matcher in proxy.ts (lib/auth/proxy-config.test.ts checks this).
export const WORKSPACE_PREFIXES = ["/dashboard", "/account", "/staff", "/audit"] as const;
