import localFont from "next/font/local";

/**
 * Source Serif 4, self-hosted (Latin subset, variable weight 200–900), from
 * `@fontsource-variable/source-serif-4` 5.3.1 under the SIL Open Font License. The editorial
 * face for the sign-in page's marketing headline only. It lives beside that route, not in
 * `lib/fonts.ts`, because next/font preloads a font wherever its defining module is
 * imported. Exposed as `--font-source-serif` and consumed through `--font-serif`.
 */
export const sourceSerif = localFont({
  src: "../../assets/fonts/source-serif-4-latin-wght.woff2",
  weight: "200 900",
  style: "normal",
  display: "swap",
  variable: "--font-source-serif",
  fallback: ["Georgia", "Times New Roman", "serif"],
  adjustFontFallback: "Times New Roman",
});
