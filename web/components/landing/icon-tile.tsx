import type { LandingIconName } from "@/lib/landing/types";

import { LandingIcon } from "./icons";

/** Mint tile holding one decorative line icon; shared by the strip and process steps. */
export function IconTile({ name }: { name: LandingIconName }) {
  return (
    <span className="inline-grid size-11 shrink-0 place-items-center rounded-sm bg-brand-subtle text-brand">
      <LandingIcon name={name} className="size-6" />
    </span>
  );
}
