import { LISTING_MODES } from "@/lib/landing/search";
import type { ListingType } from "@/lib/landing/types";

type SearchTabsProps = {
  value: ListingType;
  onChange: (value: ListingType) => void;
};

/**
 * Buy / Rent / Invest. All three modes share one set of fields, so this is a radio group
 * styled as tabs rather than a tablist: one tab stop, arrow keys move between modes, and
 * the choice submits as `listing` even without JavaScript. The selected tab is underlined
 * as well as filled, so the state never rests on colour (forced-colors mode drops fills).
 */
export function SearchTabs({ value, onChange }: SearchTabsProps) {
  return (
    <fieldset className="flex">
      <legend className="sr-only">Looking to</legend>
      {LISTING_MODES.map((mode) => (
        <label
          key={mode.value}
          className="relative inline-flex min-h-11 flex-1 cursor-pointer items-center justify-center bg-surface px-6 font-semibold text-fg transition-colors duration-150 ease-standard first-of-type:rounded-tl-md last-of-type:rounded-tr-md hover:bg-brand-subtle has-checked:bg-brand has-checked:text-fg-inverse has-checked:underline has-checked:decoration-2 has-checked:underline-offset-6 has-focus-visible:z-1 has-focus-visible:outline-3 has-focus-visible:outline-offset-2 has-focus-visible:outline-brand sm:flex-none"
        >
          {/* The native radio stays for keyboard and form semantics; the label is the tab. */}
          <input
            type="radio"
            name="listing"
            value={mode.value}
            checked={value === mode.value}
            onChange={() => onChange(mode.value)}
            className="absolute inset-0 m-0 cursor-pointer opacity-0"
          />
          {mode.label}
        </label>
      ))}
    </fieldset>
  );
}
