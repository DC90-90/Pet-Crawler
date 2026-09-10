# Daleel — Production runbook (iter80 drop: Market Share + backfill)

Everything in this file is copy-pasteable. Replace `$PROD` with your production
host (no trailing slash) and `$TOKEN` with a super-admin bearer token:

```bash
PROD="https://<your-production-host>"
TOKEN=$(curl -s -X POST "$PROD/api/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"a.disi@taqueen.sa","password":"<password>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
echo "${TOKEN:0:12}…"   # non-empty means you are ready
```

Timing: the deploy is minutes; the **backfill is 1–3 hours** (six stores, crawled
one after another, two of them very large). Plan a window where nobody needs to
redeploy — a pod restart kills an in-flight crawl.

---

## 0 · What is in this drop

| Area | Change | Why it matters on production |
|---|---|---|
| Market Share | filters now recompute the KPIs; CSV gained a **Calculation method** and (brands/categories) **Unavailable reason** column; "Sellers" split into **Stores carrying** / **Sales data available**; methodology states the tracked-market sentence verbatim | the client's 12 rules |
| **Catalogue tag (P0 bug fix)** | a legacy import had written the placeholder `own-store-id` into `my_products.store_id`, so **2,231 of 2,303 products were invisible to the matcher** — every rematch reported "ok" while matching only 68 products. Boot now re-tags them (idempotent) and the matcher refuses to run on a partial catalogue | after deploy, a rematch covers the WHOLE catalogue for the first time — expect competitor counts and Market Share coverage to jump |
| Backfill runner | new `POST /api/admin/backfill` runs crawls in the BACKGROUND and then re-matches | `POST /stores/{id}/crawl` is synchronous; a large Salla store outlives the ingress timeout, the client disconnects and the crawl dies before persistence. That is why Zarafa has never landed |
| Data hygiene | `/api/crawler/ingest` now refuses `*.example.com`, so "Test Store" cannot reappear on the Stores page; 175 throwaway `ratelimit_reg_*` users and 2 orphan match rows deleted | clean dashboards |
| Security | the crawler bearer token is read from the environment instead of being hardcoded in `server.py` | ⚠️ **pre-deploy check below** |
| Test suite | 1,119 passing / 0 failing / 0 errors (was 1,043 / 36 / 36) | green gate |

---

## 0b · iter81 — the deploy that timed out, and what changed

The Sep 10 deploy failed with `deployment failed to become ready: timeout
waiting for the condition` (health check never ran). The FastAPI startup
handler was the readiness gate: it AWAITED the seeds, the store registry, the
catalogue re-tag and ~35 index ensures before uvicorn served anything, and any
exception in the first three exited the process. Both modes look identical to
Kubernetes.

Now: `startup()` only schedules a background boot task, every phase fails soft,
and a new bounded `_wait_for_mongo()` retries a cold Atlas connection for up to
60s instead of raising. The browser self-heal (~400MB download) and the
catalogue-wide cache warm-up are delayed out of the readiness window
(`PLAYWRIGHT_SELFHEAL_DELAY_SECS=60`, `CACHE_WARM_DELAY_SECS=30`).

**Read the boot state after any deploy — one call:**

```bash
curl -s "$PROD/api/health" | python3 -m json.tool
# boot.status: done            → the boot sequence finished (expected)
#              running         → still working; poll again in 10s
#              mongo_unreachable → Atlas never answered: check MONGO_URL/network
#              aborted         → boot.errors names the phase that failed
```

`boot.errors` is a list of `"<phase>: <ExceptionType>: <message>"`. The API is
up and serving in every one of those states, so the pod becomes ready either
way; if a phase failed, finish it by hand:
`POST /api/admin/ensure-snapshot-indexes` and `POST /api/admin/refresh-caches`.

Two new environment keys must reach production (both already in
`backend/.env`): **`SUPER_ADMIN_EMAIL`** and **`SUPER_ADMIN_PASSWORD`** — the
super-admin credentials moved out of `server.py`. If they are missing, the boot
log says `[RBAC] ... NOT seeded` and nobody has super-admin rights.

---

## 1 · Pre-deploy checks (2 minutes)

1. **`CRAWLER_TOKEN` must exist in the production backend environment.** It is
   already in `/app/backend/.env`; confirm the value is carried into production.
   If it is missing, the API still boots and only `/api/crawler/ingest` returns
   `500 CRAWLER_TOKEN not configured` (deliberate — a missing key must not take
   the whole API down).
