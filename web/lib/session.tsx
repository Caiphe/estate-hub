"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiClient } from "./api/client";
import { ApiError } from "./api/errors";
import type { CurrentUser } from "./api/types";
import { LOGIN_PATH } from "./auth/config";
import { loginPathFor } from "./auth/redirect";

export type Session = {
  user: CurrentUser;
  roles: string[];
  permissions: string[];
};

type SessionState =
  | { status: "loading" }
  | { status: "ready"; session: Session }
  | { status: "error" };

type SessionContextValue = {
  state: SessionState;
  client: ApiClient;
  reload: () => void;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

/** Full navigation that replaces the history entry, dropping all client state. */
function leaveTo(path: string) {
  window.location.replace(path);
}

/**
 * Loads the signed-in staff member for the workspace.
 *
 * Holds identity and permissions only. Tokens stay in HTTP-only cookies and are never
 * visible here. When the session cannot be recovered, it signs out (best effort, which
 * also clears the cookies) and returns to /login once, so a dead session cannot loop.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading" });

  const [client] = useState(() => {
    // Concurrent failing requests may all report a lost session; act on the first only.
    let leaving = false;
    const instance: ApiClient = new ApiClient({
      onSessionLost: (reason) => {
        if (leaving) return;
        leaving = true;
        setState({ status: "loading" });
        const returnTo = loginPathFor(`${window.location.pathname}${window.location.search}`);
        if (reason === "refresh_rejected") {
          // The API already cleared the cookies. Signing out here could race a refresh
          // from another tab and end a session that is still in use.
          leaveTo(returnTo);
          return;
        }
        // A fresh token was refused: clear the cookies so /login cannot bounce back.
        void instance
          .logout()
          .catch(() => undefined)
          .finally(() => leaveTo(returnTo));
      },
    });
    return instance;
  });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const [user, access] = await Promise.all([client.me(), client.myPermissions()]);
      setState({
        status: "ready",
        session: { user, roles: access.roles, permissions: access.permissions },
      });
    } catch (error) {
      // A 401 already triggered handleSessionLost; anything else can be retried.
      if (!(error instanceof ApiError && error.status === 401)) {
        setState({ status: "error" });
      }
    }
  }, [client]);

  useEffect(() => {
    // Initial bootstrap: fetch identity once the workspace mounts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  useEffect(() => {
    // A page restored from the back/forward cache may be from before sign-out.
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) window.location.reload();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  const signOut = useCallback(async () => {
    setState({ status: "loading" });
    try {
      await client.logout();
    } catch {
      // The API clears cookies even for unknown sessions; leave regardless.
    }
    leaveTo(LOGIN_PATH);
  }, [client]);

  const value = useMemo(
    () => ({ state, client, reload: () => void load(), signOut }),
    [state, client, load, signOut],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSessionContext(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSessionContext must be used inside SessionProvider.");
  return value;
}

/** The ready session. Only for components rendered after the workspace has loaded. */
export function useSession(): Session & { client: ApiClient } {
  const { state, client } = useSessionContext();
  if (state.status !== "ready") throw new Error("The session is not loaded yet.");
  return { ...state.session, client };
}
