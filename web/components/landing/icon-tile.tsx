import type { LandingIconName } from "@/lib/landing/types";

import { LandingIcon } from "./icons";

const TONES = {
  mint: "bg-brand-subtle text-brand",
  // Over the dusk photograph on the sign-in page.
  gold: "bg-sunset/50 text-fg-inverse",
} as const;

/** Tile holding one decorative line icon; shared by the strip, process steps, and sign-in panel. */
export function IconTile({ name, tone = "mint" }: { name: LandingIconName; tone?: keyof typeof TONES }) {
  return (
    <span className={`inline-grid size-11 shrink-0 place-items-center rounded-sm ${TONES[tone]}`}>
      <LandingIcon name={name} className="size-6" />
    </span>
  );
}
