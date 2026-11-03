import { NextResponse, type NextRequest } from "next/server";

import { ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, LOGIN_PATH } from "./lib/auth/config";
import { loginPathFor, postLoginPath } from "./lib/auth/redirect";

/**
 * Optimistic route protection. Only the API decides who is authenticated; this proxy
 * just avoids rendering the workspace for visitors with no session at all.
 *
 * - Workspace routes need the access cookie, or the CSRF cookie (which lives as long as
 *   the refresh session) so the client can refresh an expired access token.
 * - /login sends visitors with an access cookie to the workspace. It ignores the CSRF
 *   cookie alone, so a session the API rejects can never cause a redirect loop.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasAccess = request.cookies.has(ACCESS_COOKIE_NAME);

  if (pathname === LOGIN_PATH) {
    if (hasAccess) {
      const target = postLoginPath(request.nextUrl.searchParams.get("next"));
      return NextResponse.redirect(new URL(target, request.url));
    }
    return noStore(NextResponse.next());
  }

  if (!hasAccess && !request.cookies.has(CSRF_COOKIE_NAME)) {
    return NextResponse.redirect(new URL(loginPathFor(`${pathname}${search}`), request.url));
  }
  return noStore(NextResponse.next());
}

/** Keep workspace and login pages out of the HTTP and back/forward caches. */
function noStore(response: NextResponse): NextResponse {
  response.headers.set("Cache-Control", "no-store, max-age=0");
  return response;
}

export const config = {
  // Must list every WORKSPACE_PREFIXES entry; Next.js requires a static literal here.
  matcher: ["/login", "/dashboard/:path*", "/account/:path*", "/staff/:path*", "/audit/:path*"],
};
