"use client";

import Image from "next/image";
import { useState } from "react";

import type { ImageAsset } from "@/lib/landing/types";

import { HouseIcon } from "./icons";

const SIZES = "(min-width: 64rem) 24rem, (min-width: 40rem) 50vw, 100vw";

/**
 * Fixed 16:9 frame so every card keeps the same image height. The tinted frame shows
 * while the photo loads; if it fails, a labelled placeholder takes its place.
 */
export function PropertyImage({ image }: { image: ImageAsset }) {
  const [failed, setFailed] = useState(false);

  return (
    <div className="relative aspect-video overflow-hidden bg-surface-tint">
      {failed ? (
        <div
          role="img"
          aria-label={image.alt || "Photo unavailable"}
          className="grid size-full place-content-center justify-items-center gap-2 text-sm text-fg-muted"
        >
          <HouseIcon className="size-8" />
          <span aria-hidden="true">Photo unavailable</span>
        </div>
      ) : (
        <Image
          src={image.src}
          alt={image.alt}
          fill
          sizes={SIZES}
          onError={() => setFailed(true)}
          className="object-cover transition-transform duration-300 ease-standard motion-safe:group-hover:scale-105"
        />
      )}
    </div>
  );
}
