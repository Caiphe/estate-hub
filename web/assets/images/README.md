# Landing-page image requirements

Images are registered in `lib/landing/assets.ts`. Sections import them from that manifest
only. Every slot renders through `next/image` at a fixed aspect ratio, so a source with the
wrong ratio is cropped (`object-fit: cover`), never stretched.

| Slot | Aspect ratio | Minimum source | Recommended | Composition |
| --- | --- | --- | --- | --- |
| Hero | 3:2 | 2400 × 1600 | 3000 × 2000 | Always cropped to its box (≈1.2:1 at desktop, 16:9 below). Keep the subject right of centre and in the upper two-thirds; the left edge fades into the page wash behind the heading. |
| Property card | 16:9 | 960 × 540 | 1280 × 720 | Consistent landscape crop of the building exterior; subject centered, no text or watermark. |
| Investment banner | 16:9 | 1600 × 900 | 2400 × 1350 | Architectural shot. Fills only the banner's right side (≈2.5:1 at desktop, 16:9 when stacked) and fades into the forest-green text zone, so keep the building right of centre. |

Use PNG, JPEG, or WebP. Next.js serves optimized responsive variants, but keep sources under
about 3 MB.

## Alt text

- Meaningful images (hero, property cards) describe what the photo shows, e.g. "Modern
  two-storey villa beside a pool at sunset".
- Decorative crops (investment banner) use `alt=""`; the surrounding copy carries the meaning.
- Placeholder entries say so: "Image placeholder for …".

## Current status

| Entry | File | Status |
| --- | --- | --- |
| Hero | `header-banner.jpg` (5509 × 3673) | Final. A family at home; crop point set in `hero-media.tsx`. 3.5 MB source; Next.js serves resized variants. |
| Modern Duplex in Lekki | `placeholders/property-card.svg` | **Missing**: needs a photograph. |
| Palm Heights Apartments | `placeholders/property-card.svg` | **Missing**: needs a photograph. |
| Victoria Commercial Plaza | `placeholders/property-card.svg` | **Missing**: needs a photograph. |
| Investment banner | `header-banner-1.png` (1672 × 941) | Final. The villa that was the original hero; decorative (`alt=""`). |

## Sign-in page

| Slot | File | Status |
| --- | --- | --- |
| Dusk marketing panel | `auth-banner.png` (1312 × 1199) | **Usable, under-sized.** Standalone photo of the reference villa at dusk; no baked-in text or controls. |

Requirements: the panel is full-height and portrait at desktop (≈842 × 1024 at 1536 × 1024, so
≈0.82:1), and a short landscape band on mobile. Use a landscape source of at least
**2400 × 2048** so a 2× display gets a sharp full-height crop; the current file is upscaled
≈1.7× there. Keep the house right of centre and in the lower half (crop anchored around
70% horizontally), with open dark sky top-left behind the headline and value points. The image
is decorative (`alt=""`): the panel's copy carries the meaning. Never substitute a crop of
`layout/Estate Hub Login at Dusk.png`; it contains baked-in UI.

`logo.png` is a raster with a white
background and a gold accent outside the landing palette; Prompt 02 decides between it and
a repo-native SVG mark.

## Fonts

`../fonts/manrope-latin-wght.woff2` is Manrope 5.3.0 (Latin subset, variable weight), from
`@fontsource-variable/manrope`, licensed under the SIL Open Font License (`../fonts/Manrope-OFL.txt`).

`../fonts/source-serif-4-latin-wght.woff2` is Source Serif 4 (Latin subset, variable weight),
from `@fontsource-variable/source-serif-4` 5.3.1, licensed under the SIL Open Font License
(`../fonts/SourceSerif4-OFL.txt`). It is used only for the sign-in marketing headline.
