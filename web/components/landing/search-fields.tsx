import type { Ref } from "react";

import { ANY, LOCATION_MAX, PRICE_BANDS, PROPERTY_TYPES } from "@/lib/landing/search";
import type { ListingType } from "@/lib/landing/types";

import { ChevronDownIcon, PinIcon } from "./icons";

const CONTROL =
  "h-12 w-full rounded-sm border border-line bg-surface text-sm font-medium text-fg transition-colors duration-150 ease-standard hover:border-fg-muted";

type LocationFieldProps = {
  value: string;
  error: string | null;
  errorId: string;
  inputRef: Ref<HTMLInputElement>;
  onChange: (value: string) => void;
};

export function LocationField({ value, error, errorId, inputRef, onChange }: LocationFieldProps) {
  return (
    <div className="relative flex items-center md:col-span-2 lg:col-span-1">
      <label htmlFor="search-location" className="sr-only">
        Location
      </label>
      <PinIcon className="pointer-events-none absolute left-4 text-fg-muted" />
      <input
        ref={inputRef}
        id="search-location"
        name="location"
        type="text"
        placeholder="Enter a location"
        maxLength={LOCATION_MAX}
        autoComplete="off"
        enterKeyHint="search"
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={`${CONTROL} pr-4 pl-11 placeholder:text-fg-muted aria-invalid:border-danger`}
      />
    </div>
  );
}

type SelectFieldProps = {
  id: string;
  name: string;
  label: string;
  value: string;
  options: readonly { value: string; label: string }[];
  anyLabel: string;
  onChange: (value: string) => void;
};

function SelectField({ id, name, label, value, options, anyLabel, onChange }: SelectFieldProps) {
  return (
    <div className="relative flex items-center">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <select
        id={id}
        name={name}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`${CONTROL} cursor-pointer appearance-none pr-11 pl-4`}
      >
        <option value={ANY}>{anyLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDownIcon className="pointer-events-none absolute right-4" />
    </div>
  );
}

export function PropertyTypeSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <SelectField
      id="search-type"
      name="type"
      label="Property type"
      anyLabel="Any property type"
      value={value}
      options={PROPERTY_TYPES}
      onChange={onChange}
    />
  );
}

type PriceRangeSelectProps = {
  listing: ListingType;
  value: string;
  onChange: (value: string) => void;
};

/** Bands follow the listing mode: rent is monthly, buy and invest are purchase prices. */
export function PriceRangeSelect({ listing, value, onChange }: PriceRangeSelectProps) {
  return (
    <SelectField
      id="search-price"
      name="price"
      label="Price range"
      anyLabel="Any price"
      value={value}
      options={PRICE_BANDS[listing]}
      onChange={onChange}
    />
  );
}
