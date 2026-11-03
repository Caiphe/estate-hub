/** Fixture copy for the public landing page, typed so sections stay data-driven. */

import { LANDING_ASSETS } from "./assets";
import { LANDING_SECTION_IDS } from "./navigation";
import type { FooterLinkGroup, ProcessStep, PropertySummary, SocialLink, ValueProposition } from "./types";

export const VALUE_PROPOSITIONS: readonly ValueProposition[] = [
  {
    id: "verified",
    icon: "home-check",
    title: "Verified properties",
    description: "Trusted and vetted listings.",
  },
  {
    id: "invest",
    icon: "chart",
    title: "Invest with confidence",
    description: "Track returns and grow wealth.",
  },
  {
    id: "portfolio",
    icon: "layers",
    title: "Manage your portfolio",
    description: "Keep properties in one place.",
  },
  {
    id: "secure",
    icon: "shield",
    title: "Secure and reliable",
    description: "Protect property and investment data.",
  },
];

/** The three reference listings; prices are decimal strings, as the API will send them. */
export const FEATURED_PROPERTIES: readonly PropertySummary[] = [
  {
    id: "prop-modern-duplex-lekki",
    slug: "modern-duplex-lekki",
    title: "Modern Duplex in Lekki",
    locationLabel: "Lekki, Lagos",
    listingType: "sale",
    price: { amount: "4500000.00", currency: "ZAR" },
    image: LANDING_ASSETS.modernDuplex,
    bedrooms: 4,
    bathrooms: 4,
    floorArea: { value: 5200, unit: "sqft" },
  },
  {
    id: "prop-palm-heights-ikoyi",
    slug: "palm-heights-apartments-ikoyi",
    title: "Palm Heights Apartments",
    locationLabel: "Ikoyi, Lagos",
    listingType: "rent",
    price: { amount: "35000.00", currency: "ZAR", period: "month" },
    image: LANDING_ASSETS.palmHeights,
    bedrooms: 3,
    bathrooms: 3,
    floorArea: { value: 2100, unit: "sqft" },
  },
  {
    id: "prop-victoria-commercial-plaza",
    slug: "victoria-commercial-plaza",
    title: "Victoria Commercial Plaza",
    locationLabel: "Victoria Island, Lagos",
    listingType: "investment",
    price: { amount: "12000000.00", currency: "ZAR" },
    image: LANDING_ASSETS.victoriaPlaza,
    // Commercial stock: no bedroom or bathroom counts.
    floorArea: { value: 12000, unit: "sqft" },
  },
];

/** "How it works", in order; the list position is the step number. */
export const PROCESS_STEPS: readonly ProcessStep[] = [
  {
    id: "account",
    icon: "user",
    title: "Create an account",
    description: "Sign up and set up a profile.",
  },
  {
    id: "discover",
    icon: "search",
    title: "Discover opportunities",
    description: "Browse verified properties that fit your goals.",
  },
  {
    id: "invest",
    icon: "trend-up",
    title: "Invest and grow",
    description: "Invest with confidence and track portfolio performance.",
  },
];

/**
 * Footer navigation. Items with `planned: true` have no page yet; they render as text
 * marked "Soon" so nothing ships as a dead link. Give each one an `href` once its page
 * exists. Terms of service and Privacy policy must exist before public launch.
 */
export const FOOTER_LINK_GROUPS: readonly FooterLinkGroup[] = [
  {
    heading: "Platform",
    links: [
      { label: "Buy property", href: `/?listing=sale#${LANDING_SECTION_IDS.search}` },
      { label: "Rent property", href: `/?listing=rent#${LANDING_SECTION_IDS.search}` },
      { label: "Invest", href: `/#${LANDING_SECTION_IDS.invest}` },
      { label: "Manage portfolio", planned: true },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About us", href: `/#${LANDING_SECTION_IDS.howItWorks}` },
      { label: "Careers", planned: true },
      { label: "Contact", planned: true },
      { label: "Blog", planned: true },
    ],
  },
  {
    heading: "Support",
    links: [
      { label: "Help center", planned: true },
      { label: "FAQs", planned: true },
      { label: "Terms of service", planned: true },
      { label: "Privacy policy", planned: true },
    ],
  },
];

/**
 * Official social profiles. Empty until real URLs are confirmed: inventing handles could
 * send visitors to someone else's account. Add entries such as
 * `{ platform: "linkedin", label: "EstateHub on LinkedIn", href: "https://…" }`.
 */
export const SOCIAL_LINKS: readonly SocialLink[] = [];
