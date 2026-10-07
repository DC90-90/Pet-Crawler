# DALEEL — Full System Report
### What it does · how it works · where every number comes from · why it can disagree with real life
_Written Sep 10 2026 (iter81). Production: https://saudi-pets-monitor.emergent.host_

---

## 1 · What Daleel is

Daleel is a competitor price- and market-intelligence platform for a Saudi store
owner (Pets Houses, on Zid). It crawls competitor storefronts in the Saudi pet
market every day, matches their products to the owner's catalogue by **barcode
first, SKU second**, and turns the resulting time-series into pricing,
assortment and share analytics.

One sentence per screen:

| Screen | The question it answers |
|---|---|
| **My Products** | For every product I sell: am I cheaper or dearer than the market, who else carries it, how much did it move, what is my share? |
| **Price & Market Intel** | Where should I reprice today, who is strongest in the market, what is trending, where are the gaps and price wars? |
| **Market Share** | Of the sales Daleel can actually MEASURE inside the tracked market, how much is mine — by product, brand, category, and what am I missing? |
| **Price Scanner** | Which of my products are priced above the market low, who is the cheapest seller, and what is the realistic money left on the table? |
| **Discounts** | Who is discounting what, how deep, for how long, how aggressively? |
| **Alerts** | Tell me when a competitor undercuts me, drops a price, or goes out of stock. |
| **Stores** | The tracked fleet: platform, crawl status, per-store profile, manual crawl, credentials. |
| **Import / Settings / Users** | Catalogue import + CSV export, Zid connection, nightly archive, RBAC per page. |

---

## 2 · End-to-end pipeline

```
   ┌── competitor storefronts (Salla / Zid) ──┐        ┌── my store (Zid Merchant API) ──┐
   │  multi-tier crawler (crawlers.py)        │        │  sync_own_store_prices()        │
   │  politeness + TLS impersonation          │        │  every 6 h, 23 pages            │
   └──────────────┬───────────────────────────┘        └───────────┬────────────────────┘
                  │ product_snapshots (price, sale, qty,            │ my_products
                  │ sold-counter, barcode, variants, url, tier)     │ (+ VAT basis tag)
                  ▼                                                 ▼
          ┌───────────────── matcher.py (barcode → SKU, 14-day window) ─────────────────┐
          │                           product_matches                                   │
          └───────────────────────────────┬──────────────────────────────────────────────┘
                                          ▼
   write-time rollups  ─ metric_daily_rollups · sku_store_coverage · sku_sales_daily
   append-only ledger  ─ daily_ledger · daily_ledger_store      (KSA days, sealed nightly)
   own-store truth     ─ own_store_orders  (exact invoices, needs Zid OAuth)
                                          ▼
   read layer: dashboard_cache + page caches + 60 s TTL cache → ~129 /api endpoints → React UI
                                          ▼
   nightly archive to object storage (gzip JSONL per store per KSA day, immutable)
```

---

## 3 · The crawler layer (`crawlers.py`, 3,880 lines)

**Waterfall per store** — the first tier that answers wins, and the tier used is
recorded in the crawl log:

| Tier | Method |
|---|---|
| 1 | Storefront/platform JSON API (`/products.json`, Salla store API), endpoint auto-discovery + per-store caching, full pagination |
| 2 | Playwright XHR interception — headless browser, auto-scroll, read the payloads the page itself fetches |
| 2.5 | Salla **detail supplement** — one call per product to the product-details route to recover barcodes |
| 3 | Rendered-HTML scraping with platform-specific selector sets |
| 3.5 | Salla **DOM barcode read** — Playwright reads the barcode off the product page when the API hides it |
| Storefront-categories | Salla full-catalogue walk: resolve the store id from the storefront HTML, pull up to 100 categories from the Salla categories API, then paginate every category (this is how 2,000–4,000-product stores get covered) |
| 4 | Authenticated merchant login (encrypted credentials, live OTP queue + `OtpBanner`) for exact stock — built, used sparingly |

