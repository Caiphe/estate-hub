import type { ReactNode } from "react";

/** Text announced by assistive technology but not shown, e.g. "per month" after a price. */
export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}
