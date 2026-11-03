import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { FeaturedProperties } from "@/components/landing/featured-properties";
import { PropertyCard } from "@/components/landing/property-card";
import { FEATURED_PROPERTIES } from "@/lib/landing/content";
import type { PropertySummary } from "@/lib/landing/types";

export const metadata: Metadata = {
  title: "Property card preview",
  robots: { index: false, follow: false },
};

const [duplex, palmHeights] = FEATURED_PROPERTIES;

/** Edge cases the reference cards do not exercise. */
const EDGE_CASES: readonly PropertySummary[] = [
  {
    ...duplex,
    id: "edge-long-text",
    slug: "edge-long-text",
    title:
      "Expansive Five-Bedroom Waterfront Residence with Private Jetty, Rooftop Terrace, and Staff Quarters",
    locationLabel: "Plot 14, Admiralty Way, Lekki Phase 1, Eti-Osa, Lagos State",
    isFavorite: true,
  },
  {
    ...palmHeights,
    id: "edge-no-facts",
    slug: "edge-no-facts",
    title: "Serviced Land Plot",
    listingType: "investment",
    price: { amount: "85000.50", currency: "NGN" },
    bedrooms: undefined,
    bathrooms: undefined,
    floorArea: undefined,
  },
  {
    ...duplex,
    id: "edge-broken-image",
    slug: "edge-broken-image",
    title: "Listing with a Missing Photo",
    image: { src: "/missing-property-photo.png", alt: "Front of the listing" },
  },
];

/**
 * Development-only gallery for the property card (the three reference listings plus edge
 * cases, at card width) and the featured section's loading, empty, and error states.
 * Production builds return 404.
 */
export default function PropertyCardPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <main className="site min-h-screen bg-surface-tint p-10 font-sans text-fg">
      <h1 className="mb-8 text-2xl font-extrabold tracking-tight">Property card preview</h1>
      <ul className="flex flex-wrap items-stretch gap-6">
        {[...FEATURED_PROPERTIES, ...EDGE_CASES].map((property) => (
          <li key={property.id} className="w-96">
            <PropertyCard property={property} headingLevel="h2" />
          </li>
        ))}
      </ul>
      {(["loading", "empty", "error"] as const).map((variant) => (
        <div key={variant} data-variant={variant} className="mt-12 rounded-lg bg-surface">
          <FeaturedProperties
            id={`featured-${variant}`}
            state={variant === "empty" ? { status: "ready", properties: [] } : { status: variant }}
          />
        </div>
      ))}
    </main>
  );
}
