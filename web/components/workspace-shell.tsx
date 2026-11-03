"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { visibleNavigation } from "@/lib/navigation";
import { useSessionContext } from "@/lib/session";

/**
 * The workspace frame. Children render only after the session has loaded, so no
 * workspace content ever appears for an unauthenticated visitor.
 */
export function WorkspaceShell({ children }: { children: ReactNode }) {
  const { state, reload, signOut } = useSessionContext();
  const pathname = usePathname();

  if (state.status === "loading") {
    return (
      <div className="workspace-status" role="status" aria-live="polite">
        Loading your workspace…
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="workspace-status" role="alert">
        <p>The workspace could not be loaded.</p>
        <button type="button" className="button" onClick={reload}>
          Try again
        </button>
      </div>
    );
  }

  const { user, permissions } = state.session;
  return (
    <div className="workspace">
      <header className="workspace-header">
        <p className="brand">EstateHub</p>
        <nav aria-label="Workspace">
          <ul className="nav-list">
            {visibleNavigation(permissions).map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="nav-item"
                  aria-current={
                    pathname === item.href || pathname.startsWith(`${item.href}/`) ? "page" : undefined
                  }
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="account">
          <span className="account-name">{user.fullName}</span>
          <button type="button" className="button button-secondary" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="workspace-main">{children}</main>
    </div>
  );
}
