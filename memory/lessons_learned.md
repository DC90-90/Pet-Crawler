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
