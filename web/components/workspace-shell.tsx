"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentType, ReactNode, SVGProps } from "react";

import { AccountMenu } from "@/components/account-menu";
import { BrandMark } from "@/components/landing/brand-mark";
import { ClipboardListIcon, HouseIcon, LockIcon, UsersIcon } from "@/components/landing/icons";
import { StaffSearch } from "@/components/staff-search";
import { isActive, visibleNavigation, type NavigationIcon } from "@/lib/navigation";
import { useSessionContext } from "@/lib/session";

const ICONS: Record<NavigationIcon, ComponentType<SVGProps<SVGSVGElement>>> = {
  dashboard: HouseIcon,
  staff: UsersIcon,
  audit: ClipboardListIcon,
  password: LockIcon,
};

/**
 * The workspace frame: forest sidebar navigation, a top bar with staff search and the
 * account menu, and the page. Children render only after the session has loaded, so no
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

  const { user, roles, permissions } = state.session;
  return (
    <div className="workspace min-h-viewport lg:grid lg:grid-cols-[16.5rem_minmax(0,1fr)]">
      <a
        href="#workspace-main"
        className="absolute top-2 left-2 z-50 -translate-y-[calc(100%+1rem)] rounded-sm bg-fg px-4 py-3 font-bold text-fg-inverse no-underline focus-visible:translate-y-0"
      >
        Skip to main content
      </a>
      <div className="bg-brand-strong px-4 py-4 text-fg-inverse lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto lg:px-5 lg:py-6">
        <div className="px-2">
          <BrandMark tone="dark" />
        </div>
        <nav aria-label="Workspace" className="mt-4 lg:mt-8">
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0 lg:grid">
            {visibleNavigation(permissions).map((item) => {
              const Icon = ICONS[item.icon];
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={isActive(pathname, item.href) ? "page" : undefined}
                    className="flex min-h-11 items-center gap-3 rounded-md px-4 py-2.5 font-semibold text-fg-inverse no-underline transition-colors duration-150 ease-standard hover:bg-forest-deep motion-reduce:transition-none aria-[current=page]:bg-brand-subtle aria-[current=page]:font-extrabold aria-[current=page]:text-brand-strong"
                  >
                    <Icon className="shrink-0" />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex min-h-18 items-center gap-4 border-b border-line bg-surface px-4 py-3 sm:px-6 lg:px-8">
          {permissions.includes("staff:read") && <StaffSearch />}
          <AccountMenu user={user} roles={roles} onSignOut={() => void signOut()} />
        </header>
        <main id="workspace-main" tabIndex={-1} className="workspace-main px-4 py-7 focus:outline-none sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
