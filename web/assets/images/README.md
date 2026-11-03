# Landing-page image requirements

Images are registered in `lib/landing/assets.ts`. Sections import them from that manifest
only. Every slot renders through `next/image` at a fixed aspect ratio, so a source with the
wrong ratio is cropped (`object-fit: cover`), never stretched.

| Slot | Aspect ratio | Minimum source | Recommended | Composition |
| --- | --- | --- | --- | --- |
| Hero | 16:9 | 1600 × 900 | 2400 × 1350 | Wide architectural shot. The building fills the right half and bleeds to the edge; the left third is calm sky or wash behind the heading. |
| Property card | 16:9 | 960 × 540 | 1280 × 720 | Consistent landscape crop of the building exterior; subject centered, no text or watermark. |
| Investment banner | 3:1 | 2400 × 800 | 3000 × 1000 | Panoramic crop. Subject in the right 45%; the left 55% is dark or low-detail, safe for white text. |

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
| Hero | `header-banner.png` (1672 × 941) | Final. Meets the minimum; supply 2400 px wide for sharper 2× displays. |
| Modern Duplex in Lekki | `placeholders/property-card.svg` | **Missing**: needs a photograph. |
| Palm Heights Apartments | `placeholders/property-card.svg` | **Missing**: needs a photograph. |
| Victoria Commercial Plaza | `placeholders/property-card.svg` | **Missing**: needs a photograph. |
| Investment banner | `placeholders/investment-banner.svg` | **Missing**: needs a panoramic photograph. |

`auth-banner.png` belongs to the sign-in page. `logo.png` is a raster with a white
background and a gold accent outside the landing palette; Prompt 02 decides between it and
a repo-native SVG mark.

## Fonts

`../fonts/manrope-latin-wght.woff2` is Manrope 5.3.0 (Latin subset, variable weight), from
`@fontsource-variable/manrope`, licensed under the SIL Open Font License (`../fonts/Manrope-OFL.txt`).
