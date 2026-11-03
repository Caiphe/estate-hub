import localFont from "next/font/local";

/**
 * Manrope, self-hosted (Latin subset, variable weight 200–800) so builds never fetch
 * fonts over the network. `adjustFontFallback` sizes the Arial fallback to Manrope's
 * metrics, keeping layout shift small while the font loads. Exposed as
 * `--font-manrope` and consumed through the `--font-family-sans` token.
 */
export const manrope = localFont({
  src: "../assets/fonts/manrope-latin-wght.woff2",
  weight: "200 800",
  style: "normal",
  display: "swap",
  variable: "--font-manrope",
  fallback: ["Arial", "Helvetica", "sans-serif"],
  adjustFontFallback: "Arial",
});
