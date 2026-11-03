import { VisuallyHidden } from "@/components/visually-hidden";
import { formatPrice } from "@/lib/landing/property";
import type { Price } from "@/lib/landing/types";

/** Green price, with "/ month" for recurring prices ("per month" to screen readers). */
export function PropertyPrice({ price }: { price: Price }) {
  const formatted = formatPrice(price);
  if (!formatted) {
    return <p className="text-lg font-bold text-fg-muted">Price on request</p>;
  }
  return (
    <p className="text-xl font-extrabold text-brand">
      {formatted}
      {price.period && (
        <>
          <span aria-hidden="true" className="text-sm font-semibold">
            {" "}
            / {price.period}
          </span>
          <VisuallyHidden> per {price.period}</VisuallyHidden>
        </>
      )}
    </p>
  );
}
