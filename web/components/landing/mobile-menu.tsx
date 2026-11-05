"use client";

import type { MouseEvent } from "react";

import { HEADER_ACTIONS } from "@/lib/landing/navigation";

import { ActionLink } from "./action-link";
import { CloseIcon, MenuIcon } from "./icons";
import { PrimaryNavigation } from "./primary-navigation";

const MENU_ID = "site-menu";

/**
 * Below the desktop breakpoint, navigation and actions move into a native popover: the
 * browser handles opening, Escape, outside clicks, and returning focus, even without
 * JavaScript. Script only closes it after a link is followed within this page.
 */
export function MobileMenu({
  currentHref,
  signedIn = false,
}: {
  currentHref?: string;
  signedIn?: boolean;
}) {
  function closeOnLink(event: MouseEvent<HTMLDivElement>) {
    if ((event.target as Element).closest("a"))
      event.currentTarget.hidePopover();
  }

  return (
    <div className="group lg:hidden">
      <button
        type="button"
        popoverTarget={MENU_ID}
        className="inline-grid size-11 place-items-center rounded-sm border-[1.5px] border-line bg-surface text-fg transition-colors duration-150 ease-standard hover:bg-brand-subtle"
      >
        <MenuIcon className="group-has-[:popover-open]:hidden" />
        <CloseIcon className="hidden group-has-[:popover-open]:block" />
        <span className="sr-only">Menu</span>
      </button>
      {/* Not a landmark of its own: the <nav> inside carries the "Primary" label. */}
      <div
        id={MENU_ID}
        popover="auto"
        onClick={closeOnLink}
        className="inset-x-(--gutter) top-(--site-header-height) m-0 h-fit w-auto rounded-lg bg-surface p-4 text-fg shadow-floating backdrop:bg-fg/20"
      >
        <PrimaryNavigation layout="stack" currentHref={currentHref} />
        <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
          {/* Signed-in visitors reach their account through the icon beside the menu. */}
          {signedIn ? null : (
            <ActionLink href={HEADER_ACTIONS.logIn.href} variant="secondary">
              {HEADER_ACTIONS.logIn.label}
            </ActionLink>
          )}
          <ActionLink href={HEADER_ACTIONS.getStarted.href} variant="primary">
            {HEADER_ACTIONS.getStarted.label}
          </ActionLink>
        </div>
      </div>
    </div>
  );
}