2. Confirm nobody is mid-crawl: `curl -s "$PROD/api/scheduler/status" -H "Authorization: Bearer $TOKEN"`.
3. Note the current numbers so you can compare afterwards:
   ```bash
   curl -s "$PROD/api/my-products?days=90&limit=1" -H "Authorization: Bearer $TOKEN" \
     | python3 -c "import sys,json;print(json.load(sys.stdin)['kpis'])"
   curl -s "$PROD/api/admin/coverage-report" -H "Authorization: Bearer $TOKEN" \
     | python3 -c "import sys,json;[print(s['name'], s['products_crawled'], s['matched_products']) for s in json.load(sys.stdin)['stores']]"
   ```

## 2 · Deploy, then confirm it took

```bash
curl -s "$PROD/api/health"
# expect: status healthy · mongodb connected · scheduler_active_jobs 15 · playwright_available true
```

Then confirm the three things this drop changes:

```bash
# a) the catalogue re-tag ran (this is the P0 fix)
curl -s "$PROD/api/admin/coverage-report" -H "Authorization: Bearer $TOKEN" >/dev/null && echo "admin ok"
# b) Market Share answers and states the caveat
curl -s "$PROD/api/market-share/methodology?days=30" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['tracked_market'][:95])"
# expect it to START WITH: Market share is based on tracked measured data inside Daleel, not the total Saudi market
# c) the new backfill endpoint exists and is guarded
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$PROD/api/admin/backfill" -H "Content-Type: application/json" -d '{}'
# expect 401 (no token)
```

Server-side log lines worth grepping after the first boot:

```
[Catalogue] Re-tagged N my_products onto the real own-store id   ← the P0 fix, N should be ~2231 the first time
[Stores] Removed N reserved-domain (*.example.com) test store(s)
```

## 3 · Backfill — Zarafa, Petsy and the four Salla stores

**One call queues all six, sequentially, in the background.** `rematch: true`
runs the ADDITIVE matcher afterwards (never the purge).

```bash
curl -s -X POST "$PROD/api/admin/backfill" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"names":["Zarafa","Petsy","CutePets","Hamtaro","Caty","Lana Pets"],"rematch":true}'
# → {"ok":true,"run_id":"…","status":"started","stores":[…],"poll":"/api/admin/backfill/status"}
```

Poll every few minutes (safe to run as often as you like):

```bash
curl -s "$PROD/api/admin/backfill/status" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys,json
r=json.load(sys.stdin)['run']
print(r['status'])
for s in r['stores']:
    print(f\"  {s['name']:<12}{s['status']:<10}found={s.get('products_found')} snapshots={s.get('snapshots_created')} {s.get('duration_secs')}s {s.get('error') or ''}\")
print('rematch:', r.get('rematch') or r.get('rematch_error') or '(pending)')"
```

What good looks like per store: `status: done`, `products_found` in the
thousands, `snapshots_created` ≈ `products_found`, `error: null`. A `tier_used`
of 1 is the store's API; 2/3 are the HTML/DOM fallbacks.

**While it runs:** do not deploy, do not edit backend files, do not restart the
pod — a restart kills the crawl in flight and you must start the run again.
Zarafa and CutePets are the slow ones (uncapped barcode + DOM supplement);
persistence happens at the END of a store's crawl, so a store that is killed
half-way leaves nothing behind.

If a store comes back `failed` or `empty`, re-run the call for just that store:

```bash
curl -s -X POST "$PROD/api/admin/backfill" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"names":["Zarafa"],"rematch":true}'
```

## 4 · Rematch — the ORDER matters

The backfill call above already re-matches. Only run a standalone rematch if you
skipped it, and mind which one you use:

| Call | Behaviour | When |
|---|---|---|
| `POST /api/import/run-matching` | additive: rebuilds each product's matches from the stores currently inside the 14-day window | **safe, use this** |
| `POST /api/admin/rematch` (no `store_id`) | **DELETES every row in `product_matches` first**, then rebuilds | only when the whole fleet is fresh |

```bash
curl -s -X POST "$PROD/api/import/run-matching" -H "Authorization: Bearer $TOKEN"
# → {"message":"Matching started for 2303 products", ...}   ← the count MUST be your full catalogue
```

⚠️ **Never rematch before the backfill finishes.** The matcher only sees stores
crawled inside `matcher.MATCH_WINDOW_DAYS` (14). Rematching while Zarafa/CutePets
are stale deletes the rows it cannot rebuild, and competitor counts drop.

Verify the run actually covered the catalogue (this is the P0 fix in action):

```bash
curl -s "$PROD/api/data-freshness" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['sync_health'])"
# last_match_status: ok — and last_match_added should now be in the HUNDREDS, not 6
```

## 5 · Market Share verification (one command)

```bash
cd /app/backend
python3 tools_prod_verify_market_share.py --url "$PROD" \
  --email a.disi@taqueen.sa --password '<password>' \
  --days 30 --stores "Zarafa,Petsy" --json /tmp/prod_verify.json
# add --partial if the sealed window has no measurable sales yet
```

23 checks, exit code 0 = all green. It verifies, in the client's own terms:

| # | Rule |
|---|---|
| 1 | Market Share tab loads (all six endpoints + a product breakdown + the methodology sentence) |
| 2 | share only from measured data (no share without measured market revenue, none with zero measurable sellers, sole-seller products excluded from the headline) |
| 3 | estimates never feed a share (no row sourced from an estimate; methodology names the excluded Salla estimate) |
| 4 | every withheld number carries a reason (rows AND individual sellers) |
| 5 | Stores carrying ≠ Sales data available (both counters present, and rows where they differ) |
| 6 | Zarafa and Petsy appear as sellers where they carry the product |
| 7 | CSV has source label + confidence + unavailable reason + calculation method, for all four sections |
| 8 | a filter moves the KPIs, and the KPI equals the filtered table total |
| 9 | unauthenticated calls are refused (401) |
| 10 | fleet freshness + matcher coverage (the backfill acceptance test) |

**Expected before the backfill:** two FAILs — `Zarafa does not appear as a
seller` and `never crawled=['Zarafa'], older than the 14-day window=[Hamtaro,
Caty, Lana Pets, CutePets]`. Both must be gone afterwards.

Then five UI spot-checks at `$PROD/market-share` (super admin):

1. Overview loads with no console error; the tracked-market note names the window.
2. Toggle **Including today (partial)** — numbers appear where the sealed window withholds them.
3. Set the **Contested only** filter — the KPI count drops and the My Products table total matches it exactly.
4. Open any product row — every seller is listed, each with a source chip; a seller with no sales signal shows a reason, never 0.
5. Methodology tab — first line reads *"Market share is based on tracked measured data inside Daleel, not the total Saudi market."*

## 6 · Stores Carrying verification (product level)

```bash
# 1. a product Zarafa and Petsy both carry: every seller must be listed, even
#    when its sales are unavailable
SKU=$(curl -s "$PROD/api/market-share/my-products?days=30&limit=1&contested=true" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['rows'][0]['sku'])")
curl -s "$PROD/api/market-share/product/$SKU?days=30" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys,json
p=json.load(sys.stdin)['product']
print(p['name'], '| stores carrying:', p['sellers_total'], '| sales data available:', p['sellers_with_sales'])
for s in p['sellers']:
    print(f\"  {s['store_name']:<14}price={s['price']} units={s['units']} source={s['units_source']} reason={s.get('unavailable_reason')}\")"
```

Accept when: every store that carries the product is listed (mine included), the
two counters differ wherever a seller publishes no sales data, and each
unavailable seller shows a reason (`store_not_crawled_in_window`,
`fewer_than_two_crawls_in_window`, `no_sales_signal_published`).

```bash
# 2. per-store coverage: crawled > 0 must imply matched > 0 for every competitor
curl -s "$PROD/api/admin/coverage-report" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys,json
for s in json.load(sys.stdin)['stores']:
    if s.get('is_own_store'): continue
    flag='  <-- CHECK' if s['products_crawled']>100 and s['matched_products']==0 else ''
    print(f\"{s['name']:<14}crawled={s['products_crawled']:<6}matched={s['matched_products']:<5}barcodes={s['barcode_coverage_pct']}%{flag}\")"
```

## 7 · Rollback

Nothing in this drop migrates away from anything, so rollback is safe at any
point.

| Symptom | Action |
|---|---|
| Anything looks wrong after the deploy | Use the platform **rollback** to the previous checkpoint (free, instant). Do NOT git-revert. |
| A backfill crawl is hammering a store / you need it to stop | `curl -s -X POST "$PROD/api/scheduler/toggle-pause" -H "Authorization: Bearer $TOKEN"` pauses scheduled crawls, then rollback/restart the pod to kill the in-flight run. Snapshots already written are unaffected. |
| A crawl returned garbage for one store | `POST /api/admin/rematch {"store_id":"<id>"}` purges and rebuilds THAT store's matches only. |
| Competitor counts dropped after a rematch | A store fell outside the 14-day matcher window. Re-run the backfill for it; the counts come back with the snapshots. |
| The catalogue re-tag looks wrong | It only ever writes the real own-store id onto rows whose `store_id` was empty or the `own-store-id` placeholder; it never touches a correctly tagged row and is safe to re-run (every boot re-runs it). |
| Market Share shows everything as Unavailable | Expected when the window has fewer than two crawls per store. Toggle *Including today*, and check §6's coverage table. |

### The two things that will still be true after this deploy

* **Zid OAuth is not connected** — the partner app has not been approved, so own-store
  units come from stock depletion (a floor) and every affected number says
  `stock_depletion`. Connect it on Settings → Zid Orders once approved and those
  rows upgrade to `orders_exact` / **Actual** with no code change.
* **Resend email is mocked** — alerts render in-app only.