**Fetch policy** (`fetch_policy.py`): per-host adaptive pacing (0.2 s → 8 s under
pushback, decaying after 15 clean requests), jitter, `Retry-After` honoured,
browser-shaped headers with a rotating UA pool and `Accept-Language: ar-SA`, and
a final attempt through **curl_cffi Chrome TLS impersonation** for fingerprint
blocks. 404 is an answer, not a retry. Never raises — callers still branch on
status codes. One CutePets crawl used to log 277 × HTTP 429; after this, zero.

**Circuit breakers**: a supplement stage aborts after 30 CONSECUTIVE failures
(`failed_aborted_after_consecutive`) and when a host has been pushed to maximum
pacing (`aborted_host_saturated`) — recorded in the crawl log, not hidden.

**Soft-block guard**: if a crawl returns fewer than 20 % of the median of the
last 10 successful crawls (baseline ≥ 50 products, ≥ 3 samples of history), the
crawl is flagged `soft_blocked` and **nothing is persisted** — the previous good
cohort survives instead of being overwritten by an empty HTTP 200. Small and
brand-new stores pass through by design.

**Proxy**: Webshare Saudi residential is OFF (`PROXY_ENABLED=false`) because the
subscription answers 402; crawling runs direct. `GET /api/admin/proxy-health`
reports the live verdict and flips back automatically when a subscription is
attached.

**Data hygiene**: `*.example.com` (RFC 2606) is deleted on boot and refused by
both `POST /api/stores` and `/api/crawler/ingest`, so test stores cannot
reappear on the Stores page.

Every crawl writes a `crawl_log`: tier, HTTP statuses per endpoint tried,
products found, snapshots created, duration, proxy status, soft-block flag,
supplement outcomes.

---

## 4 · My own store, and VAT

`sync_own_store_prices()` reads the **Zid Merchant API** every 6 hours (~2,233
products): SKU, EAN-validated barcode, Arabic/English name, price, quantity,
`present_on_store`. This is first-party data, never throttled, never proxied.

**VAT is the single most common source of "wrong price" reports**, so the rule
is explicit. Every `my_products` row carries a `price_basis` tag; a closed
whitelist (`storefront_inc_vat`, `merchant_computed_inc_vat`,
`merchant_assumed_inc_vat`, `merchant_hidden_from_storefront_inc_vat`,
`merchant_non_taxable`, `merchant_hidden_non_taxable`) is trusted as written.
Anything else — an empty tag, a legacy import, the retired
`merchant_unknown_tax` — is treated as ex-VAT and grossed by **1.15**
(`_effective_own_price`). One read path that forgot to project `price_basis` is
what once showed 563.50 SAR as 648.02 on the My Products row while the detail
panel showed the right number; both now project the field, and a generic test
fence fails the build if any future projection omits it.
`GET /api/admin/own-sku-diagnose?sku=…` prints the raw row, the latest snapshot,
the resolved price and the branch taken — one call to triage any price report.

---

## 5 · Identity and matching (`matcher.py`, 762 lines)

Deliberately conservative: **a wrong match is worse than no match.**

1. **Barcode** (confidence 99–100): GTIN-14 canonicalisation so `052742024363`
   and `52742024363` join; candidates include the competitor's primary barcode
   **and** its `variant_barcodes` / `variant_skus` arrays; junk/placeholder
   barcodes are rejected.
2. **SKU string** (confidence ≥ 85): normalised comparison, Zid `-suffix`
   variant safety, `SUSPICIOUS_PRICE` flag on extreme ratios.
3. **Name matching is REMOVED** (your decision) — it produced false positives.

Guards: confidence floor 85; pack-indicator guard (Arabic token-boundary aware,
count-first descriptors like `24 Pieces*400g`); refusal to write a match on a
synthetic `S-…` SKU; 14-day candidate window (`MATCH_WINDOW_DAYS = 14`) — both a
quality rule and what keeps the aggregation alive at ~1 M snapshots; and a
coverage guard that refuses to run on a partial catalogue (see §12-A).

