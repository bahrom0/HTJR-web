# TJOCR Visual Implementation Contract

This file is the active visual source of truth for future UI work in `web_app`.
It supplements `docs/DISPLAY_ARCHITECTURE.md`: that document defines user flows,
while this file defines visual expression. If visual documents conflict, the latest
direct user request wins.

## Product direction

TJOCR is calm, editorial, and precise. The interface uses monochrome photography,
paper-white surfaces, charcoal ink, restrained borders, generous whitespace, and
one strong primary action. Do not introduce neon, purple or blue branding, glassy
decorative cards, emoji, placeholder content, or visible actions without a real flow.

## Current reference: access screen

- Route: `/access` and `/access/register`.
- Reference: user-provided sign-in image dated 2026-08-04. Its composition is the
  source for the split desktop login screen.
- New authored artwork: `web_app/public/auth-hero-v2.png`.
- Source logos: `web_app/public/tjocr-logo-light.png` and
  `web_app/public/tjocr-logo-dark.png`.
- Active auth PNGs: `web_app/public/tjocr-logo-auth-light.png` and
  `web_app/public/tjocr-logo-auth-dark.png`. These are the current user-provided
  light and dark assets; render them directly with no crop, inversion, recoloring,
  blend mode, or image-generation replacement.
- The visual reference includes Google sign-in, but it is intentionally omitted:
  the current app has no Google OAuth flow.

### Tokens

| Role | Light | Dark |
| --- | --- | --- |
| Auth page | `#EFEDE9` | `#0D0D0D` |
| Form panel | `#FCFBFA` | `#181818` |
| Primary ink/action | `#171717` | `#F6F4F0` |
| Muted copy | `#979592` | `#AAA8A5` |
| Border | `#D9D7D4` | `#353535` |
| Field surface | `#FFFFFF` | `#202020` |
| Main shadow | `0 30px 76px rgba(28,27,25,.14)` | `0 34px 90px rgba(0,0,0,.58)` |

Use semantic variables first. Repeated component values must become variables;
do not spread unrelated literal values through routes.

### Layout and responsive behavior

- Desktop: centered split container, max width `1280px`, min height
  `min(760px, calc(100dvh - 128px))`, grid ratio `1.06fr / .94fr`, radius
  `28px-42px`.
- Left side: decorative monochrome artwork, cropped with `object-fit: cover`.
  It is not interactive and must be hidden from screen readers.
- Right side: centered form, max width `540px`, generous vertical space,
  TJOCR logo lockup above the title.
- Controls: `56px` input height, `54px` button height, `14px` radius, `1px`
  border. Keep field labels accessible even when visually hidden.
- Mobile at `760px` and below: one column, hide the decorative image, remove
  outer radius/border, retain a full-height form with safe-area padding. Never
  create horizontal scrolling.

### Typography

- Use the product font stack with `Outfit Variable` where the loaded font supports
  the glyphs; keep the documented Cyrillic system fallback.
- Access title: `clamp(2.1rem, 4vw, 3rem)`, weight `450`, line-height `1.08`,
  letter-spacing `-0.055em`; mobile uses `clamp(2rem, 10vw, 2.65rem)`.
- Supporting copy: `0.95rem / 1.5`, centered, muted.

### Motion and accessibility

- Enter: image `opacity + x(-18px) + scale(1.015)` and form
  `opacity + y(18px) + scale(.985 -> 1)` using existing `motionTransition.enter`.
- Image settle: `auth-image-settle`, `900ms`,
  `cubic-bezier(.2,.8,.2,1)`, scale only.
- Controls: border, background, shadow, opacity and `translateY(-1px)` within
  `180ms`; never animate layout dimensions.
- Honor `prefers-reduced-motion`; preserve semantic forms, keyboard order,
  visible focus, `autocomplete`, and textual errors.

## Rules for subsequent pages

1. Inspect the live route, states, and functional constraints before changing UI.
2. Reuse this palette, spacing rhythm, border treatment, motion discipline, and
   responsive hierarchy; do not change API semantics to satisfy appearance.
3. Add a new section here whenever a page introduces a reusable token, component,
   breakpoint, or animation rule.
4. Verify light theme, dark theme, desktop, mobile, keyboard focus, and
   reduced-motion behavior before completion.

## Recognition workspace and automatic handoff

- Routes: `/processing`, `/preparation`, and `/regions`.
- Product flow after upload is one continuous operation: the server evaluates
  image quality, confirms the default preparation recipe, and starts the
  durable Kraken line detector. The interface must not make those server stages
  look like three user decisions.
- `/processing` uses one calm, centered loader. Its three compact labels explain
  progress but are not controls. At `awaiting_region_review`, it fades into the
  real `/regions` editor; only the later confirmed OCR stage may open `/result`.
- `/preparation` remains an advanced manual correction route for retry/error
  recovery. It is not part of the normal happy path.

### Recognized-lines editor

- Desktop: fixed-height workspace beneath the shared header, centered image
  canvas on the left and one `330-370px` glass panel on the right. The right
  side is one component, not a stack of unrelated floating cards.
- The four tool sections are `Распознавание текста`, `Область`, `Вид`, and
  `История`. Recognition shows Kraken regions, reading order, source, warnings,
  and normalized X/Y position. Selection contains exact bounds, split, merge,
  delete, and ordering actions. View owns zoom/fit/draw. History owns undo/redo,
  server refresh, dirty state, and conflict messages.
- Mobile at `900px` and below: canvas keeps the full available editor area and
  tools become a three-position bottom sheet. The visible sheet height is
  subtracted from canvas fitting so the document never sits underneath the
  controls. Tap the handle to collapse/restore; swipe it to move between
  collapsed, half, and full positions.
- Wheel input inside the desktop canvas and pinch input on touch devices change
  only the image view. The page itself must not scroll while the pointer is over
  the canvas. Region drag, 44px resize handles, keyboard movement, local draft,
  undo/redo, revision conflict recovery, and server-owned confirmation remain
  functional at every breakpoint.
