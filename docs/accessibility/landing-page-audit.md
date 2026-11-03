# Public landing page: accessibility audit

Recorded 2026-11-03 for landing-page prompt 12. Target: WCAG 2.2 AA. Run against `next dev` with Chromium (Playwright 1.61) at 1440, 1024, 768, 390, and 320 px.

## Automated coverage

| Check | Where | Result |
| --- | --- | --- |
| axe-core 4.14 (via `@axe-core/playwright` 4.14.0), tags `wcag2a`/`wcag2aa`/`wcag21a`/`wcag21aa`/`wcag22aa`/`best-practice` | `web/e2e/accessibility.spec.ts` | 0 violations in 7 landing states: desktop, mobile, mobile menu open, rent mode, search error, newsletter error, newsletter result. Dev preview (card states, loading/empty/error) also 0, with `landmark-unique` disabled there only because the gallery repeats one section three times. |
| One `h1`, no skipped heading levels | same | Pass |
| Landmarks: one banner, main, contentinfo, search, newsletter form; navigation named Primary, Platform, Company, Support; every section a named region | same | Pass |
| Image alt: meaningful images described, banner photo `alt=""`, every inline SVG `aria-hidden` | same | Pass |
| Full keyboard pass at 1440 px: every Tab stop shows a ≥2 px outline that is not covered by other content | same | Pass (30+ stops) |
| Mobile menu: reachable by Tab, links focus in order, Escape returns focus, outside tap closes, page scroll locked while open | `accessibility.spec.ts`, `responsive.spec.ts` | Pass |
| Forced colors: selected search mode underlined, focus remains an outline | `accessibility.spec.ts` | Pass |
| Reduced motion: every transition is 0 s, no hover transform, no pulsing skeletons | same | Pass |
| WCAG 1.4.12 text spacing (line 1.5, letters 0.12em, words 0.16em, paragraphs 2em) at 1440 and 390 px | same | No horizontal overflow, no clipped text (see limitations) |
| 200% zoom (720 px viewport), no horizontal scroll at 320–1440 px, targets ≥24 px | `responsive.spec.ts` | Pass |
| Form errors and announcements: search location error, newsletter errors and result through the live region, favorite `aria-pressed` | `search.spec.ts`, `footer.spec.ts`, `property-card.spec.ts` | Pass |

Interactive announcements are tested in the browser rather than in Vitest: the unit environment is Node without a DOM, and adding one only for this would duplicate the Playwright coverage.

## Manual checks

| Check | Method | Result |
| --- | --- | --- |
| Header link contrast over the hero photo (axe reports "incomplete": it cannot read pixels behind text) | Hid the links, screenshotted, and measured the darkest pixel behind each label against the text colour at 1024–2560 px | Worst case was 4.17:1 at 1920 px, below 4.5:1. **Fixed**: the wash under the header went from 75% to 90%; worst case is now 4.73:1. |
| Colour pairs on forest green (banner, footer) | Computed ratios from tokens | White 9.83, 80% white 6.88, 70% white 5.70, sand 7.13; dark text on sand 13.10. The default green focus ring would be 2.03:1, so focus turns sand on these surfaces. |
| Forced colors (Windows High Contrast) | Chromium emulation, screenshots | Selected tab was fill-only, so invisible. **Fixed** with an underline. Favorite pressed shows a filled heart; card focus shows an outline; nav over the photo gets the system text backplate. |
| Reduced motion | Emulation and code review | Card photo zoom, link-arrow nudge, and button press scale still moved. **Fixed**: now `motion-safe:` only. |
| State never by colour alone | Review of every stateful control | Current nav item: underline. Search mode: underline (fixed). Favorite: filled vs outline heart. Invalid fields: message text plus border. Card focus: outline. |
| Without CSS | Blocked stylesheets | Reading order matches the visual order; the process steps read as a numbered list (browser numbers appear beside the heading numbers). |

## Corrections made

1. Header wash over the hero photo strengthened (75% → 90%) for 4.5:1 text contrast at all widths.
2. Selected search mode underlined as well as filled.
3. Hover/press movement limited to `prefers-reduced-motion: no-preference`.
4. `FeaturedProperties` accepts an `id`, so repeated instances (the dev gallery) keep unique ids.

## Remaining limitations

- **No screen-reader pass yet.** Names, roles, states, and live regions are verified programmatically, but VoiceOver, NVDA, and TalkBack were not run. Do this before launch.
- **Chromium only.** Firefox and Safari (including Safari's list semantics, which `role="list"` addresses) are untested.
- **Truncation under text spacing.** Card titles clamp to two lines and the card location truncates by design; with text-spacing overrides more text is cut. The full title remains the link's accessible name, but the visible location can be shortened.
- **Placeholder imagery.** Property-card and alt-text checks use placeholders; re-check alt text when real listing photos arrive.
- **Dev overlay.** Next.js adds a focusable dev-tools button in development only; production builds do not include it.
