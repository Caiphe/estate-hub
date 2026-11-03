import Link from "next/link";
import type { ReactNode } from "react";

const BASE =
  "inline-flex min-h-11 items-center justify-center rounded-sm border-[1.5px] border-brand px-5 font-bold transition-colors duration-150 ease-standard";

const VARIANTS = {
  primary: "bg-brand text-fg-inverse hover:border-brand-strong hover:bg-brand-strong",
  secondary: "bg-surface text-fg hover:bg-brand-subtle",
} as const;

type ActionLinkProps = {
  href: string;
  variant: keyof typeof VARIANTS;
  className?: string;
  children: ReactNode;
};

/** Button-styled link: solid green primary or outlined secondary. */
export function ActionLink({ href, variant, className, children }: ActionLinkProps) {
  return (
    <Link href={href} className={[BASE, VARIANTS[variant], className].filter(Boolean).join(" ")}>
      {children}
    </Link>
  );
}
