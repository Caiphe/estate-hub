/**
 * Central image manifest for the public landing page. Sections import images from here,
 * never from `assets/` directly, so swapping a placeholder for an approved photograph is a
 * one-line change. Requirements are documented in `assets/images/README.md`.
 */

import heroImage from "../../assets/images/header-banner.jpg";
import investmentBannerImage from "../../assets/images/header-banner-1.png";
import propertyCardPlaceholder from "../../assets/images/placeholders/property-card.svg";

import type { ImageAsset } from "./types";

export type AssetSlot = "hero" | "propertyCard" | "investmentBanner";

export type AssetRequirement = {
  /** Width ÷ height of the crop the layout reserves. */
  aspectRatio: number;
  minWidth: number;
  minHeight: number;
};

export const ASSET_REQUIREMENTS = {
  // Always cropped to its box (≈1.2:1 at desktop, 16:9 below), so 3:2 covers both.
  hero: { aspectRatio: 3 / 2, minWidth: 2400, minHeight: 1600 },
  propertyCard: { aspectRatio: 16 / 9, minWidth: 960, minHeight: 540 },
  // Fills only the banner's right side (≈2.5:1 at desktop, 16:9 stacked), cropped to fit.
  investmentBanner: { aspectRatio: 16 / 9, minWidth: 1600, minHeight: 900 },
} as const satisfies Record<AssetSlot, AssetRequirement>;

export type ManifestEntry = ImageAsset & {
  slot: AssetSlot;
  /** "placeholder" entries are listed as asset gaps until an approved image replaces them. */
  status: "final" | "placeholder";
};

export const LANDING_ASSETS = {
  hero: {
    slot: "hero",
    status: "final",
    src: heroImage,
    alt: "A family sharing mugs of tea on the living-room rug of a bright, airy home",
  },
  modernDuplex: {
    slot: "propertyCard",
    status: "placeholder",
    src: propertyCardPlaceholder,
    alt: "Image placeholder for Modern Duplex in Lekki",
  },
  palmHeights: {
    slot: "propertyCard",
    status: "placeholder",
    src: propertyCardPlaceholder,
    alt: "Image placeholder for Palm Heights Apartments",
  },
  victoriaPlaza: {
    slot: "propertyCard",
    status: "placeholder",
    src: propertyCardPlaceholder,
    alt: "Image placeholder for Victoria Commercial Plaza",
  },
  // Decorative: the banner heading and copy carry the meaning.
  investmentBanner: {
    slot: "investmentBanner",
    status: "final",
    src: investmentBannerImage,
    alt: "",
  },
} as const satisfies Record<string, ManifestEntry>;

export type LandingAssetKey = keyof typeof LANDING_ASSETS;
