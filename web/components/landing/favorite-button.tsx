"use client";

import { useId, useState } from "react";

import { HeartIcon } from "./icons";

type FavoriteButtonProps = {
  propertyTitle: string;
  initialFavorite?: boolean;
};

/**
 * Temporary, local-only favorite toggle. Nothing is saved: the state resets on reload,
 * and the description says so. Persistence arrives with customer accounts.
 */
export function FavoriteButton({ propertyTitle, initialFavorite = false }: FavoriteButtonProps) {
  const [favorite, setFavorite] = useState(initialFavorite);
  const noteId = useId();

  return (
    <>
      <button
        type="button"
        aria-label={`Favorite ${propertyTitle}`}
        aria-pressed={favorite}
        aria-describedby={noteId}
        onClick={() => setFavorite((value) => !value)}
        className="relative z-10 inline-grid size-10 place-items-center rounded-full bg-surface text-fg shadow-card transition-colors duration-150 ease-standard hover:bg-brand-subtle aria-pressed:text-brand"
      >
        <HeartIcon className={favorite ? "fill-current" : undefined} />
      </button>
      <span id={noteId} hidden>
        Favorites last for this visit only and are not saved.
      </span>
    </>
  );
}
