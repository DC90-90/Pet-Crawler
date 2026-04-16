# Daleel Pets PRD - Phase 3 Complete

## What's Been Implemented

### Phase 1 (MVP)
- JWT Auth, My Products page, Insights page, Product Detail panel, Store Registry
- Arabic/English bilingual UI with RTL, 35 products

### Phase 2
- Tier 1 Salla Crawler (single endpoint), Alerts page, Competitor Profiles page
- Expanded to 202 products, 31K snapshots, 90 days history

### Phase 3 — April 15, 2026
1. **Multi-Endpoint Salla Crawler**: Tries 4 endpoints in sequence (/api/v2/products, /products.json, /api/store/products, /api/product/list). Caches working endpoint per store. Shows all attempted endpoints in crawl logs. Auto-escalates to "Tier 2 stub" when all fail.
2. **APScheduler**: Priority stores (P1) crawl every 4h, standard (P2) every 8h. 15min stagger. Auto-registers on startup. Registers/unregisters when stores added/deleted. Pause All Crawls toggle. Next crawl time shown per store.
3. **Discounts Page**: Top discounts by % and SAR (filterable by store/category). Discount Timeline (90-day stacked bar chart by store/week). Aggression Leaderboard with composite score (avg depth 40%, frequency 35%, max discount 25%) + labels (Most Aggressive, Most Stable, Highest Single Discount).
4. **Price Opportunity Scanner**: Summary cards (overpriced count, revenue uplift, zero-sales-overpriced). Main table sorted by revenue uplift with badges (Quick Win, Overpriced Risk, Overpriced). Well Positioned and Undercut Opportunity sections. Detail panel with price distribution chart and price recommendations. Date range filter (7/14/30D).

## Data Summary
- 202 products, 31,450+ snapshots, 90 days, 7 stores, 14 categories
- 6 pages + competitor profiles + product detail panel
- 34+ API endpoints, 100% backend test pass rate

## Backlog
### P1
- [ ] Tier 2 XHR interception crawler (Playwright)
- [ ] Tier 3 HTML crawl
- [ ] Real email alerts (Resend - one-line swap ready)
- [ ] Saudi seasonal calendar annotations on charts

### P2
- [ ] Tier 4 Buyer Account Layer
- [ ] SKU deduplication across stores
- [ ] Brand/weight regex improvements
- [ ] Admin user management
- [ ] Export functionality for all pages
