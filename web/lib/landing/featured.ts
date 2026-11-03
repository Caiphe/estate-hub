/**
 * The single boundary between the featured-properties section and its data. Today it
 * returns fixtures; when the listings API exists, only this function changes: fetch,
 * validate, and map the response to `PropertySummary`.
 */

import { FEATURED_PROPERTIES } from "./content";
import type { PropertySummary } from "./types";

export type FeaturedListings = {
  properties: readonly PropertySummary[];
  /** True while the listings are illustrative fixtures rather than approved real listings. */
  isSample: boolean;
};

export async function getFeaturedProperties(): Promise<FeaturedListings> {
  return { properties: FEATURED_PROPERTIES, isSample: true };
}
