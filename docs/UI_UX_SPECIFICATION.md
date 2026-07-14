# UI / UX Specification — the "Alpine" design system

_Last updated: 2026-07-14_

A premium, calm, mountain-tourism design system for **Svaneti with Georgie**,
built on **HeroUI v3 + Tailwind CSS v4** with a bespoke **Alpine** theme. It
covers tokens, typography, motion, responsiveness, accessibility and the
information architecture of both the public site and the dashboard. The living
reference is the dev-only showcase at **`/:lang/design-system`**.

## 1. Design principles

1. **Let the mountains lead.** Generous imagery, restrained UI chrome, plenty of
   whitespace. The interface frames content; it doesn't compete with it.
2. **Trust through clarity.** Honest metadata (difficulty, distance, price or
   "Contact for price"), never dark patterns.
3. **Three languages, first-class.** English, Georgian and Arabic are equal;
   Arabic is fully right-to-left, not an afterthought.
4. **Accessible by default.** WCAG 2.2 AA is a baseline, not a stretch goal.
5. **Calm motion.** Soft reveals that respect `prefers-reduced-motion`.

## 2. Color — Alpine palette (oklch tokens)

Colors are defined as CSS custom properties in the **oklch** color space,
following the HeroUI v3 variable contract, in `frontend/src/styles/theme.css`.
Two themes ship: `data-theme="alpine"` (light) and `data-theme="alpine-dark"`.

| Role | Meaning | Light token (oklch) |
|---|---|---|
| Accent / primary | **Deep alpine green** — primary actions, links | `0.42 0.062 165` |
| Background | **Warm ivory** | `0.972 0.008 85` |
| Foreground / stone | **Charcoal stone** (`--eclipse`) | `0.24 0.008 150` |
| Copper | **Copper accent** — focus ring, highlights | `0.66 0.12 56` |
| Glacier | **Glacier blue** — secondary accent | `0.74 0.05 232` |
| Muted | **Mist gray** — secondary text | `0.55 0.012 200` |
| Success / warning / danger | Semantic status | `0.62 0.13 155` / `0.78 0.145 72` / `0.58 0.2 25` |

Dark theme (`alpine-dark`) re-maps the base to charcoal-stone night
(`background 0.19 0.012 165`), lifts the accent to a glacier-tinted green
(`0.72 0.09 165`) for contrast, and keeps copper as the focus color. Surfaces,
overlays, fields, borders and shadows all have dedicated tokens so components
theme consistently. **Never hard-code hex** — consume the tokens.

Theme is toggled via the `ThemeToggle` component (persisted), applied by
stamping `data-theme` on the root element.

## 3. Typography

Loaded from Google Fonts in `index.html`; families exposed as CSS variables in
`globals.css`.

| Token | Family | Use |
|---|---|---|
| `--font-display` | **Fraunces** (optical serif) | Headings, hero, editorial display |
| `--font-sans` | **Manrope** | UI and body text (Latin) |
| — | **Noto Sans Georgian** | Georgian script (in the sans stack) |
| — | **IBM Plex Sans Arabic** | Arabic script (applied on `[lang="ar"]`) |

Body uses `--font-sans`; headings use `--font-display`. Arabic content switches
to IBM Plex Sans Arabic automatically. Type scale is fluid and pairs a warm serif
display with a clean geometric sans for a premium, legible feel.

## 4. Spacing, radius, elevation

- **Spacing base** `--spacing: 0.25rem` (4px), multiplied for a consistent rhythm.
- **Radius** `--radius: 0.75rem`; fields `calc(var(--radius) * 0.9)`.
- **Borders** 1px (`--border`, `--field-border`, `--separator`).
- **Elevation** soft, natural shadows: `--surface-shadow` for cards,
  `--overlay-shadow` for floating/overlay components, `--field-shadow` for
  inputs — muted in dark mode.

## 5. HeroUI v3 usage (component rules)

HeroUI v3 only — do **not** reintroduce v2 patterns.

- **Compound components:** `Card.Header` / `Card.Body` / `Card.Footer`, etc.
- **Events:** `onPress` (not `onClick`) for interactive elements.
- **Variants:** semantic — `primary` / `secondary` / `tertiary` / `danger`.
- **No `HeroUIProvider`, no flat-prop v2 API.**
- **Animation:** HeroUI animates in CSS; **Framer Motion is only** for page-level
  reveals — not for component state animation.
- **RTL:** wrap with HeroUI's `I18nProvider` and pass `dir` so components mirror.

Reusable app wrappers live in `components/primitives.tsx` and
`components/admin/*` (e.g. `AdminTable`, `EditorModal`, `LocalizedInput`,
`MediaPicker`, `StatusChip`, `ConfirmDialog`, `Toaster`).

## 6. Motion

- Soft, short reveals (fade/rise) on section entry; subtle hover elevation on
  cards. No parallax gimmicks.
