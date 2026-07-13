# Pet-Crawler — Saudi Pet-Supplies Market Intelligence (Daleel)

SKU-level competitor price intelligence for the Saudi pet-supplies market,
benchmarked against **pets-houses.com** (the owner's store). Functionally
equivalent to commercial SKU-watch tools (myskuwatch / Priceva / Skuuudle):
crawl competitor storefronts on **Salla** and **Zid**, match their products to
your catalog by barcode/SKU, and track prices, discounts, stock, and market
share over time.

## What it does

- **Store crawling (tiered waterfall)** — per store: Tier 1 public JSON
  products API (`/api/v1/products`, Salla + Zid), Tier 2 XHR interception via
  headless Chromium, Tier 2.5 storefront category walking (stores with the API
  disabled), Tier 3 HTML scraping, optional Tier 4 authenticated buyer-account
  crawl (extra data like exact stock quantities; supports OTP login flows).
- **Own-store sync** — pets-houses.com (Zid) is synced into `my_products` via
  the Zid Merchant API when `ZID_API_TOKEN` is set, else via public crawl.
  This catalog is the benchmark for all comparisons.
- **Matching engine** — competitor snapshots matched to your SKUs by EAN
  barcode (definitive) or exact SKU string; no fuzzy name matching. Weight and
  pack-size guards prevent 4kg vs 15kg false positives.
- **Analytics** (FastAPI + dashboard): price comparison per SKU, price history,
  discounts/offers, out-of-stock and restock detection, recently-added
  products, estimated sales velocity (from quantity deltas between crawls),
  market share (catalog share + sales-estimate share), price-war detection,
  alerts, weekly market digest, CSV export.
- **Scheduling** — APScheduler daily crawl window (04:00–04:55 KSA), 6-hourly
  own-store sync, weekly digest.

## Repo layout

| Path | Purpose |
|---|---|
| `backend/server.py` | FastAPI app: auth/RBAC, stores, insights, alerts, digest, import/export |
| `backend/crawlers.py` | Tiered Salla/Zid crawlers + own-store sync |
| `backend/matcher.py` | Barcode/SKU matching engine |
| `backend/store_registry.py` | **Registry of all tracked stores** (own + competitors) |
| `backend/run_market_crawl.py` | One-command headless pipeline: crawl → match → report |
| `backend/core/`, `backend/models/` | Metrics/utils, Pydantic schemas |
| `frontend/` | React dashboard (CRA + Tailwind + shadcn) |
| `reports/` | Generated market reports (gitignored) |

## Quick start

```bash
# 1. MongoDB on localhost:27017 (or FerretDB for restricted environments)
# 2. Configure backend
cd backend
cp .env.example .env        # fill JWT_SECRET + ENCRYPTION_KEY, set SEED_DEMO_DATA=false
pip install -r requirements.txt   # emergentintegrations is optional/private — safe to skip
python -m playwright install chromium chromium-headless-shell

# 3. Full pipeline (crawl all active stores → own-store sync → matching → report)
python run_market_crawl.py

# 4. Or run the API + dashboard
python -m uvicorn server:app --host 0.0.0.0 --port 8001
cd ../frontend && yarn && yarn start
```

`run_market_crawl.py` writes `reports/<timestamp>/`:
`summary.json`, `market_share.csv`, `price_comparison.csv`, `discounts.csv`,
`out_of_stock.csv`, `recently_added.csv`, `crawl_status.csv`.

Price history accumulates one snapshot per SKU per crawl — run daily (the API
server's scheduler does this automatically) to build trends, sales estimates,
and restock detection.

## Store registry (July 2026)

All tracked stores live in `backend/store_registry.py` — 47 stores: the own
store, ~40 Salla/Zid competitors (verified via platform URL fingerprints), and
5 inactive non-Salla/Zid context players (Petzone, Pet Arabia, …). Add a store
by appending to `REQUIRED_STORES`; `ensure_stores()` syncs the DB on startup.

## Network requirements

The crawlers need outbound HTTPS to the store domains (plus
`cdn.playwright.dev` for browser install and, if used, `api.zid.sa` and the
Webshare proxy). In restricted/sandboxed environments (e.g. Claude Code remote
sessions with a locked-down egress policy) crawls fail with proxy 403s — grant
the environment full/trusted network access, or run on infrastructure that can
reach the stores. All failures degrade gracefully into `crawl_logs`.
