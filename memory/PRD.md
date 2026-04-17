# Daleel Pets (دليل بيتس) — Product Requirements Document

## Problem Statement
SaaS web application for Saudi pet store owners to track and monitor competitor stores in the Saudi pet market (Zarafa, Petsy, Panda Store, etc.). Monitors product prices, stock/quantity, best sellers, categories, discounts, and out-of-stock alerts.

## Tech Stack
- **Frontend**: React 18, Tailwind CSS, Shadcn/UI, Recharts, Zustand, react-i18next
- **Backend**: FastAPI, Motor (async MongoDB), APScheduler, slowapi, Playwright, BeautifulSoup4
- **Database**: MongoDB 7
- **Auth**: PyJWT + bcrypt, httpOnly cookies
- **Deployment**: Docker Compose, Nginx reverse proxy

## Architecture
- 3-Tier Waterfall Crawler: API JSON → Playwright XHR → HTML Parsing
- JWT auth via httpOnly cookies (SameSite=Lax)
- Rate limiting: 5/min/IP on auth endpoints (slowapi)
- Security headers: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy

## Completed Features

### Phase 1-2: Foundation (Done)
- FastAPI + MongoDB + React project structure
- JWT authentication with httpOnly cookie storage
- Admin seed account (admin@daleelpets.com)
- 200+ product seed data with 90-day snapshot history
- Arabic/English localization (RTL support)

### Phase 3: Crawler & Analytics (Done)
- Tier 1 multi-endpoint JSON crawler for Salla stores
- APScheduler-based job system (P1: 4h, P2: 8h intervals)
- MyProductsPage dashboard with KPIs, filters, sorting
- Discounts page (top %, top SAR, timeline heatmap, aggression leaderboard)
- Price Opportunity Scanner (overpriced, quick wins, undercut analysis)
- Product detail panel with price history charts

### Phase 4: Advanced Crawling & Intelligence (Done)
- Tier 2 Playwright XHR interception crawler
- Tier 3 BeautifulSoup HTML parsing crawler
- 3-tier waterfall orchestrator with crawl logging
- Weekly Market Intelligence Digest (auto-generated Sunday 05:00 UTC)
- Saudi seasonal calendar annotations on charts
- Enhanced trending category analysis

### Code Quality (Done)
- Extracted crawlers.py for maintainability
- JWT secret generation via `secrets` module
- Migrated JWT storage from localStorage to httpOnly cookies
- Fixed React hook dependency warnings

### Deployment Readiness (Done — Feb 2026)
- Docker deployment package: Dockerfiles, docker-compose.yml, nginx.conf, .env.example
- Deployment guide for AWS Bahrain / Ubuntu VPS
- start.sh launcher script with validation
- GET /api/health endpoint (MongoDB, scheduler, Playwright, uptime)
- GET /api/health/detailed endpoint (per-store connectivity: reachable, response_time_ms, http_status, last_crawl)
- Rate limiting on auth endpoints (5/min/IP, 429 response)
- HTTP security headers middleware (CSP, nosniff, DENY, strict-origin)
- PLATFORM_SUMMARY.md — complete API/page/crawler/DB reference

### Crawler Endpoint Fix (Done — Feb 2026)
- Fixed Salla Tier 1: correct endpoint /en/api/v1/products with cursor.next pagination
- Fixed cursor.next /en/ prefix bug: Salla cursor.next drops /en/ prefix, leading to deprecated API (400). Re-insert /en/ automatically.
- Fixed Zid Tier 1: correct endpoint /api/v1/products with page-number pagination
- Added `results` key detection for Zid-style API responses
- Pagination follows cursor.next as complete URL until null (up to 200 pages)
- Results: Zarafa 1110 products (was 15), Petsy 720 (was 11), Panda 720 (was 8)

### Store Registry & Crawler Fixes (Done — Feb 2026)
- Added 7 stores: CuteCat, CutePets, Hamtaro, Mowkly, Aleef, Hobba, Caty (with correct domains, platforms, working_endpoints)
- Fixed CutePets domain (cutepets.com → cutepets.com.sa, Shopify → Salla)
- Marked pets-houses.com as is_own_store: true (MY STORE baseline)
- Lana Pets: Added Cloudflare bypass headers (Accept-Language, Accept) + direct Salla API attempt via Playwright
- Tier 2 enhanced: For Salla stores, tries direct API via Playwright before XHR interception (bypasses Cloudflare JS challenge)
- 12 stores total, 13 scheduler jobs active
- Complete dark premium SaaS theme: #060B14 background, glassmorphism cards, teal #00D4B4 + amber #F59E0B accents
- All pages redesigned: Login (split-screen hero), Dashboard, Stores, Insights, Scanner, Discounts, Alerts, Settings
- Collapsible sidebar with teal glow active state
- Fonts: Plus Jakarta Sans (EN), IBM Plex Arabic (AR), IBM Plex Mono (metrics)
- Micro-animations: fadeIn, countUp, pulse-glow, hover lift
- Reference: Linear.app meets Hex.tech meets Saudi fintech dashboard
- Removed verify=False from SSL calls in health/detailed endpoint
- Fixed hardcoded secrets in test file (now uses os.environ.get)
- Clarified i18n.js has no API keys (pure local translation dictionary)
- React hook dependencies verified clean (0 ESLint exhaustive-deps issues)
- Replaced all index-as-key patterns with stable unique IDs (6 instances across 4 files)
- Fixed missing /stores/:storeId route for CompetitorProfilePage in App.js

### Tier 4 Part 1: Encrypted Credential Vault (Done — Feb 2026)
- Fernet symmetric encryption for all stored credentials (ENCRYPTION_KEY from .env)
- Startup validation — crashes with clear error if ENCRYPTION_KEY missing/invalid
- Settings page (/settings) with Store Accounts (Tier 4) section
- Per-store credential management: email, password (masked), phone (last 4 only)
- Session status badges: Active/OTP Required/Expired/Not Configured
- Test Login + Clear Session buttons per store
- Verify Encryption button with green/red status banner
- Gear icon in sidebar footer
- Security: credentials never returned in plaintext, only masked versions

### Tier 4 Parts 2-6: OTP + Login Flows + Authenticated Crawl (Done — Feb 2026)
- Part 2: OTP handling — persistent orange banner, 6-digit modal with countdown timer, 5s polling, submit/retry/status endpoints, rate-limited (10/hr)
- Part 3: Platform login handlers — Salla (phone+OTP), Zid (email+password+OTP fallback), Shopify (email+password+2FA) via Playwright
- Part 4: Authenticated crawl — Tier 4 captures tier4_qty_exact, tier4_member_price, tier4_flash_sale, tier4_flash_price, source_tier=4, confidence=96
- Part 5: Store Registry UI — Tier 4 column with Authenticated/OTP Needed/Expired/Not Set Up badges. ProductDetailPanel shows member price, flash sale, exact stock
- Part 6: Waterfall updated — T1→T2→T3, then T4 supplement runs if session active (does NOT replace earlier tiers)

## What's MOCKED
- Email alerts → logged to console (Resend not yet integrated)
- Weekly digest delivery → logged to console

## Backlog

| Priority | Feature |
|----------|---------|
| P1 | Resend email integration for alerts + digest |
| P2 | Multi-tenant role-based access |
| P2 | Webhook notifications (Slack/Telegram) |

## Test Credentials
- Admin: admin@daleelpets.com / admin123
- Auth: POST /api/auth/login
