import Link from "next/link";

import { propertyHref } from "@/lib/landing/property";
import type { PropertySummary } from "@/lib/landing/types";

import { FavoriteButton } from "./favorite-button";
import { PinIcon } from "./icons";
import { PropertyBadge } from "./property-badge";
import { PropertyFacts } from "./property-facts";
import { PropertyImage } from "./property-image";
import { PropertyPrice } from "./property-price";

type PropertyCardProps = {
  property: PropertySummary;
  /** Matches the surrounding outline; h3 under a section's h2 by default. */
  headingLevel?: "h2" | "h3" | "h4";
};

/**
 * One listing. The title link is stretched over the whole card, so any click opens the
 * listing, while the favorite button sits above it as a sibling, never nested inside a
 * link. Fills its grid cell (h-full) and pins facts to the bottom so a row lines up.
 */
export function PropertyCard({ property, headingLevel: Heading = "h3" }: PropertyCardProps) {
  return (
    <article className="group relative flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card transition-shadow duration-150 ease-standard hover:shadow-floating has-[a:focus-visible]:outline-3 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-brand">
      <PropertyImage image={property.image} />
      <div className="absolute inset-x-3 top-3 flex items-start justify-between gap-3">
        <PropertyBadge listingType={property.listingType} />
        <FavoriteButton propertyTitle={property.title} initialFavorite={property.isFavorite} />
      </div>
      <div className="flex flex-1 flex-col gap-2 p-5">
        <Heading className="line-clamp-2 text-lg leading-snug font-bold">
          {/* The card's only link, so the card draws its focus ring (has-[a:focus-visible]). */}
          <Link
            href={propertyHref(property.slug)}
            className="after:absolute after:inset-0 focus-visible:outline-none"
          >
            {property.title}
          </Link>
        </Heading>
        <p className="flex min-w-0 items-center gap-1.5 text-sm text-fg-muted">
          <PinIcon className="size-4 shrink-0" />
          <span className="truncate">{property.locationLabel}</span>
        </p>
        <PropertyPrice price={property.price} />
        <div className="mt-auto pt-2">
          <PropertyFacts
            bedrooms={property.bedrooms}
            bathrooms={property.bathrooms}
            floorArea={property.floorArea}
          />
        </div>
      </div>
    </article>
  );
}
