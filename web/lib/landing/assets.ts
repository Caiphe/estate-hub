/**
 * Central image manifest for the public landing page. Sections import images from here,
 * never from `assets/` directly, so swapping a placeholder for an approved photograph is a
 * one-line change. Requirements are documented in `assets/images/README.md`.
 */

import heroImage from "../../assets/images/header-banner.png";
import investmentBannerPlaceholder from "../../assets/images/placeholders/investment-banner.svg";
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
  hero: { aspectRatio: 16 / 9, minWidth: 1600, minHeight: 900 },
  propertyCard: { aspectRatio: 16 / 9, minWidth: 960, minHeight: 540 },
  investmentBanner: { aspectRatio: 3, minWidth: 2400, minHeight: 800 },
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
    alt: "Modern two-storey villa with floor-to-ceiling windows beside a pool at sunset",
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
    status: "placeholder",
    src: investmentBannerPlaceholder,
    alt: "",
  },
} as const satisfies Record<string, ManifestEntry>;

export type LandingAssetKey = keyof typeof LANDING_ASSETS;
