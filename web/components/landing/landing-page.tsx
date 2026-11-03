import type { ReactNode } from "react";

import { LANDING_SECTION_IDS } from "@/lib/landing/navigation";

import { SiteHeader } from "./site-header";

/**
 * Public-site frame: skip link, then a transparent header laid over the top of `main`.
 * The first section (the hero) paints the pale wash and reserves `--site-header-height`
 * at its top, so the header reads as part of the hero without leaving the header landmark.
 */
export function LandingPage({ children }: { children?: ReactNode }) {
  return (
    <div className="site">
      <a className="skip-link" href={`#${LANDING_SECTION_IDS.main}`}>
        Skip to main content
      </a>
      <SiteHeader />
      {/* tabIndex lets the skip link move focus here, not just scroll. */}
      <main id={LANDING_SECTION_IDS.main} tabIndex={-1} className="site-main">
        {children}
      </main>
    </div>
  );
}
