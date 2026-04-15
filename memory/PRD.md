# Daleel Pets PRD - Phase 2 Complete

## What's Been Implemented

### Phase 1 (MVP) - April 15, 2026
- JWT Auth (login/register/me)
- My Products page (KPI cards, dense table, filters, sorting, date picker, CSV export)
- Insights page (summary KPIs, revenue leaderboard, top sellers, trending, price wars, restock, gaps)
- Product Detail side panel (price history chart, velocity chart, store prices, confidence badges)
- Store Registry (CRUD, 7 seeded Saudi pet stores)
- Arabic/English bilingual UI with RTL
- 35 products, 1,746 snapshots

### Phase 2 - April 15, 2026
1. **Tier 1 Live Salla Crawler**: Real HTTP calls to Salla stores (zarafaksa.com tested), graceful fallback on failure, crawl logging with tier/status/HTTP code, crawl history expansion in Store Registry
2. **Alerts Page**: Full CRUD (create/toggle/delete), 5 alert types (price_drop, price_increase, out_of_stock, back_in_stock, low_stock), alert feed with 30d history, Check Now manual trigger, email logging (console, Resend-ready)
3. **Competitor Profiles Page**: Per-store analytics with KPIs (catalog size, active SKUs, est monthly revenue, avg discount), revenue trend chart (weekly/daily toggle, 90 days), top 10 products, category distribution pie chart, new arrivals (7d), recently OOS
4. **Expanded Mock Data**: 202 products across 14 categories (cat food dry/wet, cat litter, cat accessories, dog food dry/wet, dog accessories, bird, fish, reptile, grooming, healthcare, small animals, toys) distributed across 7 stores with 90 days of snapshot history (31,450 snapshots)

## Data Summary
- 7 stores: Zarafa, Panda Store, Lana Pets, Cute Pets, Hamtaro, Caty Store, Petsy
- 202 products with Arabic/English names
- 31,450 price snapshots over 90 days
- 14 product categories
- ~48K units sold est, ~5M SAR revenue est

## Backlog
### P1
- [ ] Live Salla/Shopify/Zid crawler deployment (Tier 1 infra ready)
- [ ] Tier 2 XHR interception crawler
- [ ] Discounts page (timeline, aggression scoring)
- [ ] Scheduled crawl jobs (Bull/Redis)

### P2
- [ ] Tier 3 HTML crawl with Playwright
- [ ] Tier 4 Buyer Account Layer
- [ ] Real email alerts (Resend integration - one-line swap ready)
- [ ] Saudi seasonal calendar annotations (Ramadan, Eid)
- [ ] SKU deduplication across stores (Arabic name normalization)
- [ ] Brand/weight regex extraction improvements
