"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useSyncExternalStore, type FormEvent } from "react";

import { SearchIcon } from "@/components/landing/icons";
import { STAFF_SEARCH_MAX_LENGTH } from "@/lib/api/staff";
import { staffSearchHref } from "@/lib/navigation";

const noSubscription = () => () => {};
const onApplePlatform = () => /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);

/**
 * The top-bar staff search. A plain GET form to /staff, so it works before hydration; once
 * hydrated it navigates client-side. ⌘K or Ctrl+K focuses it from anywhere in the workspace.
 */
export function StaffSearch() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  // Only the hint differs by platform; either modifier works everywhere.
  const apple = useSyncExternalStore(noSubscription, onApplePlatform, () => false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) return;
      if (event.altKey || event.shiftKey) return;
      event.preventDefault();
      inputRef.current?.focus();
      inputRef.current?.select();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    router.push(staffSearchHref(inputRef.current?.value ?? ""));
  }

  return (
    <form
      role="search"
      aria-label="Staff"
      action="/staff"
      method="get"
      onSubmit={onSubmit}
      className="relative flex min-w-0 flex-1 items-center sm:max-w-xl"
    >
      <label htmlFor="workspace-search" className="sr-only">
        Search staff by name or email
      </label>
      <SearchIcon className="pointer-events-none absolute left-3.5 text-fg-muted" />
      <input
        ref={inputRef}
        id="workspace-search"
        type="search"
        name="q"
        maxLength={STAFF_SEARCH_MAX_LENGTH}
        autoComplete="off"
        placeholder="Search staff by name or email…"
        aria-keyshortcuts="Meta+K Control+K"
        className="m-0 min-h-11 w-full rounded-md border border-line bg-surface py-2 pr-16 pl-11 font-sans text-sm text-fg placeholder:text-fg-muted"
      />
      <kbd
        aria-hidden="true"
        className="pointer-events-none absolute right-3 rounded-sm border border-line bg-canvas px-1.5 py-0.5 font-sans text-xs font-semibold text-fg-muted max-sm:hidden"
      >
        {apple ? "⌘K" : "Ctrl K"}
      </kbd>
    </form>
  );
}