- **Reduced motion:** honor `prefers-reduced-motion: reduce` — reveals become
  instant, non-essential animation is disabled.

## 7. Responsive breakpoints

Designed mobile-first and validated at:

`360 · 390 · 430 · 768 · 1024 · 1280 · 1440 · 1920`

- **360–430** — phones (primary for many inbound Gulf/European mobile visitors):
  single column, sticky primary CTA, condensed nav (drawer).
- **768** — tablet: two-column grids.
- **1024–1280** — laptop: full nav, multi-column tour/destination grids.
- **1440–1920** — large: content max-width capped; imagery scales, whitespace
  grows rather than lines getting too long.

## 8. Accessibility (WCAG 2.2 AA)

- **Semantic HTML** and landmarks (`header/nav/main/footer`, headings in order).
- **Skip link** ("Skip to content", target `#main`) present in `index.html`.
- **Keyboard:** everything operable; visible focus using the copper focus token
  and a 2px ring offset.
- **Dialogs / popups:** focus-trapped, `Esc` to close, focus restored on close
  (HeroUI dialog semantics).
- **Color:** never color-only status — pair with text/icon (e.g. status chips
  carry a label). Contrast meets AA in both themes.
- **Images:** localized `altText` on media; decorative images empty-alt.
- **RTL:** full mirroring for Arabic; logical CSS properties throughout.
- **Forms:** labels tied to inputs, inline validation messages, error summaries.
- **Maps/embeds:** accessible fallbacks and labels for Leaflet map and video
  embeds.

## 9. Information architecture — public site

Language-prefixed (`/:lang/...`). Global chrome: `Header` (logo, localized nav,
`LanguageSwitcher`, `ThemeToggle`), optional `AnnouncementBar`, `Footer`,
`WhatsAppFab`, `PopupHost`, `Seo`.

| Page | Purpose / key sections |
|---|---|
| **Home** | Hero, featured tours, destinations, why-Georgie, offers, testimonials, travel-guide teasers, CTA — assembled by the section renderer, editable in `/admin/pages`. |
| **Tours** | Filterable grid (destination, season, duration, difficulty, family, low-walking, winter, private, search, sort) + **Help me choose**. |
| **Tour detail** | Gallery, overview, itinerary, inclusions/exclusions, what to bring, distances/elevation/difficulty, price or "Contact for price", map, related, inquiry CTA. |
| **Destinations / detail** | Place intro, map, cultural/practical/accessibility/safety notes, gallery, related tours & articles. |
| **Experiences** | Category/audience-oriented entry points. |
| **About Georgie** | Guide story, credentials (once verified), portrait. |
| **Gallery / Videos** | Albums; uploaded and YouTube/Vimeo videos. |
| **Offers** | Active promotions. |
| **Travel guide / Article** | Editorial articles with related links. |
| **Reviews** | Guest reviews (sample ones excluded in prod). |
| **Plan your trip / Inquiry / Contact** | Planning content and the lead form (dates, group, interests, transport, consent). |
| **Privacy / Terms** | Legal. |
| **Design system** | **Dev-only** token/component showcase. |
| **404** | Not found. |

## 10. Information architecture — dashboard

`/admin` with a persistent shell (`AdminLayout`): sidebar nav, top bar, toaster.
Login at `/admin/login`.

| Area | Purpose |
|---|---|
| **Overview** | Counters: published/draft, new inquiries, recent activity. |
| **Pages** | Section-based page builder (reorder, hide, schedule sections). |
| **Tours** | List (incl. drafts) + rich edit form + publish/schedule. |
| **Destinations, Articles, FAQs, Gallery, Videos** | CRUD + publish. |
| **Media** | Upload/register external, edit metadata, replace, archive. |
| **Banners, Offers, Popups** | Targeting, scheduling, activation. |
| **Inquiries** | Pipeline (status, notes, timeline), CSV export. |
| **Navigation** | Menu, footer, social, legal, CTA — localized. |
| **SEO** | Route defaults and per-document overrides. |
| **Settings** | Brand, contact, languages, analytics, notices (owner-gated secrets). |
| **Users** | Owner/editor management (owner only). |
| **Audit** | Activity log. |

Admin forms use `LocalizedInput` (per-language tabs, English required),
`MediaPicker`, `StatusChip`, `ConfirmDialog` and a shared `AdminTable` with
`DataTableToolbar` for filtering/search/pagination.

## 11. Component & pattern checklist

- Tour card: cover (with alt), title, difficulty + duration chips, price/"Contact
  for price", featured badge, `onPress` to detail.
- Status chips: draft/scheduled/published/archived — label + color, never color
  alone.
- Localized inputs: en/ka/ar tabs; English required; RTL preview for Arabic.
- Empty states, skeletons (shimmer token), toasts for save/publish feedback.
- Popup host respects targeting + frequency (`lib/popupFrequency.ts`).
