import Image from "next/image";

import duskImage from "@/assets/images/auth-banner.png";
import { BrandMark } from "@/components/landing/brand-mark";
import { IconTile } from "@/components/landing/icon-tile";
import type { LandingIconName } from "@/lib/landing/types";

export type SignInHighlight = { id: string; icon: LandingIconName; label: string };

export const SIGN_IN_HIGHLIGHTS: readonly SignInHighlight[] = [
  { id: "discover", icon: "chart", label: "Discover verified properties" },
  { id: "invest", icon: "layers", label: "Invest and grow your wealth" },
  { id: "manage", icon: "shield", label: "Manage your portfolio securely" },
];

/**
 * The sign-in page's dusk property panel: brand, statement, and value points over a navy
 * overlay. A complementary landmark labelled by its statement, which is a paragraph rather
 * than a heading so the form's "Welcome back" stays the page's first heading. The photograph
 * is decorative; no carousel exists, so there are no carousel dots. The copy steps down with
 * the column: brand and statement in the mobile band and tablet split, supporting copy from
 * lg, and value points only at xl, where the panel takes 55% of the width.
 */
export function MarketingPanel({ highlights = SIGN_IN_HIGHLIGHTS }: { highlights?: readonly SignInHighlight[] }) {
  return (
    <aside
      aria-labelledby="sign-in-statement"
      className="relative isolate overflow-hidden px-(--gutter) pt-6 pb-14 text-fg-inverse md:-mr-(--radius-panel) md:px-10 md:pt-10 md:pb-10 lg:px-12 lg:pt-12 xl:px-20 [&_:focus-visible]:outline-sunset"
    >
      {/* Split, the photo covers a full-height column, so the width it needs follows the
          height: about 1.1 times it, the source's aspect ratio. */}
      <Image
        src={duskImage}
        alt=""
        fill
        preload
        sizes="(min-width: 80rem) max(55vw, 110vh), (min-width: 48rem) max(45vw, 110vh), 100vw"
        className="-z-20 object-cover object-[70%_center]"
      />
      {/* Even navy over the whole mobile band, where the copy spans it; once split, a scrim
          behind the copy that clears toward the lit house. */}
      <div className="absolute inset-0 -z-10 bg-dusk/75 md:bg-dusk-scrim" />

      <BrandMark tone="dark" size="lg" />
      <span aria-hidden="true" className="mt-5 block h-1 w-20 rounded-full bg-sunset md:mt-10 xl:mt-14" />
      <p
        id="sign-in-statement"
        className="mt-5 max-w-headline font-serif text-2xl leading-tight font-semibold tracking-tight text-balance md:mt-8 md:text-editorial xl:mt-10"
      >
        Your gateway to smarter <span className="text-sunset">real estate</span>
      </p>
      <p className="mt-5 hidden max-w-hero-copy text-xl lg:block">
        Buy, rent, invest, and manage properties all in one place.
      </p>
      <ul className="mt-7 hidden gap-2.5 text-lg xl:grid">
        {highlights.map((item) => (
          <li key={item.id} className="flex items-center gap-4">
            <IconTile name={item.icon} tone="gold" />
            {item.label}
          </li>
        ))}
      </ul>
    </aside>
  );
}
