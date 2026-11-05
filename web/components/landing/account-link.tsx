import Link from "next/link";

import { HEADER_ACTIONS } from "@/lib/landing/navigation";

import { UserIcon } from "./icons";

/** Round profile icon shown instead of "Log in" when a session cookie is present. */
export function AccountLink() {
  return (
    <Link
      href={HEADER_ACTIONS.account.href}
      title={HEADER_ACTIONS.account.label}
      className="inline-grid size-11 shrink-0 place-items-center rounded-full border-[1.5px] border-brand bg-brand-subtle text-brand-strong transition-colors duration-150 ease-standard hover:bg-surface"
    >
      <UserIcon aria-hidden="true" />
      <span className="sr-only">{HEADER_ACTIONS.account.label}</span>
    </Link>
  );
}
