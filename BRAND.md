# Zearch — approved brand identity

Status: **LOCKED — approved by Brandon on September 27, 2026.** The double-loop concept is unchanged. The visual system, symbol grid and assets were redrawn on September 30, 2026 (see Symbol and Assets).

## Source of truth
The approved concept is the double-loop identity board shown in this conversation: two connected rounded loops, lowercase wordmark, and monochrome celestial campaign imagery. Source image: exec-b4506059-09c5-426a-966f-f495626b96eb.png.
These SVGs are the scalable production interpretation of that approved concept. Preserve this identity in future work; new concepts require an explicit request.

## Symbol
Two balanced rounded loops intersect to form a central lens: intersecting perspectives and discovery. Keep their proportions, common stroke weight, connected crossings, and generous inner spaces. No Z monogram, floating dots, orbital embellishments, detached pieces, or added symbols.

**Pixel-grid geometry (redrawn for a crisp mark).** The symbol is drawn on a 28-unit grid with a 2-unit stroke, so at its native 28px size the stroke is exactly 2 device-independent pixels and the vertical edges land on whole pixels. The left loop is `M14 6C8 .5 1 2.5 1 9.5v8C1 25.5 8 28 14 22.5 20 17 20 11 14 6Z` (stroke centreline, round caps and joins). The right loop is the same path mirrored with `matrix(-1 0 0 1 28 0)`. Both loops meet at (14, 6) and (14, 22.5), which forms the lens. In the UI the mark is an inline SVG with `width="28" height="28"`, `shape-rendering: geometricPrecision` and `vector-effect: non-scaling-stroke`, placed on integer pixel positions. Do not scale it by fractions: use 28px, 56px (stroke 4), 84px (stroke 6) and so on. At 16, 20, 24 and 32px the non-scaling stroke stays at the size the surface needs, and the favicon tile draws the mark at 1:1 inside a 32-unit tile so it is sharp at 16px (1px stroke) and 32px (2px stroke).

## Wordmark
Lowercase **zearch**, contemporary sans, tightened spacing (-0.045em). In the product it is live Geist text (weight 500, 21px), so it is rendered by the browser at the exact pixel size. The SVG lockups (`zearch-logo.svg`, `zearch-wordmark-light.svg`) use outlined Geist paths, so they need no font and stay sharp at any size. Display headlines use Geist (weight 500, letter-spacing -0.04em); there is no serif. Data (counts, timings, dates, URLs) uses Geist Mono with tabular numerals.

## Palette
The identity is monochrome. The product look is "Ethereal Glass": a near-black OLED dark theme and a cool silver-white light theme, both with restrained radial mesh glows and hairline borders. The UI follows the system setting (`prefers-color-scheme`; light when there is no preference) or the Settings toggle (System, Light, Dark; stored as `data-theme` on `<html>`). Both themes use the same tokens in `styles.css`.

Dark theme (flagship)
- Canvas #060608, surfaces #0F1014 / #15161C / #1D1F27, hairlines white at 8% and 14%
- Off-white #F1F2F6 — symbol, wordmark, primary text; secondary text #9A9EAE (AA on every surface)
- Inner top highlight `inset 0 1px 1px rgba(255,255,255,.12)` on cores; mesh glows are indigo and blue at low opacity

Light theme
- Canvas #EEF0F6 (cool silver-white), cores #FFFFFF, hairline `#0F172A` at 9%, soft diffused ambient shadows
- Ink #0C0E14 — symbol, wordmark, primary text; secondary text #565C6B (AA on every surface)
- Use `zearch-mark-dark.svg` (ink symbol) and `zearch-wordmark-light.svg` on light surfaces

