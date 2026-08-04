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
