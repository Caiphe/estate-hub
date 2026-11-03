import type { ComponentType, SVGProps } from "react";

import type { SocialLink, SocialPlatform } from "@/lib/landing/types";

import { FacebookIcon, InstagramIcon, LinkedInIcon, XIcon, YouTubeIcon } from "./icons";

const ICONS: Record<SocialPlatform, ComponentType<SVGProps<SVGSVGElement>>> = {
  linkedin: LinkedInIcon,
  x: XIcon,
  facebook: FacebookIcon,
  instagram: InstagramIcon,
  youtube: YouTubeIcon,
};

/**
 * Icon links to official profiles. They open in a new tab, so the name says so, and
 * `rel` cuts the opener reference and the referrer. Renders nothing without links.
 */
export function SocialLinks({ links }: { links: readonly SocialLink[] }) {
  if (links.length === 0) return null;
  return (
    <ul role="list" aria-label="EstateHub on social media" className="flex flex-wrap gap-2">
      {links.map((link) => {
        const Icon = ICONS[link.platform];
        return (
          <li key={link.platform}>
            <a
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`${link.label} (opens in a new tab)`}
              className="inline-grid size-11 place-items-center rounded-sm text-fg-inverse/80 transition-colors duration-150 ease-standard hover:bg-fg-inverse/10 hover:text-fg-inverse"
            >
              <Icon />
            </a>
          </li>
        );
      })}
    </ul>
  );
}
