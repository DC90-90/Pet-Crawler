# Daleel Pets — Platform Summary
# دليل بيتس — ملخص المنصة
> Generated: February 2026 | Version: 1.0 (Deployment-Ready)

---

## 1. Product Overview

**Daleel Pets** is a SaaS competitor intelligence platform for Saudi pet store owners. It monitors product prices, stock levels, discounts, and market trends across Saudi e-commerce pet stores (Zarafa, Petsy, Panda Store, etc.) using a 3-tier automated web crawler.

**Target Users**: Saudi pet store owners and category managers
**Currency**: SAR (﷼) | **Localization**: Arabic (RTL) + English

---

## 2. Pages & UI Routes

| Route | Page | Description |
|-------|------|-------------|
| `/login` | LoginPage | JWT authentication (email/password) |
| `/` | MyProductsPage | Dashboard — all tracked products with KPIs, filters, sorting, CSV export |
| `/insights` | InsightsPage | Market intelligence — leaderboard, top sellers, trending categories, gaps, price wars, restock opportunities |
| `/alerts` | AlertsPage | Price drop/increase, OOS, back-in-stock, low-stock alert management + event feed |
| `/discounts` | DiscountsPage | Discount tracker — top % off, top SAR savings, timeline heatmap, aggression leaderboard |
| `/scanner` | ScannerPage | Price Opportunity Scanner — overpriced items, quick wins, well-positioned, undercut analysis |
| `/stores` | StoreRegistryPage | Store management — add/edit/delete stores, trigger manual crawls, pause scheduler, view crawl logs |
| `/stores/:id` | CompetitorProfilePage | Deep-dive into a single competitor — revenue trends, top products, category distribution, OOS items |

### Shared Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Sidebar | `components/Sidebar.jsx` | Navigation, language toggle (AR/EN), digest access |
| DigestModal | `components/DigestModal.jsx` | Weekly Market Intelligence Digest viewer |
| ProductDetailPanel | `components/ProductDetailPanel.jsx` | Slide-out panel with price history charts, store comparison, velocity graph |
| SeasonalAnnotations | `components/SeasonalAnnotations.jsx` | Saudi seasonal event markers on Recharts charts |

---

## 3. API Endpoints

### Authentication
| Method | Endpoint | Auth | Rate Limit | Description |
|--------|----------|------|------------|-------------|
| POST | `/api/auth/register` | No | 5/min/IP | Create account |
| POST | `/api/auth/login` | No | 5/min/IP | Login → sets httpOnly cookie |
| GET | `/api/auth/me` | Yes | — | Get current user |
| POST | `/api/auth/logout` | No | — | Clear auth cookie |

### Health & System
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/health` | No | System health: MongoDB, scheduler jobs, Playwright, last crawl, uptime |
| GET | `/api/` | No | API root status message |
| GET | `/api/scheduler/status` | Yes | APScheduler job listing |
| POST | `/api/scheduler/toggle-pause` | Yes | Pause/resume all crawl jobs |

### Stores
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/stores` | Yes | List all stores with product counts and next crawl time |
| POST | `/api/stores` | Yes | Add a new store |
| PUT | `/api/stores/{store_id}` | Yes | Update store config |
| DELETE | `/api/stores/{store_id}` | Yes | Remove store and unregister crawl job |
| POST | `/api/stores/{store_id}/crawl` | Yes | Trigger manual crawl (waterfall: Tier 1→2→3) |
| GET | `/api/stores/{store_id}/crawl-logs` | Yes | Crawl history for a store |
| GET | `/api/stores/{store_id}/profile` | Yes | Full competitor profile with KPIs, revenue trends, top products |

### Products
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/my-products` | Yes | Dashboard product list with market metrics |
| GET | `/api/products` | Yes | Paginated product catalog |
| GET | `/api/products/{sku}` | Yes | Product detail with per-store pricing |
| GET | `/api/products/{sku}/history` | Yes | Price history by store over N days |
| GET | `/api/products/{sku}/velocity` | Yes | Sales velocity (daily units, rolling avg) |
| GET | `/api/export/products` | Yes | CSV export of product data |

### Insights
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/insights/summary` | Yes | Market KPIs: SKUs, price drops, gaps, spread, confidence |
| GET | `/api/insights/leaderboard` | Yes | Revenue leaderboard by store |
| GET | `/api/insights/top-sellers` | Yes | Top 20 products by estimated sales |
| GET | `/api/insights/trending` | Yes | Category-level sales trends |
| GET | `/api/insights/gaps` | Yes | Products missing from stores |
| GET | `/api/insights/price-wars` | Yes | Highest price spreads across stores |
| GET | `/api/insights/restock-opportunities` | Yes | OOS at some stores, in-stock at others |

