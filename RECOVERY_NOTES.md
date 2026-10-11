# Daleel recovery — working notes (branch `daleel/recovery`)

Base: `origin/conflict_130726_1244` (the code emergent.sh deploys; `main` is two months stale).

## Done on this branch

1. **Own-store sync** (`backend/crawlers.py`, `backend/observation_contract.py`)
   - Storefront overlay reads `sale_price` when `effective_price` is absent (live Zid payload shape), so our own discounts are no longer erased.
   - Variant children inherit the listing's `is_taxable`; previously every `has_options` product fell to `merchant_unknown_tax` and lost its price.
   - Merchant API pages fetched before a 401 are kept as `partial`; a partial merchant fetch is preferred over the public storefront fallback (and never triggers archival).
   - Products with no Zid SKU are keyed `Z.<id>` instead of collapsing into one `my_products` row with `sku: ""`.
   - Public-crawl own path uses the sale-aware normalized price (my_products and snapshots agree).
   - Snapshot dedup compares `in_stock` as a tri-state.
   - Archival of unseen products is skipped when the sync source flipped (merchant vs public) and never archives quarantined rows.
   - Own snapshot `offer_id` uses the same key order as `my_products`, so our own sales history is found.
   - Finding F10 kept: unknown tax basis stays untrusted (never grossed).
2. **Registry** (`backend/store_registry.py`): cutepets, hamtaro, zarafa, lanapets on Tier 1 via `/en/api/v1/products` (verified live 10 Oct); caty-store on the bare route; the registry endpoint wins over a stale cached one.
3. **Analytics** (`market_share.py`, `sales_evidence.py`, `price_cohort.py`, `store_views.py`, `evidence_ledger.py`, `server.py`)
   - Market share no longer requires every seller to be `orders_exact` (only our store can be), so a share is computable again; `share_basis` states orders-vs-proxy or proxy-vs-proxy.
   - Exact Zid inventory is no longer discarded by the Salla-era placeholder / `>200` filters; the depletion cap scales with interval length (30 units per 24 h).
   - Pack-size disagreement needs explicit counts on both sides; silence is not "single unit".
   - Legacy blacklist rows keyed by competitor SKU are honoured in cohorts.
   - Manual match confirmation is validated on identity, not on current stock/age.
   - `store_views.latest()` bounded to 30 days (index-friendly); `sales_map` filters unavailable intervals in the query.
4. **Frontend**: alerts page and notification bell no longer gated on the outbound-email capability.
5. **Zid variant parents resolved from the detail route** (`_resolve_zid_variant_parents`): local Mowkly crawl went from 2,053 to 4,864 comparable offers, 0 quarantined, barcodes 1,834 → 3,907. Own-store Merchant path does the same. `sold_products_count` read as the Zid sold counter.
6. **Store-supplied categories captured** on `my_products` and competitor `products` (`store_categories`, `category`, `category_source=store_supplied`), merchandising buckets excluded. Prerequisite for category share; cross-store mapping (`category_map`) is next.

Deployment model confirmed with emergent support: production builds only from the emergent workspace; GitHub is version control. Each release = push a branch here, then paste `EMERGENT_RELEASE_MESSAGE.md` to the emergent agent.

Focused suites: 67 passed / 37 failed vs 62 / 42 on the untouched branch; no new failure families (remaining failures pin retired pre-v2 contracts).

## Blocked (needs a permission change in this Claude session)

The auto-mode safety classifier refused every edit that relaxes a gate, even though the gate is the reason production is empty:

| Change | Why it is needed | File(s) |
|---|---|---|
| Make the release guard opt-in (`RELEASE_GUARD=on`), default off | Every DB write is denied until a stamped build is "activated"; the deployed build is unstamped, so nothing can ever run | `release_database.py`, `release_control.py`, `release_runtime.py`, `release_api.py`, `release_identity.py`, `server.py:124` |
| Restore the boot sequence and in-process scheduler | Boot is read-only; APScheduler never starts; platform crons are all disabled | `server.py` `_boot_sequence`, `register_crawl_job` |
| Freshness window 7 → 14 days (env `MAX_OFFER_AGE_DAYS`) | One quiet week blanks every page | `price_cohort.py`, `stock_evidence.py` |
| Dockerfiles / `craco.config.js` verify stage | Production build refuses an unstamped tree | `deploy/*.Dockerfile`, `frontend/craco.config.js` |
| Market total across mixed sources (`compatible` rule) | Market units are `None` whenever a Zid and a Salla seller coexist | `market_share.py:712, 816` |
| Accept partial merchant rows comment / basis_counts tidy | cosmetic | `crawlers.py` |

## Still to do after unblock

- Push `daleel/recovery`, open PR to `main`, point emergent at it (or merge and redeploy).
- First supervised crawl from a Saudi IP; verify 20 SKUs by hand against storefronts.
- Enable 3×/day Zid crawls, 1×/day Salla.
- Zid partner-app OAuth for exact own orders.

## 11 Oct 2026 (evening) — database starvation under the 90-day legacy scan

Symptom: every analytics page showed "Price analysis is being prepared", and
the backfill crawl finished four stores with 0 snapshots stored
("Observation persistence failed: NetworkTimeout").

Cause: the cohort, market-share, insight and matcher reads scanned 90 days of
the 8.45M-row snapshot collection (almost all legacy v1 rows) on every cache
rebuild, in more than one backend process. The database starved: a
one-document revision read exceeded 15 s and the crawler's own writes exceeded
the 45 s socket timeout.

Fix:
- `observation_contract.v2_since()` / `since_bound()`: v2 observations only
  exist since 2026-10-07 (env `OBSERVATIONS_V2_SINCE` to override), so every
  v2-only read starts there instead of 90 days back.
- `crawl_persistence.retry_transient`: transient database errors during
  persistence are retried (5/20/60 s) instead of discarding the store.
- `my_products_cache.revision` uses the background budget inside a rebuild.
- `POST /api/admin/recover-captures` replays retained captures (with their
  original observed_at) without re-crawling; `GET .../status` to poll.
- Tests pin `OBSERVATIONS_V2_SINCE=2000-01-01` (conftest + reviewed runner)
  because fixtures seed older history.
