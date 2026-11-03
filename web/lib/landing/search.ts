/**
 * Property-search URL contract, shared by the landing-page form and the future results
 * route. Query strings are untrusted input: `parseSearchQuery` keeps only values it
 * recognizes and falls back to defaults for everything else.
 *
 *   /properties?listing=sale&location=Lekki&type=villa&price=3m-5m
 *
 * `listing` is always present; the other parameters are omitted when they mean "any".
 */

import { characterCount } from "@/lib/format";

import { DISPLAY_CURRENCY, formatPrice } from "./property";

import type { ListingType } from "./types";

export const SEARCH_PATH = "/properties";
export const LOCATION_MAX = 80;
// Letters (any script), combining marks, digits, spaces, and common place-name punctuation.
const LOCATION_PATTERN = /^[\p{L}\p{M}\p{N} ,.'’-]+$/u;

export const ANY = "any";

export const LISTING_MODES: readonly { value: ListingType; label: string }[] = [
  { value: "sale", label: "Buy" },
  { value: "rent", label: "Rent" },
  { value: "investment", label: "Invest" },
];

export const PROPERTY_TYPES = [
  { value: "apartment", label: "Apartments" },
  { value: "house", label: "Houses" },
  { value: "villa", label: "Villas" },
  { value: "commercial", label: "Commercial" },
  { value: "land", label: "Land" },
] as const;

export type PropertyType = (typeof PROPERTY_TYPES)[number]["value"];

export type PriceBand = { value: string; label: string };

/** Rand amount as a label, formatted exactly like listing prices: "R 1 000 000". */
const rand = (amount: string) => formatPrice({ amount, currency: DISPLAY_CURRENCY }) ?? amount;

const PURCHASE_BANDS: readonly PriceBand[] = [
  { value: "under-1m", label: `Under ${rand("1000000")}` },
  { value: "1m-3m", label: `${rand("1000000")} – ${rand("3000000")}` },
  { value: "3m-5m", label: `${rand("3000000")} – ${rand("5000000")}` },
  { value: "over-5m", label: `Over ${rand("5000000")}` },
];

/** Rent is quoted per month, so it needs its own scale. */
export const PRICE_BANDS: Record<ListingType, readonly PriceBand[]> = {
  sale: PURCHASE_BANDS,
  investment: PURCHASE_BANDS,
  rent: [
    { value: "under-10k", label: `Under ${rand("10000")} / month` },
    { value: "10k-20k", label: `${rand("10000")} – ${rand("20000")} / month` },
    { value: "20k-40k", label: `${rand("20000")} – ${rand("40000")} / month` },
    { value: "over-40k", label: `Over ${rand("40000")} / month` },
  ],
};

export type SearchQuery = {
  listing: ListingType;
  /** Trimmed; "" means any location. */
  location: string;
  type: PropertyType | typeof ANY;
  /** A value from `PRICE_BANDS[listing]`, or "any". */
  price: string;
};

export const DEFAULT_SEARCH: SearchQuery = { listing: "sale", location: "", type: ANY, price: ANY };

type RawParams = URLSearchParams | Record<string, string | string[] | undefined>;

function first(params: RawParams, key: string): string | undefined {
  const value = params instanceof URLSearchParams ? params.get(key) : params[key];
  return (Array.isArray(value) ? value[0] : value) ?? undefined;
}

export function isListingType(value: unknown): value is ListingType {
  return LISTING_MODES.some((mode) => mode.value === value);
}

export function isPropertyType(value: unknown): value is PropertyType {
  return PROPERTY_TYPES.some((type) => type.value === value);
}

export function isPriceBand(listing: ListingType, value: unknown): boolean {
  return PRICE_BANDS[listing].some((band) => band.value === value);
}

/** Error message for a location, or null when it is acceptable. Expects trimmed input. */
export function validateLocation(location: string): string | null {
  if (!location) return null;
  if (characterCount(location) > LOCATION_MAX) return `Use at most ${LOCATION_MAX} characters.`;
  if (!LOCATION_PATTERN.test(location)) {
    return "Use letters, numbers, spaces, commas, periods, apostrophes, and hyphens only.";
  }
  return null;
}

/** Reads a query string, discarding anything malformed rather than trusting it. */
export function parseSearchQuery(params: RawParams): SearchQuery {
  const listingValue = first(params, "listing");
  const listing = isListingType(listingValue) ? listingValue : DEFAULT_SEARCH.listing;

  const location = (first(params, "location") ?? "").trim();
  const type = first(params, "type");
  const price = first(params, "price");

  return {
    listing,
    location: validateLocation(location) === null ? location : "",
    type: isPropertyType(type) ? type : ANY,
    price: isPriceBand(listing, price) ? (price as string) : ANY,
  };
}

/** Builds the results URL, omitting parameters that mean "any". */
export function buildSearchUrl(query: Partial<SearchQuery> = {}): string {
  const { listing, location, type, price } = { ...DEFAULT_SEARCH, ...query };
  const params = new URLSearchParams({ listing });

  const trimmed = location.trim();
  if (trimmed) params.set("location", trimmed);
  if (type !== ANY) params.set("type", type);
  if (price !== ANY && isPriceBand(listing, price)) params.set("price", price);

  return `${SEARCH_PATH}?${params.toString()}`;
}