"Stores Carrying" does **not** depend on a match row: `_seller_snapshots`
discovers sellers through four key classes (`sku`, `barcode`, `variant_skus`,
`variant_barcodes`) plus the match rows, each as its own indexed aggregation
(discover distinct `(store_id, sku)` pairs → bounded per-pair read), with a
180-day lookback and a 7-day staleness label — a store crawled 31 days ago is
shown WITH "price as of …", never silently dropped.

---

## 6 · How "units sold" and "revenue" are derived — the honesty hierarchy

Daleel never blends sources. Every number carries the method that produced it:

| Rank | Source | Label | What it really is |
|---|---|---|---|
| 1 | `orders_exact` | **Actual** | My own Zid order ledger — real invoices, cancelled/refunded statuses excluded, KSA-day buckets |
| 2 | `sold_counter_diff` | **Measured (approx.)** | A Salla store's published cumulative "sold N times" counter, diffed between crawls. Resets skipped, capped readings excluded, single step capped at 5,000 |
| 3 | `stock_depletion` | **Measured (floor)** | Quantity dropping between two crawls. A FLOOR by construction: sell-then-restock inside one interval is invisible |
| 4 | `measured_zero` | **Zero is a fact** | The store publishes a signal, was crawled ≥ 2× in the window, and this product never moved |
| 5 | `unavailable` | **Withheld + reason** | No signal, or fewer than 2 crawls. The number is NOT rendered as 0 — the reason is shown (`store_not_crawled_in_window`, `fewer_than_two_crawls_in_window`, `no_sales_signal_published`) |

Anti-noise clamps on the derived paths (`core/utils.py`): placeholder
quantities `{99,100,999,1000,…}` ignored; max **10** units per interval;
max **30** units per SKU per day; max **50** sold-counter units per interval;
only snapshots with `confidence_score ≥ 85` feed aggregation (Tier-3 HTML noise
excluded).

**The ±50 % Salla category-velocity estimate** (`salla_revenue_estimate.py`) is
a separate thing: it projects a store's revenue from the velocity measured on
Zid stores × its own catalogue and prices. It is allowed ONLY on the Market
Strength Ranking / Store Profile, always labelled `ESTIMATE ±50 %` with its
range, and is **fenced out of Market Share by test** — a ±50 % numerator over a
partial denominator is not a share.

**The ledger** (`ledger.py`): `daily_ledger` stores observation LEVELS per
(store, SKU, KSA day) — never deltas — plus a per-store day row whose status can
be `ok | partial | no_data`, which is how ABSENCE is recorded as a fact. A
nightly seal at 21:30 UTC (00:30 KSA) freezes the day that ended; sealed rows
are immutable. "Sealed days only" vs "Including today (partial)" on Market Share
is exactly this boundary.

---

## 7 · Storage and caching

| Collection | Role |
|---|---|
| `product_snapshots` | The raw observation log (price, sale_price, discount_pct, qty, in_stock, sold_count_cumulative, barcode, variant arrays, product_url, tier, confidence, crawled_at) |
| `my_products` | My catalogue from Zid (+ `price_basis`) |
| `product_matches` / `match_blacklist` | Identity links + manual rejections |
| `metric_daily_rollups`, `sku_store_coverage`, `sku_sales_daily` | Write-time rollups — rebuilt from snapshots after each crawl (a cache, not history) |
| `daily_ledger`, `daily_ledger_store` | Append-only KSA-day history (the real audit trail) |
| `own_store_orders` | Exact own-store invoices |
| `dashboard_cache` + page caches | Pre-computed My Products / Insights / Price-Intel / Market-Share payloads |
| `crawl_logs`, `sync_runs`, `backfill_runs`, `archive_files`, `migrations` | Operational trails |

Reads are served from caches: a 60 s TTL cache on heavy endpoints, plus
`dashboard_cache` / page caches rebuilt **after a crawl** or **after the
6-hourly own-store sync** — so a read-side fix or a price change can take up to
6 hours to appear unless you call `POST /api/admin/refresh-caches`.

35 indexes are applied from one registry, each in its own attempt
(`POST /api/admin/ensure-snapshot-indexes` re-applies them live and lists what
MongoDB actually has). `GET /api/admin/perf-probe?sku=` returns EXPLAIN plans
with a `collscan` boolean per key class.

