import Link from "next/link";

import { VisuallyHidden } from "@/components/visually-hidden";

/** House mark plus wordmark, linking home. The SVG is decorative; the text names the link. */
export function BrandMark() {
  return (
    <Link href="/" className="brand-mark">
      <svg
        className="brand-mark-icon"
        viewBox="0 0 32 32"
        width="36"
        height="36"
        aria-hidden="true"
        focusable="false"
      >
        <path
          d="M4.5 13.5 16 4.5l11.5 9V27.5h-8v-8h-7v8h-8z"
          fill="none"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinejoin="round"
        />
      </svg>
      <span className="brand-mark-text">EstateHub</span>
      <VisuallyHidden> home</VisuallyHidden>
    </Link>
  );
}
