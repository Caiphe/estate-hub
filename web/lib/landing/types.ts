/**
 * Public landing-page data shapes. Sections render fixture data today; the property types
 * mirror what a listings API response can map onto, so components will not need redesign
 * once that API exists.
 */

import type { StaticImageData } from "next/image";

/** An image plus its accessible text. `alt` is "" only for purely decorative crops. */
export type ImageAsset = {
  src: StaticImageData | string;
  alt: string;
  /** Required for string sources so next/image can reserve space; static imports carry their own. */
  width?: number;
  height?: number;
};

export type NavLink = {
  label: string;
  href: string;
};

/** Icon names the landing page draws; each maps to one repo-native SVG. */
export type LandingIconName =
  | "home-check"
  | "chart"
  | "layers"
  | "shield"
  | "user"
  | "search"
  | "trend-up";

export type ListingType = "sale" | "rent" | "investment";

export type BillingPeriod = "month" | "year";

/**
 * A price exactly as the API serializes a decimal: a string such as "450000.00". It is
 * formatted straight from the string and never converted to a float.
 */
export type Price = {
  amount: string;
  /** ISO 4217 code, e.g. "ZAR". */
  currency: string;
  /** Set for recurring prices such as rent; omitted for one-off prices. */
  period?: BillingPeriod;
};

export type AreaUnit = "sqft" | "sqm";

export type FloorArea = {
  value: number;
  unit: AreaUnit;
};

/** The card-level view of a listing. Facts that do not apply (e.g. bedrooms on a plaza) are omitted. */
export type PropertySummary = {
  id: string;
  /** URL segment for the future detail route, /properties/{slug}. */
  slug: string;
  title: string;
  /** Display-ready, e.g. "Lekki, Lagos". */
  locationLabel: string;
  listingType: ListingType;
  price: Price;
  image: ImageAsset;
  bedrooms?: number;
  bathrooms?: number;
  floorArea?: FloorArea;
  /** Presentation only; favorites are not persisted yet. */
  isFavorite?: boolean;
};

export type ValueProposition = {
  id: string;
  icon: LandingIconName;
  title: string;
  description: string;
};

export type ProcessStep = {
  id: string;
  icon: LandingIconName;
  title: string;
  description: string;
};

/** A destination that does not exist yet. Rendered as text marked "Soon", never as a dead link. */
export type PlannedLink = {
  label: string;
  planned: true;
};

export type FooterLink = NavLink | PlannedLink;

export type FooterLinkGroup = {
  heading: string;
  links: readonly FooterLink[];
};

export type SocialPlatform = "linkedin" | "x" | "facebook" | "instagram" | "youtube";

export type SocialLink = {
  platform: SocialPlatform;
  /** Accessible name, e.g. "EstateHub on LinkedIn". */
  label: string;
  href: string;
};
