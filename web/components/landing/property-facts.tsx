import type { ReactNode } from "react";

import { VisuallyHidden } from "@/components/visually-hidden";
import { formatArea, formatCount, hasFact } from "@/lib/landing/property";
import type { PropertySummary } from "@/lib/landing/types";

import { AreaIcon, BathIcon, BedIcon } from "./icons";

type Fact = { key: string; icon: ReactNode; visible: string; spoken?: string };

/** Bedrooms, bathrooms, and floor area; facts that are missing or zero are left out. */
type PropertyFactsProps = Pick<PropertySummary, "bedrooms" | "bathrooms" | "floorArea">;

export function PropertyFacts({ bedrooms, bathrooms, floorArea }: PropertyFactsProps) {
  const facts: Fact[] = [];
  if (hasFact(bedrooms)) {
    facts.push({
      key: "beds",
      icon: <BedIcon className="size-4.5" />,
      visible: formatCount(bedrooms, "bed", "beds"),
    });
  }
  if (hasFact(bathrooms)) {
    facts.push({
      key: "baths",
      icon: <BathIcon className="size-4.5" />,
      visible: formatCount(bathrooms, "bath", "baths"),
    });
  }
  if (floorArea && hasFact(floorArea.value)) {
    const area = formatArea(floorArea);
    facts.push({
      key: "area",
      icon: <AreaIcon className="size-4.5" />,
      visible: area.short,
      spoken: area.long,
    });
  }
  if (facts.length === 0) return null;

  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-fg-muted">
      {facts.map((fact) => (
        <li key={fact.key} className="flex items-center gap-1.5">
          {fact.icon}
          {fact.spoken ? (
            <>
              <span aria-hidden="true">{fact.visible}</span>
              <VisuallyHidden>{fact.spoken}</VisuallyHidden>
            </>
          ) : (
            fact.visible
          )}
        </li>
      ))}
    </ul>
  );
}
