import Link from "next/link";

import { VisuallyHidden } from "@/components/visually-hidden";

const TONES = {
  light: { link: "text-fg", mark: "text-brand" },
  // On forest green or the dusk photograph the brand green would fall below 3:1, so the mark
  // goes white too.
  dark: { link: "text-fg-inverse", mark: "text-fg-inverse" },
} as const;

// "lg" is the sign-in page's scale; it starts at the header size so phones keep a short band.
const SIZES = {
  md: { link: "gap-2", mark: "", text: "text-xl" },
  lg: { link: "gap-2 md:gap-3", mark: "md:size-12", text: "text-xl md:text-2xl" },
} as const;

/** House mark plus wordmark, linking home. The SVG is decorative; the text names the link. */
export function BrandMark({
  tone = "light",
  size = "md",
}: {
  tone?: keyof typeof TONES;
  size?: keyof typeof SIZES;
}) {
  return (
    <Link href="/" className={`inline-flex min-h-11 items-center ${SIZES[size].link} ${TONES[tone].link}`}>
      <svg
        className={`${TONES[tone].mark} ${SIZES[size].mark}`.trim()}
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
      <span className={`${SIZES[size].text} font-extrabold tracking-tight`}>EstateHub</span>
      <VisuallyHidden> home</VisuallyHidden>
    </Link>
  );
}
