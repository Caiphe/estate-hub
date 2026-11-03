import { LISTING_LABELS } from "@/lib/landing/property";
import type { ListingType } from "@/lib/landing/types";

const TONES: Record<ListingType, string> = {
  sale: "bg-brand-subtle text-brand-strong",
  rent: "bg-surface text-fg",
  investment: "bg-accent text-fg",
};

/** Transaction label overlaid on the card image; the text, not the tint, carries meaning. */
export function PropertyBadge({ listingType }: { listingType: ListingType }) {
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${TONES[listingType]}`}>
      {LISTING_LABELS[listingType]}
    </span>
  );
}
