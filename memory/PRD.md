# Daleel Pets - دليل بيتس PRD

## Problem Statement
Build "Daleel Pets" (دليل بيتس), a Saudi Arabia pet supplies competitor intelligence SaaS platform for pet store owners to monitor and analyze all competitor stores in the Saudi pet market.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + JWT Auth
- **Frontend**: React 18 + Tailwind CSS + Shadcn UI + Recharts
- **Database**: MongoDB (users, stores, products, product_snapshots, alerts, saved_filters)
- **Design**: Swiss & High-Contrast light theme with IBM Plex Sans Arabic font
- **i18n**: Custom bilingual (Arabic RTL + English LTR) with logical CSS properties

## User Personas
- **Saudi Pet Store Owner**: Monitors competitor pricing, stock, and best sellers to optimize their own strategy
- **Market Analyst**: Tracks market trends, product gaps, and restock opportunities across the KSA pet market

## Core Requirements
- JWT authentication (login/register)
- 4-tier waterfall crawler architecture (Tier 1 JSON / Tier 2 XHR / Tier 3 HTML / Tier 4 Account) - SIMULATED with mock data
- Inventory depletion engine (computes sales velocity from snapshot qty deltas)
- Confidence scoring per product snapshot (Tier 1: 92-98%, Tier 2: 85-95%, Tier 3: 70-85%)
- Arabic/English bilingual UI with RTL support
- All prices in SAR (Saudi Riyal)
- Date range picker (7/14/30/90 days)

## What's Been Implemented (April 15, 2026)

### Backend (27+ endpoints)
- Auth: login, register, me, logout, protected
- Stores CRUD: list, create, update, delete, trigger crawl
- Products: list, detail by SKU, history, velocity, my-products (with KPIs)
- Insights: summary, leaderboard, top-sellers, trending, gaps, price-wars, restock-opportunities
- Discounts: list, top-pct, top-amount (stubs)
- Alerts: CRUD (stubs)
- Saved Filters: CRUD
- CSV Export

### Seed Data
- 7 Saudi pet stores: Zarafa, Panda Store, Lana Pets, Cute Pets, Hamtaro, Caty Store, Petsy
- 35 products with Arabic/English names across 8 categories
- 1,746 price snapshots over 30 days with depletion simulation
- ~10,394 estimated units sold, ~1.52M SAR estimated revenue

### Frontend (4 pages)
1. **Login Page** - Email/password auth
2. **My Products** - KPI cards + dense product table with confidence tiers, stock signals, price ranges, sorting, filtering, search, date range picker, CSV export
3. **Insights** - Summary KPIs, Revenue Leaderboard chart, Top Sellers, Trending by Category (tabs), Price Wars, Restock Opportunities, Product Gaps
4. **Store Registry** - Store management table with crawl triggers, add/delete stores

### Product Detail Side Panel (Sheet)
- Product header with Arabic name, SKU, brand, category
- Price Range / Market Avg / Total Volume KPIs
- Confidence Tier badge
- Price by Store table with stock signals
- Price History multi-line chart (per store)
- Daily Velocity bar chart

### Other
- Arabic/English language toggle with RTL support
- Sidebar navigation
- JWT token auth with auto-redirect

## Prioritized Backlog

### P0 - Completed
- [x] JWT Auth
- [x] My Products page with full metrics
- [x] Insights page with analytics
- [x] Store Registry CRUD
- [x] Product Detail panel with charts
- [x] Arabic/English toggle
- [x] CSV Export

### P1 - Next Phase
- [ ] Live crawler (Tier 1 JSON endpoint scraping for Salla/Shopify/Zid)
- [ ] Alerts page (create alerts for price drops, OOS events)
- [ ] Discounts page (discount timeline, aggression score per store)
- [ ] Competitor Profiles page (per-store deep dive)
- [ ] Historical data pipeline (automated scheduled crawls)

### P2 - Future
- [ ] Tier 2 XHR interception crawler
- [ ] Tier 3 HTML crawl with Playwright
- [ ] Tier 4 Buyer Account Layer
- [ ] Email/SMS alert notifications
- [ ] Saudi seasonal calendar annotations (Ramadan, Eid, National Day)
- [ ] SKU matching normalization (Arabic name deduplication across stores)
- [ ] Brand/weight regex extraction from Arabic product names
- [ ] TanStack Table upgrade for virtual scrolling
- [ ] Redis caching + Bull job queues for crawl scheduling
