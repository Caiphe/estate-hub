import Image from "next/image";

import { LANDING_ASSETS } from "@/lib/landing/assets";

/**
 * The hero photograph. Below desktop it is a 16:9 band under the copy; at desktop it fills
 * the right of the hero to its outer edge. Either way the image sits in a box the layout
 * sizes, so loading it never shifts content. It is the page's largest contentful image,
 * hence the preload.
 */
export function HeroMedia() {
  const { src, alt } = LANDING_ASSETS.hero;
  return (
    <div className="hero-media-arrival relative mt-10 aspect-video lg:absolute lg:inset-y-0 lg:right-0 lg:left-5/12 lg:mt-0 lg:aspect-auto">
      <Image
        src={src}
        alt={alt}
        fill
        preload
        sizes="(min-width: 64rem) 60vw, 100vw"
        // Keeps the family in frame: right of centre at desktop (where only the sides are
        // cropped), and high enough on small screens that faces clear the top fade.
        className="hero-media-image object-cover object-[62%_35%]"
      />
      {/* Feathers the photograph into the wash: from above on small screens, from the left
          at desktop, so the seam never cuts behind the copy. */}
      <div className="absolute inset-0 bg-linear-to-b from-surface-tint to-transparent to-25% lg:bg-linear-to-r lg:to-30%" />
      {/* Lightens the strip under the header so desktop navigation keeps 4.5:1 even over the
          darkest foliage (measured worst case 4.7:1, at 1920px). */}
      <div className="absolute inset-x-0 top-0 hidden h-(--site-header-height) bg-linear-to-b from-surface-tint/90 to-transparent lg:block" />
    </div>
  );
}
