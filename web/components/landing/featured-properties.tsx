import Link from "next/link";
import type { ReactNode } from "react";

import { PageContainer } from "@/components/page-container";
import { LANDING_SECTION_IDS } from "@/lib/landing/navigation";
import { SEARCH_PATH } from "@/lib/landing/search";
import type { PropertySummary } from "@/lib/landing/types";

import { ArrowRightIcon } from "./icons";
import { PropertyCard } from "./property-card";
import { PropertyCardSkeleton } from "./property-card-skeleton";

const SKELETON_COUNT = 3;

export const VIEW_ALL_HREF = SEARCH_PATH;

/** Everything the section can show. "ready" with no properties is the empty state. */
export type FeaturedPropertiesState =
  | { status: "loading" }
  | { status: "ready"; properties: readonly PropertySummary[]; isSample?: boolean }
  | { status: "error"; retryHref?: string };

type FeaturedPropertiesProps = {
  state: FeaturedPropertiesState;
  /** Section id; the heading id derives from it. Override only when rendering several. */
  id?: string;
};

/** Kicker, heading, and view-all link, then cards, skeletons, or a message. */
export function FeaturedProperties({ state, id = LANDING_SECTION_IDS.featuredProperties }: FeaturedPropertiesProps) {
  const headingId = `${id}-heading`;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      aria-busy={state.status === "loading" || undefined}
      className="scroll-mt-6 py-12 lg:py-14"
    >
      <PageContainer>
        <div className="mb-8 flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
          <div className="grid gap-2">
            <p className="text-xs font-bold tracking-eyebrow text-brand uppercase">Featured properties</p>
            <h2 id={headingId} className="text-2xl leading-tight font-extrabold tracking-tight">
              Discover our handpicked properties
            </h2>
          </div>
          <ViewAllLink />
        </div>
        <FeaturedBody state={state} />
      </PageContainer>
    </section>
  );
}

function FeaturedBody({ state }: { state: FeaturedPropertiesState }) {
  if (state.status === "loading") {
    return (
      <>
        <p role="status" className="sr-only">
          Loading featured properties…
        </p>
        <CardGrid>
          {Array.from({ length: SKELETON_COUNT }, (_, index) => (
            <li key={index}>
              <PropertyCardSkeleton />
            </li>
          ))}
        </CardGrid>
      </>
    );
  }

  if (state.status === "error") {
    return (
      <Message
        title="Featured properties could not be loaded."
        body="Try again, or browse every available property instead."
      >
        <Link href={state.retryHref ?? `/#${LANDING_SECTION_IDS.featuredProperties}`} className={MESSAGE_LINK}>
          Try again
        </Link>
        <Link href={VIEW_ALL_HREF} className={MESSAGE_LINK}>
          Browse all properties
        </Link>
      </Message>
    );
  }

  if (state.properties.length === 0) {
    return (
      <Message
        title="No featured properties right now."
        body="New listings are added regularly. Browse everything that is available today."
      >
        <Link href={VIEW_ALL_HREF} className={MESSAGE_LINK}>
          Browse all properties
        </Link>
      </Message>
    );
  }

  return (
    <>
      <CardGrid>
        {state.properties.map((property) => (
          <li key={property.id}>
            <PropertyCard property={property} />
          </li>
        ))}
      </CardGrid>
      {state.isSample && (
        <p className="mt-6 text-sm text-fg-muted">
          Sample listings for illustration. Locations, prices, and availability are not real.
        </p>
      )}
    </>
  );
}

/** Equal columns; cards fill their cells so a row shares one height. */
function CardGrid({ children }: { children: ReactNode }) {
  return <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">{children}</ul>;
}

/** The words carry the action; the arrow only reinforces direction. */
function ViewAllLink() {
  return (
    <Link
      href={VIEW_ALL_HREF}
      className="group inline-flex min-h-11 items-center gap-2 text-sm font-bold text-brand hover:text-brand-strong"
    >
      View all properties
      <ArrowRightIcon className="size-4 transition-transform duration-150 ease-standard motion-safe:group-hover:translate-x-0.5" />
    </Link>
  );
}

const MESSAGE_LINK =
  "inline-flex min-h-11 items-center rounded-sm border-[1.5px] border-brand px-5 font-bold text-fg transition-colors duration-150 ease-standard hover:bg-brand-subtle";

function Message({ title, body, children }: { title: string; body: string; children: ReactNode }) {
  return (
    <div className="grid justify-items-start gap-3 rounded-md border border-line bg-surface-tint p-8">
      <p className="text-lg font-bold">{title}</p>
      <p className="text-fg-muted">{body}</p>
      <div className="mt-2 flex flex-wrap gap-3">{children}</div>
    </div>
  );
}
