# Daleel — PRD

## Original Problem Statement
SaaS platform for Saudi online store owners to track competitors' prices, inventory, best sellers, categories, and discounts across all Saudi stores (initially Salla & Zid). Real-time market intelligence.

## Core Requirements
- Multi-tier crawler (Tier 1/2/3 fallback + external Saudi-IP ingest)
- Product matching: Barcode > SKU > Name, max 150% price diff, max 10% weight diff
- HRM-SA brand identity (flat dark `#090E1C`, teal accent `#1E988E`, Space Grotesk + Inter + JetBrains Mono + DIN Next LT Arabic)
- FastAPI + MongoDB + JWT (httpOnly cookies) + APScheduler
- External ingest API (bearer token)
- Arabic RTL support, SAR currency

## Brand Identity (HRM-SA)
| Usage | Hex |
|---|---|
| Page bg | `#090E1C` |
| Card bg | `#0A2728` |
| Elevated | `#104745` |
| Borders | `#13625F` |
| Primary accent | `#1E988E` |
| Accent light (hover) | `#6AC1B5` |
| Muted text | `#A1E4DB` |
| Near-white teal | `#DAF8F4` |
| Text | `#FFFFFF` |

Fonts: `Space Grotesk` (EN headings, uppercase, letter-spacing 0.05em), `Inter` (EN body), `JetBrains Mono` (badges/numbers), `DIN Next LT Arabic` with `IBM Plex Sans Arabic` fallback (AR, no uppercase, letter-spacing 0).

## What's Implemented
- Multi-tier crawler + external ingest endpoint (hardened for bad payloads, idempotent store upsert-by-domain)
- `tier1_only` flag skipping Playwright tiers for Salla stores (CuteCat, CutePets, Hamtaro, Mowkly)
- Product matcher with strict rules
- Excel baseline import
- Price Intel + Insights dashboards
- Fernet-encrypted credentials vault
- Auto-generated price alerts
- Docker deployment package
- **Full rebrand** from "Daleel Pets" → "Daleel" (English + Arabic, all files)
- **Full HRM-SA visual identity applied** (flat `#090E1C` bg, teal palette, Space Grotesk/Inter/JetBrains Mono, HRM-SA button/card/input/table/badge/scrollbar styles)

## Recent Changes (Feb 2026)
- Crawler token hardcoded in `server.py` (no env var fallback)
- `seed_database()` force-updates admin password hash on startup
- `/api/crawler/ingest`: per-row try/except, currency/null coercion, `upsert` stores by domain
- Brand rebrand: all "Daleel Pets" → "Daleel", removed pet-specific copy
- HRM-SA theme: `App.css` + `index.css` rewritten, Login & Sidebar refactored, 69 stale teal refs swept across all pages via global sed
- **Light/Dark theme toggle** (Feb 2026) — Sun/Moon button in Sidebar (`data-testid="theme-toggle-btn"`), persists to `localStorage.daleel_theme`, no-flash inline init script in `public/index.html`. CSS overrides under `html[data-theme="light"]` cover sidebar, KPI cards, dense table, glass-card, and inputs.
- **Per-day date picker** on My Products (`day-picker-input`) — overrides 7/14/30/90D pills via `?on_date=YYYY-MM-DD`
- **Product Detail panel speed-up** — single aggregated `/api/products/{sku}/full?days=30` replaces 3 round-trips; renders per-store sparklines + Recharts price-history chart
- **Storefront deep-links** on every product row + every store row inside the detail panel
- Tested via testing agent (iteration_12.json): 100% backend (16/16), 100% frontend (5/5), no issues

## Backlog
- **P1** Resend email integration (alerts + weekly digest)
- **P1** Multi-tenant role-based access
- **P2** Webhook notifications (Slack/Telegram)
- **Refactor** Split large pages (`PriceIntelPage.jsx`, `InsightsPage.jsx`); organize backend into `routes/` and `models/`

## Credentials
- Admin: `admin@daleelpets.com` / `BGv8ZcRYrBTPlJFHHhZQ3Q` (kept unchanged — live auth credential)
- Crawler token (hardcoded): `zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO`

## Preview URL
https://saudi-pets-monitor.preview.emergentagent.com