### Discounts
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/discounts/top-pct` | Yes | Highest % discounts |
| GET | `/api/discounts/top-amount` | Yes | Highest SAR savings |
| GET | `/api/discounts/timeline` | Yes | Weekly discount activity heatmap |
| GET | `/api/discounts/aggression` | Yes | Store discount aggression scoring |

### Scanner
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/scanner/opportunities` | Yes | Overpriced items, quick wins, well-positioned, undercut analysis |

### Alerts
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/alerts` | Yes | List user's alerts |
| POST | `/api/alerts` | Yes | Create alert (price_drop, price_increase, out_of_stock, back_in_stock, low_stock) |
| PUT | `/api/alerts/{alert_id}/toggle` | Yes | Enable/disable alert |
| DELETE | `/api/alerts/{alert_id}` | Yes | Delete alert |
| GET | `/api/alerts/feed` | Yes | Triggered alert events |
| POST | `/api/alerts/check` | Yes | Manually evaluate alerts against latest snapshots |

### Digests
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/digests` | Yes | List past weekly digests |
| GET | `/api/digests/latest` | Yes | Most recent digest |
| POST | `/api/digests/generate` | Yes | Trigger digest generation now |

### Saved Filters
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/saved-filters` | Yes | List saved filter presets |
| POST | `/api/saved-filters` | Yes | Save a filter preset |

---

## 4. Crawler Architecture

### 3-Tier Waterfall System (`crawlers.py`)

The crawler attempts each tier in order. If one fails, it falls through to the next.

| Tier | Method | Speed | Confidence | Function |
|------|--------|-------|------------|----------|
| **Tier 1** | JSON API endpoints | Fast (~2s) | 92-98% | `crawl_salla_tier1()` |
| **Tier 2** | Playwright XHR interception | Medium (~20s) | 85-95% | `crawl_tier2_xhr()` |
| **Tier 3** | HTML parsing (BeautifulSoup) | Slow (~15s) | 70-85% | `crawl_tier3_html()` |

**Waterfall orchestrator**: `crawl_store_waterfall(db, store)` — tries T1→T2→T3, logs results to `crawl_logs` collection.

### Key Crawler Functions

| Function | Purpose |
|----------|---------|
| `crawl_salla_tier1` | Attempts multiple Salla JSON API endpoints with pagination |
| `crawl_tier2_xhr` | Launches headless Chromium, intercepts XHR product responses |
| `crawl_tier3_html` | Downloads HTML, parses product cards with BeautifulSoup |
| `process_crawled_products` | Normalizes raw crawl data → upserts products + snapshots to MongoDB |
| `crawl_store_waterfall` | Orchestrator — cascading tier attempts with logging |
| `extract_brand` / `guess_category` / `guess_animal` | NLP helpers for product classification |

### Scheduling

- **APScheduler** (AsyncIOScheduler) registered at startup
- Priority 1 stores: every 4 hours | Priority 2+: every 8 hours
- Staggered start offsets to avoid concurrent crawl storms
- Weekly digest: Sunday 05:00 UTC (08:00 Riyadh)
- Global pause toggle via `/api/scheduler/toggle-pause`

---

## 5. Database Schema (MongoDB)

| Collection | Key Fields | Indexes |
|------------|------------|---------|
| `users` | email, password_hash, name, role, created_at | email (unique) |
| `stores` | id, name, domain, platform, base_url, crawl_frequency_hrs, is_active, priority, last_crawled_at | domain (unique) |
| `products` | id, sku, name_ar, name_en, brand, category, animal_type, weight_kg, image_url, first_seen_at | sku (unique) |
| `product_snapshots` | id, product_id, store_id, store_name, sku, price, original_price, discount_pct, in_stock, qty_available, source_tier, confidence_score, crawled_at | (sku, crawled_at), (store_id, crawled_at), product_id |
| `alerts` | id, user_id, product_sku, category, store_id, alert_type, threshold, channel, is_active, triggered_count | — |
| `alert_events` | id, alert_id, user_id, product_sku, store_name, alert_type, old_value, new_value, triggered_at | — |
| `crawl_logs` | id, store_id, store_name, tier_attempted, tier_used, http_status, products_found, products_new, snapshots_created, duration_secs, completed_at | — |
| `market_digests` | id, generated_at, week_start, week_end, delivery_status, content | — |
| `saved_filters` | id, user_id, name, filters, created_at | — |

**Seed Data**: 7 stores, 200+ products (Saudi pet market brands: Royal Canin, Whiskas, Hills, Purina, etc.), 90 days of simulated snapshot history.

---

## 6. Security Features

| Feature | Implementation |
|---------|---------------|
| **Authentication** | JWT tokens in httpOnly cookies (SameSite=Lax, 24h expiry) |
| **Rate Limiting** | slowapi — 5 attempts/minute/IP on `/api/auth/login` and `/api/auth/register` |
| **Security Headers** | CSP, X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy: strict-origin-when-cross-origin |
| **CORS** | Configurable origins via `CORS_ORIGINS` env var |
| **Password Hashing** | bcrypt |
| **JWT Secret** | Generated via `secrets.token_hex(64)`, stored in env only |

---

## 7. Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Tailwind CSS, Shadcn/UI, Recharts, Zustand, react-i18next |
| Backend | FastAPI, Motor (async MongoDB), APScheduler, slowapi |
| Crawler | Playwright (Chromium), BeautifulSoup4, httpx |
| Database | MongoDB 7 |
| Auth | PyJWT, bcrypt, httpOnly cookies |
| Deployment | Docker Compose, Nginx reverse proxy |

---

## 8. Deployment Package (`/app/deploy/`)

| File | Purpose |
|------|---------|
| `backend.Dockerfile` | Python 3.11 + Playwright/Chromium + Arabic fonts |
| `frontend.Dockerfile` | Node 20 build → Nginx static serve |
| `docker-compose.yml` | 4-service stack: MongoDB + Backend + Frontend + Nginx |
| `nginx.conf` | Reverse proxy with rate limiting, SSL-ready (commented HTTPS block) |
| `nginx-frontend.conf` | SPA routing + static asset caching |
| `.env.example` | Production environment template with all required variables |
| `DEPLOYMENT_GUIDE.md` | Step-by-step deployment instructions for AWS Bahrain / Ubuntu VPS |
| `start.sh` | One-command deployment launcher with validation and health checks |

### Quick Deploy (AWS Bahrain / Ubuntu VPS)
```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sudo sh

