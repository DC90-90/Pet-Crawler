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
