"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { VisuallyHidden } from "@/components/visually-hidden";
import { LANDING_SECTION_IDS } from "@/lib/landing/navigation";
import {
  ANY,
  buildSearchUrl,
  isPriceBand,
  isPropertyType,
  SEARCH_PATH,
  type SearchQuery,
  validateLocation,
} from "@/lib/landing/search";
import type { ListingType } from "@/lib/landing/types";

import { SearchIcon } from "./icons";
import { PopularSearches } from "./popular-searches";
import { LocationField, PriceRangeSelect, PropertyTypeSelect } from "./search-fields";
import { SearchTabs } from "./search-tabs";

const ERROR_ID = "search-location-error";

/**
 * Floating search panel. Without JavaScript it is a plain GET form to the results route;
 * with JavaScript it validates first and navigates to a clean URL with "any" values omitted.
 */
export function PropertySearch({ initialQuery }: { initialQuery: SearchQuery }) {
  const [listing, setListing] = useState(initialQuery.listing);
  const [location, setLocation] = useState(initialQuery.location);
  const [type, setType] = useState(initialQuery.type);
  const [price, setPrice] = useState(initialQuery.price);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const locationRef = useRef<HTMLInputElement>(null);

  // Returning through the back/forward cache restores this page mid-submit; re-enable it.
  useEffect(() => {
    const reset = (event: PageTransitionEvent) => event.persisted && setSubmitting(false);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  function changeListing(next: ListingType) {
    setListing(next);
    if (!isPriceBand(next, price)) setPrice(ANY);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = location.trim();
    const problem = validateLocation(trimmed);
    if (problem) {
      setError(problem);
      locationRef.current?.focus();
      return;
    }
    setSubmitting(true);
    window.location.assign(
      buildSearchUrl({ listing, location: trimmed, type, price }),
    );
  }

  return (
    // scroll-mt leaves breathing room above the panel when reached through "#search".
    <div id={LANDING_SECTION_IDS.search} className="grid max-w-search scroll-mt-6 gap-4">
      <form
        role="search"
        aria-label="Property search"
        action={SEARCH_PATH}
        method="get"
        noValidate
        onSubmit={handleSubmit}
      >
        <SearchTabs value={listing} onChange={changeListing} />
        <div className="grid gap-2 rounded-lg rounded-tl-none bg-surface p-3 shadow-floating">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_auto]">
            <LocationField
              value={location}
              error={error}
              errorId={ERROR_ID}
              inputRef={locationRef}
              onChange={(value) => {
                setLocation(value);
                setError(null);
              }}
            />
            <PropertyTypeSelect
              value={type}
              onChange={(value) => setType(isPropertyType(value) ? value : ANY)}
            />
            <PriceRangeSelect listing={listing} value={price} onChange={setPrice} />
            {/* Square icon button at desktop; a full-width labelled button below it. The
                accessible name stays "Search properties" (or "Searching…") throughout. */}
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex h-12 items-center justify-center gap-2 rounded-sm bg-brand px-5 font-bold text-fg-inverse transition duration-150 ease-standard hover:bg-brand-strong motion-safe:active:scale-96 disabled:cursor-progress disabled:bg-fg-muted md:col-span-2 lg:col-span-1 lg:w-12 lg:px-0"
            >
              <SearchIcon />
              <span className="lg:sr-only">{submitting ? "Searching…" : "Search"}</span>
              {!submitting && <VisuallyHidden> properties</VisuallyHidden>}
            </button>
          </div>
          {error && (
            <p id={ERROR_ID} className="px-1 text-sm font-medium text-danger">
              {error}
            </p>
          )}
        </div>
      </form>
      <PopularSearches listing={listing} />
    </div>
  );
}
