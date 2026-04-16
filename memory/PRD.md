# Daleel Pets PRD - Phase 4 Complete

## Platform Summary

### Pages (8 total + sub-pages)
1. My Products — KPI dashboard + dense product table + Product Detail panel
2. Insights — Summary KPIs, Revenue Leaderboard, Top Sellers, Trending, Price Wars, Restock, Gaps + Digest modal
3. Price Scanner — Overpriced products, revenue uplift, Quick Win/Overpriced Risk badges, detail panel
4. Discounts — Top by %, Top by SAR, 90-day Timeline, Aggression Leaderboard
5. Alerts — CRUD, 5 alert types, alert feed, Check Now
6. Stores — Registry, CRUD, crawl triggers, crawl logs, scheduler status + Competitor Profiles (sub-page)
7. Login — JWT auth
8. Competitor Profiles — Per-store: revenue trend (weekly/daily), top 10, category pie, new arrivals, OOS

### API Endpoints (45+)
Auth (5): register, login, me, logout, protected
Stores (7): list, create, update, delete, crawl, crawl-logs, profile
Products (5): list, my-products, detail, history, velocity
Insights (7): summary, leaderboard, top-sellers, trending, gaps, price-wars, restock
Discounts (4): top-pct, top-amount, timeline, aggression
Scanner (1): opportunities
Alerts (6): list, create, toggle, delete, feed, check
Digests (3): list, latest, generate
Scheduler (2): status, toggle-pause
Filters (2): list, create
Export (1): CSV
Root (1)

### Crawler Architecture
- Tier 1: 4 JSON endpoints (Salla/Shopify/Zid) — all returning 410 for zarafaksa
- Tier 2: Playwright XHR interception — WORKING, captured real products from Zarafa via api.salla.dev
- Tier 3: Playwright + BeautifulSoup HTML parsing with platform-specific CSS selectors
- Waterfall orchestrator: Tier 1 → Tier 2 → Tier 3 automatic cascade
- APScheduler: P1 every 4h, P2 every 8h, staggered 15min, weekly digest Sunday 08:00 Riyadh

### Data
- 218 products (202 mock + 16 real crawled from Zarafa)
- 31,450+ snapshots over 90 days
- 7 Saudi pet stores, 14+ categories
- Saudi Seasonal Events: Ramadan, Eid Al-Fitr, Eid Al-Adha, National Day, Founding Day, White Friday

### Phase 4 Features (April 16, 2026)
1. Tier 2 XHR Crawler — Live, captured 172 Zarafa products via Playwright interception
2. Tier 3 HTML Crawler — BeautifulSoup with Salla/Zid/Shopify/custom selector profiles
3. Weekly Market Digest — APScheduler + MongoDB, 5 sections, console delivery (Resend-ready)
4. Saudi Seasonal Calendar — ReferenceLine/ReferenceArea on all charts, toggle, 7 events config
5. Digest Modal — Insights page integration, Generate Now button

## Backlog
### P1
- [ ] Saudi IP deployment for better store endpoint access
- [ ] Real email delivery (Resend — one-line swap)
- [ ] Tier 4 Buyer Account Layer
- [ ] Admin user management + multi-tenancy
- [ ] Export PDF reports

### P2
- [ ] SKU deduplication (Arabic name normalization across stores)
- [ ] Auto-Repricer engine
- [ ] Webhook notifications
- [ ] Mobile-responsive optimization
