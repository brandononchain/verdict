# Zearch — approved brand identity

Status: **LOCKED — approved by Brandon on September 27, 2026.**

## Source of truth
The approved concept is the double-loop identity board shown in this conversation: two connected rounded loops, lowercase wordmark, and monochrome celestial campaign imagery. Source image: exec-b4506059-09c5-426a-966f-f495626b96eb.png.
These SVGs are the scalable production interpretation of that approved concept. Preserve this identity in future work; new concepts require an explicit request.

## Symbol
Two balanced rounded loops intersect to form a central lens: intersecting perspectives and discovery. Keep their proportions, common stroke weight, connected crossings, and generous inner spaces. No Z monogram, floating dots, orbital embellishments, detached pieces, or added symbols.

## Wordmark
Lowercase **zearch**, regular-weight contemporary sans, lightly tightened spacing. Product font: Geist, with Inter/Arial fallbacks. Display headlines use Geist too (weight 400, letter-spacing -0.03em); there is no serif. SVG lockups use live text and require these fonts for identical typography; the symbol itself is font-independent.

## Palette
The identity is monochrome. The product UI is light-first: light is the default, dark follows the system setting (`prefers-color-scheme`) or the Settings toggle (System, Light, Dark; stored as `data-theme` on `<html>`). Both themes use the same tokens in `styles.css`.

Dark theme (the approved identity colors)
- Charcoal: #212121 — primary canvas
- Graphite: #2B2B2B — surfaces
- Off-white: #ECECEC — symbol, wordmark, primary text
- Neutral gray: #9A9A9A — secondary text

Light theme
- App canvas #F6F7F9, cards #FFFFFF with a 1px hairline (#E3E5EA) and a very soft shadow
- Ink #16181D — symbol, wordmark, primary text; secondary text #5B616E (AA on every surface)
- Use `zearch-mark-dark.svg` (charcoal symbol) and `zearch-wordmark-light.svg` on light surfaces

Functional status colors (not identity colors)
Success green, warning amber, error red, and a running blue exist only to communicate run status (pills, dots, chart fills). Every status is also written in words, never color alone. Each has a text color on its tinted background that meets WCAG AA (4.5:1) in both themes. A categorical trio (blue, orange, gray) separates source tiers in charts, always with a text legend.

Home stage gradient
A deep navy to blue gradient (`--stage-gradient`) is allowed behind the home headline panel only. It never appears behind answers, tables or forms, and it is never used for the logo. It flattens to a solid navy under `prefers-reduced-motion`, `prefers-contrast: more` and the manual Reduce motion setting. Headline and lede on it are white and #D3DDF7 (AA on the gradient).

## Voice and copy
**A space for discovery.**
Campaign line: **Follow your curiosity.**
Domain direction: **zearch.computer** (does not imply registration or DNS setup).
Clear, curious, restrained. Describe the actual search engine capabilities accurately.

## Imagery
Cinematic monochrome landscapes, celestial scale, mist, distant horizons, human curiosity. Keep the logo flat and crisp. Atmosphere belongs in campaign imagery, with generous space and quiet typography. The app itself no longer uses the horizon photograph; the home stage uses the gradient above.

## Usage
Use a minimum clear space of one stroke width around the symbol. Prefer 24px or larger in UI. Use the same geometry in favicon, app tile, wordmark lockups and campaigns. Do not stretch, rotate, add effects, or substitute prior marks.

## Assets
- zearch-mark.svg — off-white symbol, transparent
- zearch-mark-dark.svg — charcoal symbol, transparent
- zearch-app-icon.svg — charcoal app tile
- favicon.svg — matching browser icon
- zearch-logo.svg — dark-surface horizontal lockup
- zearch-wordmark-light.svg — light-surface horizontal lockup

## Icons
Product icons are a small inline SVG sprite in `index.html` (stroke icons, `currentColor`, 1.7px stroke, round caps). No icon font and no third-party icon package. They sit beside text labels; an icon alone always has an accessible name.

## Copy in the product
Describe only what Zearch does: "Jev-checked answers with cited sources". No claims such as "AGI" or "neural engine". Every number shown comes from stored run data and says how many runs it covers. Empty states appear when there is no data; there are no placeholder or demo figures.

## Interface patterns
- **Sidebar**: resizable by the right-edge separator (mouse, touch, arrow keys, Home/End; double-click resets). Width is a CSS variable, at least 224px and at most 20% of the viewport, saved in the browser. Fixed and collapsible to icons on desktop; a drawer on mobile. Labels truncate with an ellipsis and the rail never scrolls sideways.
- **Composer**: one mode menu (icon, name, description and cost per mode) replaces the chips row. Each mode shows only its own tiles: URL with https-only hint (Scrape, Crawl), the "X vs Y" helper (Compare), the three-step list (Deep), a hint (Search), and the "Use my notes" switch with the real note count. In the thread the composer is compact and the tiles sit behind Options.
- **Pages**: Library, Knowledge, Monitors, Batches and Overview share one page header (icon tile, title, subtitle, actions), a 960px centred column, cards with a header hairline, and one set of form controls. File pickers are drop zones. Destructive actions confirm inline. Status pills use the functional tokens and always carry words.
- **Follow-ups**: if a finished run's `usage.followups` holds up to three strings, they show as chips under the answer and send as a follow-up. Nothing shows when it is absent.
