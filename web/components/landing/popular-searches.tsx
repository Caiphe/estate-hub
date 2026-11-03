import Link from "next/link";

import { buildSearchUrl, PROPERTY_TYPES } from "@/lib/landing/search";
import type { ListingType } from "@/lib/landing/types";

/** Shortcut links to results for one property type in the selected listing mode. */
export function PopularSearches({ listing }: { listing: ListingType }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <p id="popular-searches-label" className="text-sm font-bold">
        Popular:
      </p>
      <ul className="flex flex-wrap gap-2" aria-labelledby="popular-searches-label">
        {PROPERTY_TYPES.map((type) => (
          <li key={type.value}>
            {/* Compact like the reference; 32px still clears the WCAG 2.2 AA 24px minimum. */}
            <Link
              href={buildSearchUrl({ listing, type: type.value })}
              className="inline-flex min-h-8 items-center rounded-full bg-surface px-4 text-sm font-medium text-fg transition-colors duration-150 ease-standard hover:bg-brand-subtle"
            >
              {type.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
