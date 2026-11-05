import { ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME } from "./config";

type CookieReader = { has(name: string): boolean };

/**
 * Whether the browser holds a session the client could use: the access cookie, or the CSRF
 * cookie, which lives as long as the refresh session and lets an expired access token be
 * refreshed. A hint for rendering and routing only; the API decides who is authenticated.
 */
export function hasSessionCookie(cookies: CookieReader): boolean {
  return cookies.has(ACCESS_COOKIE_NAME) || cookies.has(CSRF_COOKIE_NAME);
}
