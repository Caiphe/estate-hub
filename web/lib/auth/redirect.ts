import { LOGIN_PATH, WORKSPACE_HOME, WORKSPACE_PREFIXES } from "./config";

const MAX_NEXT_LENGTH = 2048;
// Any origin works here: it only lets URL parsing resolve relative paths.
const PLACEHOLDER_ORIGIN = "http://estatehub.invalid";

export function isWorkspacePath(pathname: string): boolean {
  return WORKSPACE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * Validate a post-login `next` value, returning a same-origin workspace path or null.
 *
 * Rejects absolute and protocol-relative URLs, backslash tricks browsers normalize to
 * `//`, control characters, and anything outside the workspace, so `next` can never be
 * used as an open redirect.
 */
export function safeNextPath(value: string | null | undefined): string | null {
  if (!value || value.length > MAX_NEXT_LENGTH) return null;
  if (!value.startsWith("/") || value.startsWith("//")) return null;
  if (value.includes("\\") || /[\u0000-\u001f\u007f]/.test(value)) return null;

  let url: URL;
  try {
    url = new URL(value, PLACEHOLDER_ORIGIN);
  } catch {
    return null;
  }
  if (url.origin !== PLACEHOLDER_ORIGIN || !isWorkspacePath(url.pathname)) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Where to go after signing in. */
export function postLoginPath(next: string | null | undefined): string {
  return safeNextPath(next) ?? WORKSPACE_HOME;
}

/** The login URL that returns to `path` afterwards. */
export function loginPathFor(path: string): string {
  const next = safeNextPath(path);
  return next ? `${LOGIN_PATH}?next=${encodeURIComponent(next)}` : LOGIN_PATH;
}
