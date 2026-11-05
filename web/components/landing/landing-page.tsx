import type { ReactNode } from "react";

import { LANDING_SECTION_IDS } from "@/lib/landing/navigation";

import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";

/**
 * Public-site frame: skip link, a transparent header laid over the top of `main`, then
 * the footer.
 * The first section (the hero) paints the pale wash and reserves `--site-header-height`
 * at its top, so the header reads as part of the hero without leaving the header landmark.
 */
export function LandingPage({
  children,
  signedIn = false,
}: {
  children?: ReactNode;
  signedIn?: boolean;
}) {
  return (
    <div className="site relative min-h-screen bg-surface font-sans text-base leading-normal text-fg">
      <a
        href={`#${LANDING_SECTION_IDS.main}`}
        className="absolute top-2 left-2 z-20 -translate-y-[calc(100%+1rem)] rounded-sm bg-fg px-4 py-3 font-bold text-fg-inverse focus-visible:translate-y-0"
      >
        Skip to main content
      </a>
      <SiteHeader signedIn={signedIn} />
      {/* tabIndex lets the skip link move focus here, not just scroll. */}
      <main
        id={LANDING_SECTION_IDS.main}
        tabIndex={-1}
        className="focus:outline-none"
      >
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