---

## 8 · Screen by screen — what is computed from what

**My Products** (`/api/my-products`): per product — my VAT-resolved price,
competitor min/avg/max, gap %, market-position badge, stock signal, units sold
(mine and market), market share %, `num_competitors` ("X carry · Y priced"
tooltip: all sellers incl. OOS vs sellers with a usable price). Windows
7/14/30/90 D, search, category/stock/position filters, saved filters. KPI band:
products tracked, units sold (est.), market revenue (est.), my revenue (est.),
avg market share (over the products where a share is computable, with
`share_sample_size`), market coverage % (matched ÷ catalogue). Detail panel:
every seller with live/stale/OOS labels, price history, velocity, match method
and confidence.

**Price & Market Intel** (merged Price Intel + Insights): repricing segments,
Market Position, **Market Strength Ranking** (unified revenue axis:
exact > measured-approx > estimate > none), Revenue Leaderboard, confidence
distribution, price wars, restock opportunities, top sellers, trending, gaps,
product sales insights. The ranking and the leaderboard are both normalised to
the same monthly axis per store.

**Market Share** (`market_share.py`, 6 endpoints + export): one page-cached
dataset per window sliced by Overview / My Products / Product / Missing
Products / Brands / Categories / Methodology. Every row carries
`sellers_total` ("Stores carrying") vs `sellers_with_sales` ("Sales data
available") as two separate columns; a product no other measurable seller
carries is flagged `sole_seller` and EXCLUDED from the headline KPI (otherwise
the headline drifts to 100 % as the catalogue grows); only `contested` rows feed
the headline. A ≥ 3× seller price spread marks the row LOW confidence with the
ratio stated. Every filter recomputes the KPIs through the same
`summarize()` the unfiltered view uses, and the CSV carries source label,
confidence, confidence reason, unavailable reason and the calculation method per
row. Methodology states verbatim: *"Market share is based on tracked measured
data inside Daleel, not the total Saudi market."*

**Price Scanner**: one row per MY product (not per seller — that was the iter77
bug), `my_price` from the same VAT resolver everything else uses, `sellers[]`
with `is_own/is_lowest/is_highest`, cheapest-seller name, market low/avg/high,
and uplift = `(my price − market low) × units I actually sold` (orders ledger
first, sealed rollups second, `units_basis` stated). Competitors priced above
market sit in their own collapsible section, explicitly not counted in my KPIs.
**Pack Size Guard** (`pack_guard.py`) runs here first: explicit slug evidence
(`…-3-5-جرام-…` is a 3.5 g single against my 15 g pack) plus a corroborated
price cluster (≥3× below the cluster my price and the other sellers form; 5×
when only two prices corroborate), with a discount escape so a genuine
clearance is still shown. Everything excluded is listed in plain English under
"Excluded From Market Low".

**Discounts**: biggest % and biggest SAR discounts, timeline, per-store
aggression, days on discount.

**Alerts / digests**: price-drop, stock-out, undercut thresholds, auto-generated
suggestions, in-app notification bell, weekly market digest (Sundays 05:00).

**Stores / Competitor profile**: fleet state, per-store crawl trigger and logs,
catalogue size, pricing posture, discount behaviour, revenue with its tier chip,
**Sales by Category weighted by units sold** (empty state when there are no
measured sales — never the catalogue-composition pie).

**Settings**: Zid Orders OAuth panel, **Price History Archive** panel (nights,
files, rows, size, download), cache refresh, coverage report, proxy health.

**Users / RBAC**: JWT in httpOnly cookies, login rate-limited 5/min/IP,
super-admin (immutable, env-driven since iter81), admin, user + per-user
`allowed_pages` across the 10 page keys.

**Archive** (`archive.py`): every KSA night becomes an immutable folder on
Emergent object storage — `daleel/archive/{date}/snapshots/{store}.jsonl.gz`,
`rollups/*.jsonl.gz`, `manifest.json`, indexed in `archive_files`, downloadable
through the backend behind the super-admin check. Idempotent per night. First
real run: 11 files, 45,006 rows, 975 KB.

---

## 9 · The clock (15 scheduler jobs)

| Time (UTC) | Time (KSA) | Job |
|---|---|---|
| 01:00 – 01:55, 5-min offsets | 04:00 – 04:55 | One daily crawl per active store (11 stores) |
| every 6 h | — | Own-store Zid sync + additive rematch |
| 21:30 | 00:30 | Ledger day-seal (+ `no_data` rows for silent stores) |
| 03:00 | 06:00 | Nightly price-history archive |
| Sun 05:00 | Sun 08:00 | Weekly market digest |

On-demand: `POST /api/admin/backfill` (background, sequential, then an additive
rematch — the only safe way to re-crawl a big Salla store, because a synchronous
`/stores/{id}/crawl` outlives the ingress timeout and dies before persistence),
`POST /api/import/run-matching` (additive), `POST /api/admin/rematch` (purges
first — fleet-wide only when everything is fresh), `POST /api/admin/refresh-caches`,
`POST /api/admin/ensure-snapshot-indexes`.

---

## 10 · WHY DALEEL'S NUMBERS CAN DIFFER FROM REALITY

Ranked by how much they move a number. Most of these are structural — they are
the price of measuring a market from the outside — and each one is labelled in
the UI rather than hidden.

### A. Competitor sales are INFERRED, never reported
No Saudi storefront publishes its sales. Daleel derives units from a stock drop
or a bucketed sold-counter between two crawls. Consequences:
* **Floor, not truth.** Sell 5 and restock 5 between two crawls → 0 observed.
* **One crawl a day** → everything inside a 24-hour interval collapses to one delta.
* Clamps (10/interval, 30/SKU/day) deliberately cut spikes, so a genuine
  bestseller is UNDER-reported rather than letting a restock look like a sale.
→ Treat competitor units as a **lower bound**, and compare trends, not absolutes.

### B. My own units are also a floor until Zid OAuth is connected
`/v1/managers/store/orders` needs a **partner-app OAuth token** alongside the
store token. The partner app is not approved yet, so my own sales come from
stock depletion too, and every affected row says `stock_depletion`. The moment
Settings → Zid Orders connects, those rows upgrade to `orders_exact` / **Actual**
with no code change — and my revenue, my share and the Scanner's uplift all
become exact.

### C. Salla's sold badge is bucketed and capped
"تم بيعه أكثر من 1000 مرة" stops moving while sales continue, and the number is
rounded for display. Capped readings are EXCLUDED (not diffed as 0), so for the
best-selling products of a Salla store Daleel measures nothing rather than
something wrong — a real under-count, by choice.

### D. Crawl staleness, and the 14-day matcher window
A store that has not been crawled inside `MATCH_WINDOW_DAYS = 14` contributes no
match candidates: competitor counts fall, shares shift, and Market Share reports
`store_not_crawled_in_window`. This is the single biggest cause of
"the numbers changed and nothing else happened".
**Right now in preview** every store is 26–43 days stale (the preview pod has
not run a successful crawl window), which is exactly why preview Market Share
withholds so much. On production this is what the §3 backfill fixes — and why
rematching BEFORE the backfill finishes is destructive (the purge deletes rows
it can no longer rebuild).

### E. Coverage: barcodes, synthetic SKUs, variant encoding
The matcher matches on barcodes. A Salla merchant may put the EAN in
`skus[].sku`, or publish no barcode at all; when nothing usable is found the
crawler assigns a synthetic `S-…` id that is never used as identity. Per-store
barcode coverage therefore decides how many of my products that store can be
compared against — `GET /api/admin/coverage-report` (and `/settings/coverage`)
shows `crawled / matched / barcode %` / synthetic % per store. A store with low
barcode coverage looks like it "doesn't carry" products it actually sells.

### F. Pack-size collisions
A competitor's 3.5 g single sachet and my 15 g stick pack can share a barcode
family and a name. Unguarded, that renders as "+445 % overpriced". The guard
(slug evidence + corroborated cluster) is live on the **Scanner only** — My
Products and Price Intel still compute their market low without it, so the same
product can read differently on two screens. (Known inconsistency, §12.)

### G. VAT (15 %) and legacy rows
Zid exposes merchant prices that may be ex-VAT; the storefront shows inc-VAT.
A row with no `price_basis` tag is grossed by 1.15. If a product is genuinely
non-taxable, set `is_taxable=false` in Zid and re-sync — otherwise Daleel will
keep adding 15 % to it. Any single-product dispute is answered by
`/api/admin/own-sku-diagnose?sku=…`.

### H. "Market share" means the TRACKED market
The denominator is 11 tracked stores (10 competitors + mine), restricted to the
sales Daleel can measure in the chosen window — not the Saudi pet market, not
even the full catalogue of those stores. A share that looks "too high" is
usually a thin denominator; that is why `sole_seller` rows are excluded from the
headline and why every row states how many sellers carry it vs how many have
usable sales data.

### I. Sealed vs partial windows
"Sealed days only" excludes today by design (today's deltas are not final). With
few crawl days inside the window, the sealed view legitimately withholds almost
everything and shows a yellow banner; "Including today (partial)" shows the live
picture. Two different numbers, both correct, different definitions.

### J. Caches
A number can be up to 6 hours old (dashboard/page caches rebuild after a crawl
or the own-store sync) plus a 60 s TTL layer. After any pricing change or fix,
`POST /api/admin/refresh-caches`.

### K. Freshness and confidence filters differ per surface — on purpose
The My Products list applies a 7-day price-freshness + confidence filter (so a
20-day-old competitor price drops out → "most expensive of 2"), while the detail
panel deliberately opts out (it shows the whole seller table with "price as of"
labels → "of 3"). Likewise the list's "Mkt:" range is COMPETITOR-only while the
panel's price range includes my own price.

### L. Estimates are catalogue-driven, not demand-driven
The ±50 % Salla estimate scales with assortment size and price, not traffic. Two
stores with the same catalogue get the same estimate however different their
real sales are. It is an order-of-magnitude indicator, labelled and banded, and
it never feeds a share.

### M. Brand and category are heuristics
Brand is extracted from the product name (canonical map + leading-token
heuristic) and category/animal are guessed. Brand is still missing on ~93 % of
crawled competitor products, so brand-level aggregates cover less of the market
than product-level ones. Top Brands returns the top 20 buckets; a product whose
brand is outside that is still reachable by search but not in the chart.

### N. Rounding, currency and mixed-direction text
All money is SAR, rounded to 2 decimals at the edges; percentages are rounded
for display, so a table total can differ from a KPI by a rounding step (the KPI
is computed from the same filtered aggregation, not summed from the page).

### O. Preview ≠ production
Preview has thin, stale data (11 stores, ~2,257 own products, no own-store order
ledger, last crawls 26–43 days old). Never compare a preview number to a
production number — and bugs that only appear at production scale (the
collection-scan hangs of iter73x/y) are invisible here.

---

## 11 · Current bugs and known gaps

### Open — data quality / correctness
| # | Issue | Impact | Where |
|---|---|---|---|
| 1 | **Pack guard runs on the Scanner only** | the same product can show a different market low on My Products / Price Intel than on the Scanner | `pack_guard.py` wired at `server.py` ≈L5974-6011 only |
| 2 | **Scanner still ranks out-of-stock / storefront-hidden products** as opportunities | noise at the top of the list | `/scanner/opportunities` |
| 3 | **Brand missing on ~93 % of crawled products** | brand-level share and Top Brands under-cover the market | `extract_brand_smart` |
| 4 | **Zarafa dark + 4 Salla stores stale** (preview; production needs the backfill run) | those stores contribute no candidates, no sales, no share | `POST /api/admin/backfill` |
| 5 | **Webshare proxy is 402** → no Saudi exit IP | some storefronts may geo-block or throttle a datacenter IP; crawls run direct today | `PROXY_ENABLED=false` |
| 6 | **Salla supplement runtime**: persistence happens AFTER the barcode/DOM supplement, so Zarafa/CutePets crawls run tens of minutes and a restart loses the whole crawl | long backfills are fragile; never edit backend files or redeploy during one | `crawlers.py` |
| 7 | **Market Share withholds a lot in a sealed window** with few crawl days — correct behaviour, but reads as "no data" | use "Including today (partial)" + fix cadence | `market_share.py` |

### Open — blocked on something outside the code
| # | Issue | Needs |
|---|---|---|
| 8 | **Zid Orders API 401** → own units are a floor, not Actual | partner-app approval, then connect on Settings → Zid Orders |
| 9 | **Resend email is MOCKED** — alerts are in-app only | a Resend API key |
| 10 | Webhooks (Slack/Telegram) for soft-blocked crawls and alerts | not built yet (backlog P1/P2) |

### Open — product gaps on the backlog
Alert history (fired-at + price at fire) · share watchlist with weekly movement ·
ledger health card in the UI · nightly scheduling of the Salla category audit ·
new-store rollout (`ACTIVATE_NEW_STORES`, 47 registered stores vs 11 active) ·
sitemap discovery for faster crawling · Mahally/Apify enrichment · auto platform
detection.

### Open — engineering debt
`server.py` is ~11,700 lines and must be split into `routes/` (**your
instruction: do this LAST**). The 46 skipped tests are all conditional (39 of
them belong to two legacy suites bound to the deleted `admin@daleelpets.com`
account and can be deleted on your word).

### Recently fixed (so you do not re-report them)
* **iter81** — production deploy failed to become ready: the startup handler
  awaited the whole boot sequence and crashed the process on any error. Boot is
  now a background task with per-phase fail-soft, a bounded Mongo wait, and
  `boot` state on `/api/health`. Super-admin credentials moved to the
  environment; the unauthenticated `/api/debug/token` endpoint deleted.
* **iter80** — a legacy import had written the placeholder `own-store-id` into
  `my_products.store_id`, so **2,231 of 2,303 products were invisible to the
  matcher**: every rematch said "ok" while matching 68 products. Healed on boot
  + the matcher now refuses to run on a partial catalogue (`match_added` went
  from 6 to 356). All 24 stale-baseline test failures re-axed into invariants;
  suite 1,119 pass / 0 fail.
* **iter77** — the Scanner showed COMPETITORS' prices as "YOUR PRICE" and
  computed uplift as gap × number of sellers.
* **iter73z** — double-VAT on the My Products row (563.50 → 648.02).
* **iter76** — `KeyError: 'units_sold'` 500-ing the Market Strength Ranking on
  the 90-day window.
* **iter73y/x** — product-detail panel hanging for minutes on production
  (unindexed `$or` → collection scans; 35-index registry + bounded seller query).
* **iter75** — own store reported "Failed" while syncing 2,233 products
  (falsy-zero `tier_used`), 277 × HTTP 429 per crawl, and a test suite that was
  wiping the working database.

---

## 12 · How to check any number yourself

```bash
PROD="https://saudi-pets-monitor.emergent.host"
TOKEN=…   # super-admin login

curl -s "$PROD/api/health"                                    # boot state, mongo, scheduler, last crawl
curl -s "$PROD/api/data-freshness"        -H "Authorization: Bearer $TOKEN"   # per-store crawl age + sync health
curl -s "$PROD/api/admin/coverage-report" -H "Authorization: Bearer $TOKEN"   # crawled / matched / barcode% per store
curl -s "$PROD/api/admin/own-sku-diagnose?sku=<sku>" -H "Authorization: Bearer $TOKEN"  # why a price reads as it does
curl -s "$PROD/api/market-share/product/<sku>?days=30" -H "Authorization: Bearer $TOKEN" # every seller + source + reason
curl -s "$PROD/api/market-share/methodology?days=30"  -H "Authorization: Bearer $TOKEN"  # the rules, in writing
python3 backend/tools_prod_verify_market_share.py --url "$PROD" …             # 23 acceptance checks
```

Every figure in the product is reachable through one of those, and every
withheld figure comes with the reason it was withheld.
