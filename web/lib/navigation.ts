import { normalizeStaffSearch } from "./api/staff";

export type NavigationIcon = "dashboard" | "staff" | "audit" | "password";

export type NavigationItem = {
  label: string;
  href: string;
  icon: NavigationIcon;
  /** Shown only when the user holds this permission. Omit for every signed-in user. */
  permission?: string;
};

export const NAVIGATION: readonly NavigationItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: "dashboard" },
  { label: "Staff", href: "/staff", icon: "staff", permission: "staff:read" },
  { label: "Audit log", href: "/audit", icon: "audit", permission: "audit:read" },
  { label: "Change password", href: "/account/password", icon: "password" },
];

/**
 * Items the user may see. This only hides navigation: the API authorizes every request
 * on its own and never trusts these checks.
 */
export function visibleNavigation(
  permissions: readonly string[],
  items: readonly NavigationItem[] = NAVIGATION,
): NavigationItem[] {
  const granted = new Set(permissions);
  return items.filter((item) => !item.permission || granted.has(item.permission));
}

/** True on the item's own page and on pages below it, so /staff/new keeps Staff current. */
export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Where the top-bar search goes: the staff directory, filtered by `q` when there is one. */
export function staffSearchHref(term: string): string {
  const q = normalizeStaffSearch(term);
  return q ? `/staff?${new URLSearchParams({ q })}` : "/staff";
}
