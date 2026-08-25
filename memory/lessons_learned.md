# Lessons Learned — Daleel workspace

## NEVER parallel-edit the same file (Aug 1 2026 incident)
Six search_replace edits to server.py were issued in ONE parallel batch (iter67 sync).
Each edit read-modify-writes the whole file → racing writes clobbered edit #2
(`_ledger_obs = []` init) while the other five landed. Result: NameError in the
production ingest path (append executed without init). All tools reported
"Edit was successful" — the loss was silent.

RULES:
1. Multiple search_replace calls touching the SAME file → strictly sequential.
   Parallel batching is fine only across DIFFERENT files.
2. After a multi-hunk merge, verify EVERY hunk landed with a single grep pass
   (grep -n for each anchor) — do not trust per-edit success messages.
3. py_compile does NOT catch missing-init NameErrors (runtime scope) — an
   endpoint-level test or grep verification is required.

## ZIP sync recurring pattern
- /tmp/zipNN extracts are cleaned between sessions — never rely on an old
  extract as a drift reference; use git (auto-commit hashes) instead.
- Full-suite pytest failure counts fluctuate (login rate-limiter 429s hit
  live-API test modules nondeterministically). Compare failure FAMILIES, and
  re-run a spiking module in isolation before calling it a regression.

## Preview cannot reproduce production performance bugs (Aug 10 2026, iter73x → iter73y)
The preview DB has ~0 product_snapshots; production has ~300K. A query that
"responds in 108ms" in preview proved nothing, so iter73x shipped an
index-only fix for a hang that was structural — and the client redeployed to
the SAME hang.

RULES:
1. For any perf report, fix the query SHAPE so cost is bounded by construction
   (per-key-class indexed lookups + explicit `limit` + `maxTimeMS`), never by
   trusting the planner to index-union an `$or`. One unindexed or multikey
   branch turns the whole `$or` into a COLLSCAN.
2. Never ship an aggregation over product_snapshots without a `$match`
   (`/api/data-freshness` scanned the whole collection every 60s).
3. Indexes belong in ONE registry applied with a per-index try/except. A single
   shared try/except means the first failure silently skips every index after
   it. Anything created only inside `seed_database()` DOES NOT EXIST in
   production — that function early-returns on a live DB (this is how
   `product_matches` ended up completely unindexed).
4. Every fetch on the frontend needs a timeout + a visible error state. A bare
   `.catch(console.error)` renders as an eternal "Loading…" to the client.
5. Ship a diagnostic endpoint with the fix (`/api/admin/perf-probe`): EXPLAIN
   plans + stage timings from production beat any local guess.

## A projection can silently change a PRICE (Aug 10 2026, iter73z)
`_effective_own_price` grosses a my_products row by 1.15 when `price_basis` is
absent (legacy ex-VAT assumption). Two read paths projected `price_basis` away,
so already-inc-VAT rows were grossed a SECOND time: client's storefront 563.50
rendered as 648.02 on My Products while the detail panel (which projected the
field) showed 563.50. Same helper, same DB row, two different prices.

RULES:
1. If a helper's OUTPUT depends on a field, every caller's projection must
   include that field. Add a source-level fence test (find the projection,
   check the enclosing function for the helper call) — comments do not hold.
2. Cross-surface disagreement on the SAME value is the tell: diff the read
   paths' projections before touching any pricing rule.
3. `/api/my-products` + Insights + Price-Intel are served from
   `db.dashboard_cache`, rebuilt only after a crawl or the 6h own-store sync.
   Any read-side fix needs POST /api/admin/refresh-caches after deploy or the
   client keeps seeing the old number.

## An external dependency must never be a single point of total failure (iter74)
The Webshare residential proxy subscription lapsed (402 Payment Required on all
40 usernames). Because 6 call sites did
`if store.get("use_proxy"): creds = get_proxy_credentials()` with NO health
check and NO fallback, every tier of all 5 proxied Salla stores failed while the
Zid stores were fine — and the UI blamed "Tier 3 extracted 0 products".

RULES:
1. When a crawl/fetch path depends on a paid third party, probe it once, cache
   the verdict, and degrade (direct connection / reduced mode) instead of
   failing. Record the degradation on the job log so it is auditable.
2. "All tiers failed on exactly the stores that share ONE flag" is a
   dependency outage, not a scraping regression. Diff the failing set against
   config flags (here: PROXY_STORES) BEFORE touching extraction logic.
3. Ship an admin health endpoint for every external dependency; the client can
   then see "renew the subscription" instead of "crawler broken".