One cool accent (#8FA2FF in dark, #3A4FE0 in light) is used only for focus rings, the active-nav indicator, citation chips, selected states and glows. Primary buttons stay monochrome (ink on canvas), so the accent never competes with the identity.

Functional status colors (not identity colors)
Success green, warning amber, error red, and a running blue exist only to communicate run status (pills, dots, chart fills). Every status is also written in words, never color alone. Each has a text color on its tinted background that meets WCAG AA (4.5:1) in both themes. A categorical trio (blue, orange, gray) separates source tiers in charts, always with a text legend.

Home hero glow
The home headline and composer sit in one glass panel with a soft mesh glow behind it (`.hero-core::before`). The glow is static, low-opacity and behind text only; ink stays `--ink` on the tokenised surface, so contrast is the same as everywhere else. It never appears behind answers, tables or forms and is never applied to the logo. A fixed grain overlay at 2 to 3% opacity is the only other texture.

## Voice and copy
**A space for discovery.**
Campaign line: **Follow your curiosity.**
Domain direction: **zearch.computer** (does not imply registration or DNS setup).
Clear, curious, restrained. Describe the actual search engine capabilities accurately.

## Imagery
Cinematic monochrome landscapes, celestial scale, mist, distant horizons, human curiosity. Keep the logo flat and crisp. Atmosphere belongs in campaign imagery, with generous space and quiet typography. The app itself no longer uses the horizon photograph; the home hero uses the mesh glow above.

## Usage
Use a minimum clear space of one stroke width around the symbol. Prefer 24px or larger in UI. Use the same geometry in favicon, app tile, wordmark lockups and campaigns. Do not stretch, rotate, add effects, or substitute prior marks.

## Assets
- zearch-mark.svg — off-white symbol, transparent, 28-unit grid
- zearch-mark-dark.svg — ink symbol, transparent, 28-unit grid
- zearch-app-icon.svg — near-black app tile (32 units, mark at 1:1)
- favicon.svg — matching browser icon
- zearch-logo.svg — dark-surface horizontal lockup (outlined wordmark, mark at 2x)
- zearch-wordmark-light.svg — light-surface horizontal lockup
- assets/apple-touch-icon.png (180), icon-192.png, icon-512.png and og-image.png (1200x630) are rendered from this same geometry with Chromium at 2x to 4x device scale and box-filtered down to native size in linear light, so edges are clean. The icon tiles are full-bleed with the mark inside the maskable safe zone. Regenerate them from the SVG geometry rather than editing them by hand.

## Icons
Product icons are a small inline SVG sprite in `index.html`: ultra-light line icons on a 24-unit grid (Phosphor-Light style geometry), `currentColor`, round caps and joins. The stroke is an exact 1.5px at every size (`vector-effect: non-scaling-stroke`), drawn at 18 to 20px beside labels. No icon font and no third-party icon package. They sit beside text labels; an icon alone always has an accessible name.

## Copy in the product
Describe only what Zearch does: "Jev-checked answers with cited sources". No claims such as "AGI" or "neural engine". Every number shown comes from stored run data and says how many runs it covers. Empty states appear when there is no data; there are no placeholder or demo figures.

## Interface patterns
- **Double bezel**: major containers are two nested layers: an outer shell (faint tint, hairline ring, 6px padding, large radius) around an inner core (its own surface, an inner top highlight, a concentric smaller radius). The composer, hero, dialogs, menus, palette and mode popover use real nested elements; cards, stat cards, source cards and lists get the same look from a 6px spread shadow plus a 1px outline ring, so the radii stay concentric.
- **Buttons**: primary actions are full pills. A trailing icon sits in its own circular island flush with the right padding; on hover the island moves 1px up and right and scales to 1.05, and every button scales to .98 when pressed. The send button is an island pill and becomes a Stop pill while a run is active. A disabled primary button is an outlined ghost, never a flat grey slab.
- **Motion**: one curve, `cubic-bezier(0.32, 0.72, 0, 1)`, 400 to 700ms for entrances and 180 to 260ms for hovers. Only transform, opacity, filter (entrance blur to sharp) and colour change. Page content and cards fade up with a stagger each time a view is shown (a CSS animation restarted by the panel being un-hidden, never a scroll listener); menus and tiles spring in; skeletons and the streaming bar shimmer by moving a transform. Animations use fill-mode `backwards`, never `forwards`, so a finished animation leaves no containing block behind for fixed popovers. Prefers-reduced-motion and the manual Reduce motion setting cut every duration to near zero. Backdrop blur is used only on fixed or overlay layers (top bar, rail panel, menus, popover, dialogs, dock, tab bar, toasts), never on scrolling content.
- **Sidebar**: a floating glass panel, resizable by the right-edge separator (mouse, touch, arrow keys, Home/End; double-click resets). Width is a CSS variable, at least 224px and at most 20% of the viewport, saved in the browser. Collapsible to an icon rail with a smooth label fade; an animated accent indicator marks the current page. On phones it is a spring drawer with a scrim: swipe left to close, swipe right from the left edge to open, focus trapped and `inert` when closed. Labels truncate with an ellipsis and the rail never scrolls sideways.
- **Composer**: a bezeled bento message box. One mode pill opens a floating popover placed with collision handling (below the whole composer, else above the button, else the larger side with an inner scroll), so it never covers the input; on phones it is a bottom sheet with a grip, 56px rows and a scrim (tap, swipe down or Escape to dismiss). Each mode shows only its own tiles: URL with https-only hint (Scrape, Crawl), the "X vs Y" helper (Compare), the three steps (Deep), a hint (Search), and the "Use my notes" switch with the real note count and the reason when it is off. The composer is compact in the thread and on phones while the keyboard is open; the tiles then sit behind Options.
- **Home**: the headline and composer are one glass hero panel with a mesh glow. Shortcuts below are a bento: Deep research is the large featured card, Compare and Crawl are the two smaller ones.
- **Pages**: Library, Knowledge, Monitors, Batches and Overview share one page header (eyebrow tag, large tight title, subtitle, right-aligned actions), a 980px centred column, bezeled cards with a header hairline, and one set of form controls. Overview is an asymmetric bento (large verified-answers card, tall research-time card, small cost and source cards, wide runs-per-day, insights). File pickers are drop zones. Destructive actions confirm inline. Status pills use the functional tokens and always carry words.
- **Empty states**: one centred vertical stack: icon, title, text, then a button that never wraps.
- **Answers**: a user bubble, the answer with citation chips (number only, the full label stays for assistive tech), bezeled source cards, follow-up chips as glass pills, and an icon-pill action row.
- **Phones**: a first-class layout, not a fallback. Compact glass top bar (menu, mark, New research, more menu that also carries the runs and allowance figures), a floating bottom tab bar (Home, Library, Knowledge, Overview, More) in the page flow that hides while the dock or the keyboard is showing, a dock that follows `visualViewport` so it stays above the keyboard and keeps the newest message in view, bottom-sheet dialogs with a sticky header and footer, single-column pages, tables as card lists, 44px minimum targets, 16px inputs, pressed states instead of hover-only affordances, and contained overscroll.
- **Follow-ups**: if a finished run's `usage.followups` holds up to three strings, they show as glass pills under the answer and send as a follow-up. Nothing shows when it is absent.
