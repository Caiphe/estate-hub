import Image from "next/image";
import Link from "next/link";

import { PageContainer } from "@/components/page-container";
import { LANDING_ASSETS } from "@/lib/landing/assets";
import { LANDING_SECTION_IDS } from "@/lib/landing/navigation";

import { ArrowRightIcon } from "./icons";

const HEADING_ID = "invest-heading";

/** Opens the hero search in Invest mode. */
export const START_INVESTING_HREF = `/?listing=investment#${LANDING_SECTION_IDS.search}`;

/**
 * Forest-green call to action: message left, architecture right (stacked: message, then
 * photo). The photo is decorative
 * and sits in a box the layout sizes; the banner's own colour sits behind it, so the copy
 * stays readable if the photo never loads.
 */
export function InvestmentBanner() {
  const { src, alt } = LANDING_ASSETS.investmentBanner;
  return (
    <section id={LANDING_SECTION_IDS.invest} aria-labelledby={HEADING_ID} className="scroll-mt-6 pb-12 lg:pb-14">
      <PageContainer>
        <div className="relative flex flex-col overflow-hidden rounded-lg bg-brand-strong text-fg-inverse lg:block">
          <div className="relative z-1 grid justify-items-start gap-4 p-8 sm:p-10 lg:max-w-1/2 lg:px-12 lg:py-10">
            <h2 id={HEADING_ID} className="max-w-headline text-2xl leading-tight font-extrabold tracking-tight">
              Grow your wealth through real estate
            </h2>
            <p className="max-w-measure text-lg leading-normal">
              Invest in quality properties, earn steady returns, and build long-term value.
            </p>
            <Link
              href={START_INVESTING_HREF}
              // Sand on forest; focus uses the sand ring because the brand green would vanish here.
              className="group mt-2 inline-flex min-h-11 items-center gap-2 rounded-sm bg-accent px-5 font-bold text-fg transition duration-150 ease-standard hover:bg-surface focus-visible:outline-accent motion-safe:active:scale-96"
            >
              Start investing
              <ArrowRightIcon className="size-4 transition-transform duration-150 ease-standard motion-safe:group-hover:translate-x-0.5" />
            </Link>
          </div>
          <div className="relative aspect-video lg:absolute lg:inset-y-0 lg:right-0 lg:left-2/5 lg:aspect-auto">
            <Image
              src={src}
              alt={alt}
              fill
              sizes="(min-width: 64rem) 45rem, 100vw"
              // The building sits right of centre in the source; keep its upper floor in view.
              className="object-cover object-[75%_45%]"
            />
            {/* Blends the photo into the green: from above when stacked under the copy, from
                the left at desktop. */}
            <div className="absolute inset-0 bg-linear-to-b from-brand-strong to-transparent to-35% lg:bg-linear-to-r lg:to-45%" />
          </div>
        </div>
      </PageContainer>
    </section>
  );
}
