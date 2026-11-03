import Image from "next/image";

import { LANDING_ASSETS } from "@/lib/landing/assets";

/**
 * The hero photograph, filling the right of the hero to its outer edge. It is absolutely
 * positioned inside a box the layout sizes, so loading it can never shift content. This is
 * the page's largest contentful image, hence the preload.
 */
export function HeroMedia() {
  const { src, alt } = LANDING_ASSETS.hero;
  return (
    <div className="hero-media">
      <Image
        src={src}
        alt={alt}
        fill
        preload
        sizes="(min-width: 60rem) 60vw, 100vw"
        className="hero-media-image"
      />
    </div>
  );
}