# 2. Clone code to ~/daleel-pets, arrange structure per DEPLOYMENT_GUIDE.md

# 3. Configure
cd ~/daleel-pets/deploy
cp .env.example ../.env
# Edit ../.env → set JWT_SECRET, ADMIN_PASSWORD, CORS_ORIGINS, REACT_APP_BACKEND_URL

# 4. Launch
chmod +x start.sh && ./start.sh

# 5. SSL (optional but recommended)
# Follow DEPLOYMENT_GUIDE.md Step 4
```

---

## 9. Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MONGO_URL` | Yes | — | MongoDB connection string |
| `DB_NAME` | Yes | daleel_pets | Database name |
| `JWT_SECRET` | Yes | — | 64+ char hex secret for JWT signing |
| `ADMIN_EMAIL` | No | admin@daleelpets.com | Seed admin email |
| `ADMIN_PASSWORD` | Yes | — | Seed admin password |
| `CORS_ORIGINS` | Yes | * | Comma-separated allowed origins |
| `PLAYWRIGHT_BROWSERS_PATH` | No | /pw-browsers | Chromium browser binary path |
| `REACT_APP_BACKEND_URL` | Yes | — | Public URL for API calls (baked into frontend build) |

---

## 10. Monitored Stores (Seed)

| Store | Domain | Platform | Priority | Crawl Frequency |
|-------|--------|----------|----------|-----------------|
| Zarafa | zarafaksa.com | Salla | 1 | Every 4h |
| Panda Store | matjarpanda.com | Salla | 1 | Every 4h |
| Lana Pets | lanapets.com | Salla | 1 | Every 4h |
| Cute Pets | cutepets.com | Shopify | 1 | Every 4h |
| Hamtaro | hamtaro.sa | Salla | 2 | Every 8h |
| Caty Store | caty-store.com | Salla | 2 | Every 8h |
| Petsy | petsysa.com | Salla | 2 | Every 8h |

---

## 11. What's MOCKED (Not Yet Integrated)

| Feature | Current State | Required Integration |
|---------|--------------|---------------------|
| Email alerts | Logged to console | Resend API |
| Weekly digest delivery | Logged to console | Resend API |

---

## 12. Future Roadmap

| Priority | Feature | Description |
|----------|---------|-------------|
| P0 | Resend Email Integration | Real email delivery for alerts + weekly digest |
| P1 | Tier 4 Crawler | Buyer account layer — encrypted credentials, OOS notifications, wishlist signals |
| P2 | Multi-tenant | Per-user store assignments and role-based access |
| P2 | Webhook notifications | Slack/Telegram alert channels |

---

## 13. Test Credentials

| Account | Email | Password |
|---------|-------|----------|
| Admin | admin@daleelpets.com | admin123 |

**Auth flow**: POST `/api/auth/login` → httpOnly cookie set → all subsequent requests authenticated via cookie.
