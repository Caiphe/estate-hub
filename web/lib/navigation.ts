export type NavigationItem = {
  label: string;
  href: string;
  /** Shown only when the user holds this permission. Omit for every signed-in user. */
  permission?: string;
};

export const NAVIGATION: readonly NavigationItem[] = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "Staff", href: "/staff", permission: "staff:read" },
  { label: "Audit log", href: "/audit", permission: "audit:read" },
  { label: "Change password", href: "/account/password" },
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
