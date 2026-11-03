import type { NavLink } from "./types";

/**
 * Public-site navigation. Until listing and marketing routes exist, entries point at the
 * landing-page sections that later prompts add (`#search`, `#featured-properties`, …).
 * Buy and Rent carry a `listing` query the search panel can use to preselect its tab.
 */
export const PRIMARY_NAV: readonly NavLink[] = [
  { label: "Buy", href: "/?listing=sale#search" },
  { label: "Rent", href: "/?listing=rent#search" },
  { label: "Invest", href: "/#invest" },
  { label: "Properties", href: "/#featured-properties" },
  { label: "About", href: "/#how-it-works" },
];

export const HEADER_ACTIONS = {
  logIn: { label: "Log in", href: "/login" },
  getStarted: { label: "Get started", href: "/#how-it-works" },
} as const satisfies Record<string, NavLink>;

/** Section ids the navigation targets; sections must render these ids. */
export const LANDING_SECTION_IDS = {
  main: "main-content",
  search: "search",
  featuredProperties: "featured-properties",
  invest: "invest",
  howItWorks: "how-it-works",
} as const;
