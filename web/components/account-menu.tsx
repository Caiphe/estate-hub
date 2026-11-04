"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

import { ChevronDownIcon, LockIcon, SignOutIcon } from "@/components/landing/icons";
import { roleLabel } from "@/components/role-checkboxes";
import type { CurrentUser } from "@/lib/api/types";
import { initials } from "@/lib/format";

const ITEM =
  "flex min-h-11 w-full items-center gap-3 rounded-sm px-3 py-2 text-left font-sans text-sm font-semibold text-fg no-underline hover:bg-canvas";

/**
 * The signed-in user's identity and account actions, as a disclosure: a button that reveals
 * a short list. Opening moves focus to the first item; Escape closes and returns focus to the
 * button; a click outside or tabbing away closes it.
 */
export function AccountMenu({
  user,
  roles,
  onSignOut,
}: {
  user: CurrentUser;
  roles: string[];
  onSignOut: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const firstItemRef = useRef<HTMLAnchorElement>(null);
  const menuId = useId();
  const roleText = roles.length ? roles.map(roleLabel).join(", ") : "No role assigned";

  useEffect(() => {
    if (!open) return;
    firstItemRef.current?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    setOpen(false);
    triggerRef.current?.focus();
  }

  // Only when focus lands somewhere else: Safari does not focus clicked buttons, so a click
  // on an item blurs to nothing and must not close the menu before the click arrives.
  function onBlur(event: FocusEvent<HTMLDivElement>) {
    if (open && event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) {
      setOpen(false);
    }
  }

  return (
    <div ref={rootRef} className="relative ml-auto shrink-0" onKeyDown={onKeyDown} onBlur={onBlur}>
      <button
        ref={triggerRef}
        type="button"
        // Starts with the visible text, so speech users can say what they see.
        aria-label={`${user.fullName}, ${roleText}, account menu`}
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
        className="m-0 flex min-h-11 cursor-pointer items-center gap-3 rounded-md border-0 bg-transparent px-2 py-1.5 text-left font-sans text-fg hover:bg-canvas"
      >
        <span
          aria-hidden="true"
          className="grid size-10 shrink-0 place-items-center rounded-full bg-brand-subtle text-sm font-bold text-brand-strong"
        >
          {initials(user.fullName)}
        </span>
        <span className="grid max-w-56 leading-snug max-sm:hidden">
          <span className="truncate text-sm font-bold">{user.fullName}</span>
          <span className="truncate text-xs text-fg-muted">{roleText}</span>
        </span>
        <ChevronDownIcon
          className={`shrink-0 text-fg-muted transition-transform duration-150 motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div
          id={menuId}
          className="absolute top-[calc(100%+0.5rem)] right-0 z-30 w-72 rounded-lg border border-line bg-surface p-2 shadow-floating"
        >
          <div className="border-b border-line px-3 pt-2 pb-3">
            <p className="m-0 text-sm font-bold">{user.fullName}</p>
            <p className="m-0 text-sm break-all text-fg-muted">{user.email}</p>
          </div>
          <ul className="m-0 grid list-none gap-0.5 p-0 pt-2">
            <li>
              <Link ref={firstItemRef} href="/account/password" className={ITEM} onClick={() => setOpen(false)}>
                <LockIcon className="text-fg-muted" />
                Change password
              </Link>
            </li>
            <li>
              <button type="button" className={`${ITEM} m-0 cursor-pointer border-0 bg-transparent`} onClick={onSignOut}>
                <SignOutIcon className="text-fg-muted" />
                Sign out
              </button>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}
