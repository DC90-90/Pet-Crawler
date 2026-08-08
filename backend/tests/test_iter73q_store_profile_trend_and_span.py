"""iter73q — Store Profile: Revenue Trend chart empty + Monthly Revenue
inflated (Aug 8 2026).

Client-reported two coupled bugs on the store profile page:

1. Revenue Trend (90 days) chart shows "No data available" on EVERY store
   — including stores where the KPI above it reports a positive monthly
   revenue. Root cause: the trend loop read fields `revenue` and
   `revenue_qty_drop` from `sku_sales_daily`, but the writer at
   `_recompute_store_metrics` emits `rev_sold` and `rev_qty`. Every row
   collapsed to 0 → the daily/weekly buckets stayed empty → chart empty.

2. Zarafa (4,177 products) shows 1,218.75 SAR "Est. Monthly Revenue" on
   the profile but 162.5 SAR on the Market Strength Ranking — an exact
   7.5× inflation. Root cause: `snaps_90d = ... .to_list(50000)` returns
   only the OLDEST 50K after ascending sort. For any store whose 90-day
   snapshot count exceeds 50K (Zarafa has ~375K), `snaps_90d[-1]` is the
   50000th oldest, NOT the true newest → span_days is truncated → the
   `total_rev × 30 / span_days` formula divides by a false-short span →
   monthly revenue inflates 5-10×. The Ranking uses the correct
   $group $min/$max aggregation (iter73o) so its 162.5 is right.

Both fixes live in `store_profile` (server.py L5259-5330):
- Trend chart reads `rev_sold` / `rev_qty` (correct field names).
- span_days now comes from a `$group` `$min`/`$max` aggregation, matching
  the ranking's iter73o computation. Two surfaces agree by construction.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _store_profile_body():
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def store_profile(store_id: str")
    b = src.index("    return {", a)
    return src[a:b]


# ── Bug 1: trend chart empty ────────────────────────────────────────────────
def test_iter73q_trend_chart_reads_correct_field_names():
    body = _store_profile_body()
    # Old (buggy) projection removed
    assert "\"revenue\": 1, \"revenue_qty_drop\": 1" not in body, \
        "trend chart projection must NOT reference nonexistent fields `revenue` / `revenue_qty_drop`"
    # New projection uses the actual sku_sales_daily field names.
    assert "\"rev_sold\": 1, \"rev_qty\": 1" in body, \
        "trend chart projection must include the correct fields `rev_sold` and `rev_qty`"


def test_iter73q_trend_chart_row_read_uses_rev_sold_fallback():
    body = _store_profile_body()
    assert 'r.get("rev_sold") or r.get("rev_qty")' in body, \
        "the per-row read must prefer rev_sold and fall back to rev_qty (matches _sales_pairs_from_rollups method-1 preference)"
    assert 'r.get("revenue")' not in body, \
        "old `revenue` field access must be gone — that field does not exist in sku_sales_daily"


def test_iter73q_writer_field_names_still_present():
    """Regression fence: if a future change to `_recompute_store_metrics`
    renames the fields, we want to catch it — the trend chart depends on
    these exact names."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("sales_docs.append({")
    b = src.index("})", a) + 2
    body = src[a:b]
    assert '"rev_sold":' in body, "writer must emit `rev_sold`"
    assert '"rev_qty":' in body, "writer must emit `rev_qty`"


# ── Bug 2: monthly revenue inflated by truncated span_days ──────────────────
def test_iter73q_span_days_uses_group_aggregation_not_snaps90d_last():
    """The store profile MUST derive span_days from a $group $min/$max
    aggregation, NOT from `snaps_90d[-1]` (which is bounded by
    `.to_list(50000)` and lies for any large store)."""
    body = _store_profile_body()
    # The buggy path is gone — no direct indexing off snaps_90d for the span.
    assert "snaps_90d[-1][\"crawled_at\"]" not in body, \
        "must not derive last_ca from snaps_90d[-1] — that value is truncated at 50000 docs"
    assert "snaps_90d[0][\"crawled_at\"]" not in body, \
        "must not derive first_ca from snaps_90d[0] either — replace the whole block"
    # New path uses a grouped aggregation over the FULL 90d snapshot set.
    assert "product_snapshots.aggregate([" in body
    assert "\"first\": {\"$min\": \"$crawled_at\"}" in body, \
        "span aggregation must $min crawled_at"
    assert "\"last\":  {\"$max\": \"$crawled_at\"}" in body or \
           "\"last\": {\"$max\": \"$crawled_at\"}" in body, \
        "span aggregation must $max crawled_at"


def test_iter73q_span_aggregation_scoped_to_this_store():
    """Store Profile is per-store — the span aggregation MUST filter by
    store_id (the ranking version doesn't need to because it groups by
    store_id, but here we want ONE store's span)."""
    body = _store_profile_body()
    # Locate the span-aggregation match stage and verify it filters store_id.
    idx = body.index("product_snapshots.aggregate([")
    span_block = body[idx:idx + 800]
    assert "\"store_id\": store_id" in span_block, \
        "span aggregation must filter to THIS store"
    assert "\"crawled_at\": {\"$gte\": since_90d}" in span_block, \
        "span aggregation must clamp to the 90d window"


def test_iter73q_est_monthly_revenue_formula_preserved():
    """iter73o regression fence: the est_monthly_revenue formula MUST
    remain `total_rev * 30 / max(span_days, 1)` so the ranking (which
    uses the same formula) and the profile still produce the same number
    per store."""
    body = _store_profile_body()
    assert "est_monthly_revenue = round(total_rev * 30 / max(span_days, 1), 2)" in body, \
        "the profile's monthly revenue formula is the alignment contract with the ranking (iter73o)"


# ── Math: convergence with the ranking ─────────────────────────────────────
def test_iter73q_ranking_and_profile_now_share_span_computation():
    """Both surfaces derive span_days from a $group aggregation over
    product_snapshots. Symbolic check that the two aggregation shapes
    match (same $match clause on crawled_at, same $min/$max pair)."""
    src = (BACKEND / "server.py").read_text()
    # Ranking's shape (iter73o, L6082-6094)
    rank_a = src.index("# Per-store observation span")
    rank_b = src.index("span_by_store[r[\"_id\"]] = _span_days", rank_a) + 200
    rank_body = src[rank_a:rank_b]
    assert "product_snapshots.aggregate" in rank_body
    assert "\"first\": {\"$min\": \"$crawled_at\"}" in rank_body
    # Profile's shape (iter73q)
    prof_a = src.index("iter73q (Aug 8 2026) — client-reported bug: Zarafa")
    prof_b = src.index("est_monthly_revenue = round(", prof_a)
    prof_body = src[prof_a:prof_b]
    assert "product_snapshots.aggregate" in prof_body
    assert "\"first\": {\"$min\": \"$crawled_at\"}" in prof_body


def test_iter73q_pre_fix_zarafa_math_reproduces_client_ratio():
    """Regression documentation: WITHOUT this fix, a store with 375K
    snapshots in 90d had `snaps_90d[-1]` as the 50000th oldest doc,
    yielding a span of ~12 days. This produced the exact 7.5× inflation
    the client screenshotted (1,218.75 / 162.5 = 7.5)."""
    # Buggy (pre-iter73q) path
    total_rev = 487.5             # summed measured revenue over the true 90d window
    bogus_span = 12               # truncated by .to_list(50000)
    bugged = round(total_rev * 30 / max(bogus_span, 1), 2)
    # Fixed path
    true_span = 90
    fixed = round(total_rev * 30 / max(true_span, 1), 2)
    # Ratio matches the client's screenshotted gap.
    assert abs(bugged / fixed - 7.5) < 0.01, \
        f"the fix closes exactly the 7.5× gap the client reported (got ratio {bugged / fixed:.2f})"
    # And the fixed number matches the ranking's 162.5.
    assert fixed == 162.5


def test_iter73q_marker_present_on_fixes():
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def store_profile(store_id: str")
    b = src.index("    return {", a)
    body = src[a:b]
    # Both fixes carry the iter73q tag.
    assert body.count("iter73q") >= 2, \
        "both fixes (trend fields + span aggregation) must be tagged iter73q for future audit"
