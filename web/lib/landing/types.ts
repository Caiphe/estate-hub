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

export type RentPeriod = "month" | "year";

export type Money = {
  /** Whole currency units; avoids float rounding in display. */
  amount: number;
  /** ISO 4217 code, e.g. "USD" or "NGN". */
  currency: string;
};

export type PropertyLocation = {
  area: string;
  city: string;
};

/** The card-level view of a listing. Optional counts are omitted for non-residential stock. */
export type PropertySummary = {
  id: string;
  title: string;
  href: string;
  listingType: ListingType;
  location: PropertyLocation;
  price: Money;
  /** Present only when `listingType` is "rent". */
  rentPeriod?: RentPeriod;
  bedrooms?: number;
  bathrooms?: number;
  floorAreaSqft: number;
  image: ImageAsset;
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

export type FooterLinkGroup = {
  heading: string;
  links: readonly NavLink[];
};

export type SocialPlatform = "linkedin" | "x" | "facebook" | "instagram" | "youtube";

export type SocialLink = {
  platform: SocialPlatform;
  /** Accessible name, e.g. "EstateHub on LinkedIn". */
  label: string;
  href: string;
};
