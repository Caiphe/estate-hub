/**
 * Display helpers for property summaries.
 *
 * Money stays a decimal string end to end: Intl.NumberFormat formats numeric strings
 * exactly (ECMA-402 v3), so no amount ever passes through floating point. The locale is
 * fixed to South African English rather than taken from the browser, so server and client
 * render identical text: "R 4 500 000", "R 1 250,50", "5 200 sqft" (spaces are U+00A0).
 */

import type { FloorArea, ListingType, Price } from "./types";

export const DISPLAY_LOCALE = "en-ZA";

/** Currency for listings and search bands. */
export const DISPLAY_CURRENCY = "ZAR";

/** Up to 18 integer digits and an optional 1–2 digit fraction; no sign, no exponent. */
const DECIMAL_AMOUNT = /^\d{1,18}(\.\d{1,2})?$/;

type DecimalString = `${number}`;

export function isDecimalAmount(value: string): value is DecimalString {
  return DECIMAL_AMOUNT.test(value);
}

const priceFormatters = new Map<string, Intl.NumberFormat>();

function priceFormatter(currency: string): Intl.NumberFormat {
  let formatter = priceFormatters.get(currency);
  if (!formatter) {
    formatter = new Intl.NumberFormat(DISPLAY_LOCALE, {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      // "R 450 000" rather than "R 450 000,00"; real cents still show ("R 1 250,50").
      trailingZeroDisplay: "stripIfInteger",
    });
    priceFormatters.set(currency, formatter);
  }
  return formatter;
}

/** "R 4 500 000", or null when the amount or currency is malformed. */
export function formatPrice(price: Pick<Price, "amount" | "currency">): string | null {
  if (!isDecimalAmount(price.amount)) return null;
  try {
    return priceFormatter(price.currency).format(price.amount);
  } catch {
    // Unknown ISO currency code.
    return null;
  }
}

const integerFormatter = new Intl.NumberFormat(DISPLAY_LOCALE, { maximumFractionDigits: 0 });

const AREA_UNITS = {
  sqft: { short: "sqft", long: "square feet" },
  sqm: { short: "m²", long: "square metres" },
} as const;

/** Visible and spoken forms, e.g. "5,200 sqft" / "5,200 square feet". */
export function formatArea(area: FloorArea): { short: string; long: string } {
  const value = integerFormatter.format(area.value);
  const unit = AREA_UNITS[area.unit];
  return { short: `${value} ${unit.short}`, long: `${value} ${unit.long}` };
}

/** "1 bed", "4 beds". */
export function formatCount(count: number, singular: string, plural: string): string {
  return `${integerFormatter.format(count)} ${count === 1 ? singular : plural}`;
}

/** A fact is shown only when it is a positive finite number. */
export function hasFact(value: number | undefined): value is number {
  return value !== undefined && Number.isFinite(value) && value > 0;
}

export const LISTING_LABELS: Record<ListingType, string> = {
  sale: "For sale",
  rent: "For rent",
  investment: "For investment",
};

export function propertyHref(slug: string): string {
  return `/properties/${encodeURIComponent(slug)}`;
}
