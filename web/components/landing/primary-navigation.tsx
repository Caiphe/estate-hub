import Link from "next/link";

import { PRIMARY_NAV } from "@/lib/landing/navigation";
import type { NavLink } from "@/lib/landing/types";

const LAYOUTS = {
  // Desktop bar: the underline marks the current page without relying on color alone.
  bar: {
    list: "flex gap-8",
    link: "relative inline-flex min-h-11 items-center font-semibold text-fg transition-colors duration-150 ease-standard hover:text-brand aria-[current=page]:text-brand after:absolute after:inset-x-0 after:bottom-1 after:h-0.5 after:scale-x-0 after:rounded-full after:bg-current after:transition-transform after:duration-150 hover:after:scale-x-100 aria-[current=page]:after:scale-x-100",
  },
  // Mobile menu: full-width rows; the current page is underlined and tinted.
  stack: {
    list: "grid gap-1",
    link: "flex min-h-11 items-center rounded-sm px-3 font-semibold text-fg transition-colors duration-150 ease-standard hover:bg-brand-subtle aria-[current=page]:bg-brand-subtle aria-[current=page]:text-brand aria-[current=page]:underline aria-[current=page]:decoration-2 aria-[current=page]:underline-offset-4",
  },
} as const;

type PrimaryNavigationProps = {
  items?: readonly NavLink[];
  /** `href` of the item for the page being shown; it gets `aria-current`. */
  currentHref?: string;
  layout?: keyof typeof LAYOUTS;
  className?: string;
};

export function PrimaryNavigation({
  items = PRIMARY_NAV,
  currentHref,
  layout = "bar",
  className,
}: PrimaryNavigationProps) {
  const styles = LAYOUTS[layout];
  return (
    <nav aria-label="Primary" className={className}>
      <ul className={styles.list}>
        {items.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              className={styles.link}
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
