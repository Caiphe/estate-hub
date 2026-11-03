import Link from "next/link";

import { PRIMARY_NAV } from "@/lib/landing/navigation";
import type { NavLink } from "@/lib/landing/types";

type PrimaryNavigationProps = {
  items?: readonly NavLink[];
  /** `href` of the item for the page being shown; it gets `aria-current` and an underline. */
  currentHref?: string;
};

export function PrimaryNavigation({ items = PRIMARY_NAV, currentHref }: PrimaryNavigationProps) {
  return (
    <nav className="primary-nav" aria-label="Primary">
      <ul className="primary-nav-list">
        {items.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              className="primary-nav-link"
              aria-current={item.href === currentHref ? "page" : undefined}
            >
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
