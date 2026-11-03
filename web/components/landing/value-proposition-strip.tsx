import { PageContainer } from "@/components/page-container";
import { VALUE_PROPOSITIONS } from "@/lib/landing/content";
import type { ValueProposition } from "@/lib/landing/types";

import { IconTile } from "./icon-tile";

type ValuePropositionStripProps = {
  items?: readonly ValueProposition[];
};

/**
 * Reassurance strip under the hero. Desktop: four columns with hairline separators.
 * Smaller screens: icon beside text, one or two columns.
 */
export function ValuePropositionStrip({ items = VALUE_PROPOSITIONS }: ValuePropositionStripProps) {
  return (
    <section aria-labelledby="value-strip-heading">
      <PageContainer>
        <h2 id="value-strip-heading" className="sr-only">
          Why EstateHub
        </h2>
        <ul className="grid gap-6 border-b border-line py-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-0">
          {items.map((item) => (
            <li
              key={item.id}
              className="flex items-start gap-4 border-line lg:flex-col lg:gap-3 lg:px-6 lg:not-first:border-l"
            >
              <IconTile name={item.icon} />
              <div>
                <h3 className="text-base leading-snug font-bold">{item.title}</h3>
                <p className="text-sm leading-snug text-fg-muted">{item.description}</p>
              </div>
            </li>
          ))}
        </ul>
      </PageContainer>
    </section>
  );
}
