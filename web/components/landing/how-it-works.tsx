import { PageContainer } from "@/components/page-container";
import { PROCESS_STEPS } from "@/lib/landing/content";
import { LANDING_SECTION_IDS } from "@/lib/landing/navigation";
import type { ProcessStep } from "@/lib/landing/types";

import { IconTile } from "./icon-tile";

const HEADING_ID = "how-it-works-heading";

/**
 * Centred three-step sequence. The steps are an ordered list whose headings carry the
 * visible number, so the order survives without CSS or icons. At desktop a hairline joins
 * each icon to the previous one; it is an empty pseudo-element, invisible to assistive
 * technology. Stacked, the same rule turns vertical and sits in the gap between steps.
 */
export function HowItWorks({ steps = PROCESS_STEPS }: { steps?: readonly ProcessStep[] }) {
  return (
    <section
      id={LANDING_SECTION_IDS.howItWorks}
      aria-labelledby={HEADING_ID}
      className="scroll-mt-6 pb-16 lg:pb-20"
    >
      <PageContainer className="text-center">
        <p className="text-xs font-bold tracking-eyebrow text-brand uppercase">How it works</p>
        <h2 id={HEADING_ID} className="mt-2 text-2xl leading-tight font-extrabold tracking-tight">
          Get started in {steps.length} simple steps
        </h2>
        {/* role="list" keeps list semantics in Safari, which drops them with list-style: none. */}
        <ol role="list" className="mt-10 grid gap-10 lg:grid-cols-3 lg:gap-0">
          {steps.map((step, index) => (
            <li
              key={step.id}
              className={[
                "relative grid content-start justify-items-center gap-3 px-6",
                // Stacked: a short vertical rule in the gap above each later step.
                "not-first:before:absolute not-first:before:-top-8 not-first:before:left-1/2 not-first:before:h-6 not-first:before:w-px not-first:before:bg-line",
                // Desktop: a horizontal rule from the previous icon to this one.
                "lg:not-first:before:top-5.5 lg:not-first:before:right-[calc(50%+3rem)] lg:not-first:before:left-[calc(-50%+3rem)] lg:not-first:before:h-px lg:not-first:before:w-auto",
              ].join(" ")}
            >
              <IconTile name={step.icon} />
              <h3 className="text-lg leading-snug font-bold">
                {index + 1}. {step.title}
              </h3>
              <p className="max-w-xs text-fg-muted">{step.description}</p>
            </li>
          ))}
        </ol>
      </PageContainer>
    </section>
  );
}
