import Link from "next/link";

import type { FooterLinkGroup as FooterLinkGroupData } from "@/lib/landing/types";

/** A titled list of footer links; planned destinations show as text marked "Soon". */
export function FooterLinkGroup({ group }: { group: FooterLinkGroupData }) {
  const headingId = `footer-${group.heading.toLowerCase().replaceAll(" ", "-")}`;
  return (
    <nav aria-labelledby={headingId}>
      <h2 id={headingId} className="text-base font-bold text-fg-inverse">
        {group.heading}
      </h2>
      <ul role="list" className="mt-4 grid gap-1 text-sm">
        {group.links.map((link) => (
          <li key={link.label}>
            {"href" in link ? (
              <Link
                href={link.href}
                className="inline-flex min-h-8 items-center text-fg-inverse/80 transition-colors duration-150 ease-standard hover:text-fg-inverse hover:underline"
              >
                {link.label}
              </Link>
            ) : (
              <span className="inline-flex min-h-8 items-center gap-2 text-fg-inverse/70">
                {link.label}
                <span className="rounded-full border border-fg-inverse/30 px-1.5 text-xs leading-snug">
                  Soon
                </span>
              </span>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
