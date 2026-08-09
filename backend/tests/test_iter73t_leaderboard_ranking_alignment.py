"""iter73t — Align Revenue Leaderboard with Market Strength Ranking (Aug 8 2026).

Client-reported: Hamtaro (Salla, 100% badge coverage) rendered 134,483
SAR "MEASURED ~" on the Market Strength Ranking but 2,951,442 SAR (~22×
bigger) on the Revenue Leaderboard chart for the same 30d window. Two
different code paths measuring the same phenomenon:

* Ranking used `salla_diff_series` + `salla_store_revenue_from_velocity`
  — excludes capped readings, skips resets, 5000-unit step cap.
* Leaderboard summed `_sales_pairs_from_rollups` (Tier 1,
  `sku_sales_daily`) — includes capped readings, per-interval 50-unit
  cap that fires on every bucket transition.

Fix: extract the Salla badge-diff logic into a shared helper
`_salla_badge_revenue_by_store(db, since)` and route BOTH surfaces
through it. Zid stores unaffected — their Merchant API sold_count is
authoritative and sku_sales_daily is the right source for them.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _src():
    return (BACKEND / "server.py").read_text()


def _leaderboard_body():
    src = _src()
    a = src.index("async def _insights_leaderboard_compute(db, days):")
    b = src.index("\nasync def _salla_badge_revenue_by_store", a)
    return src[a:b]


def _ranking_body():
    src = _src()
    a = src.index("async def _store_ranking_compute(db):")
    b = src.index("# ── iter62: rank on REVENUE", a)
    return src[a:b]


def _helper_body():
    src = _src()
    a = src.index("async def _salla_badge_revenue_by_store(db, since):")
    # The helper ends at the next top-level `async def` / `def` /
    # `@router` in the file.
    for marker in ("\nasync def ", "\ndef ", "\n@router"):
        try:
            b = src.index(marker, a + 10)
            return src[a:b]
        except ValueError:
            continue
    return src[a:]


# ── Shared helper exists and is used by BOTH surfaces ───────────────────────
def test_iter73t_shared_helper_defined():
    assert "async def _salla_badge_revenue_by_store(db, since):" in _src(), \
        "helper must be defined at module scope so both surfaces can import it"


def test_iter73t_ranking_calls_shared_helper():
    body = _ranking_body()
    assert "approx_by_store = await _salla_badge_revenue_by_store(db, since)" in body, \
        "ranking must delegate to the shared helper — no inline reimplementation"


def test_iter73t_leaderboard_calls_shared_helper():
    body = _leaderboard_body()
    assert "salla_approx = await _salla_badge_revenue_by_store(db, since)" in body, \
        "leaderboard must delegate to the same shared helper"


def test_iter73t_no_inline_diff_series_duplication_in_ranking():
    """The old inline block of `_sold_series` / `salla_diff_series` /
    `salla_store_revenue_from_velocity` in `_store_ranking_compute` must
    be GONE — living in exactly one place is the whole contract."""
    body = _ranking_body()
    # A single call to the helper — no rebuild of `_sold_series` here.
    assert body.count("_sold_series") == 0, \
        "ranking must not rebuild _sold_series inline — it lives in the helper"
    assert body.count("salla_diff_series(") == 0, \
        "ranking must not call salla_diff_series directly — only through the helper"


# ── Helper contract ─────────────────────────────────────────────────────────
def test_iter73t_helper_returns_per_store_dict():
    body = _helper_body()
    # Filters product_snapshots for the window with sold_count_cumulative
    # present — same shape as the pre-iter73t inline blocks.
    assert '"sold_count_cumulative": {"$exists": True}' in body
    # Runs salla_diff_series per (store, sku).
    assert "salla_diff_series(readings)" in body
    # Aggregates via salla_store_revenue_from_velocity.
    assert "salla_store_revenue_from_velocity(prods)" in body
    # Only emits stores whose aggregate is usable — a store with only
    # baseline-or-capped readings must NOT appear in the return dict.
    assert 'if agg["usable"]:' in body
    # Attaches per-sku rows so the leaderboard can recover units_sold.
    assert 'agg["_products"] = prods' in body


def test_iter73t_helper_is_best_effort():
    body = _helper_body()
    # Never crashes — any exception returns {} so both surfaces stay up.
    assert "except Exception:" in body
    assert "return {}" in body


# ── Leaderboard override contract ───────────────────────────────────────────
def test_iter73t_leaderboard_platform_lookup_present():
    body = _leaderboard_body()
    assert 'store_platform[s["id"]] = (s.get("platform") or "").lower()' in body, \
        "leaderboard must know each store's platform to decide when to override"


def test_iter73t_leaderboard_overrides_salla_rows_only():
    body = _leaderboard_body()
    # For Salla rows: replace Tier 1 with the helper's aggregate.
    assert 'if store_platform.get(sid) == "salla":' in body
    assert 'agg = salla_approx.get(sid)' in body
    assert 'if agg and agg.get("usable"):' in body
    # Zid rows are untouched — no explicit platform check outside the
    # Salla branch.
    assert 'if store_platform.get(sid) == "zid"' not in body, \
        "Zid rows must NOT be overridden — sku_sales_daily is authoritative for them"


def test_iter73t_leaderboard_salla_status_tagged_measured_approx():
    body = _leaderboard_body()
    assert 'revenue_status = "measured_approx"' in body, \
        "Salla rows with a usable badge diff must be tagged `measured_approx` (matches Ranking)"


def test_iter73t_leaderboard_salla_no_signal_blanks_tier1():
    """When the badge diff isn't usable, the leaderboard must blank the
    Tier 1 sum for Salla stores — showing a misleading noise figure is
    the whole bug we're fixing."""
    body = _leaderboard_body()
    a = body.index('if store_platform.get(sid) == "salla":')
    b = body.index("# Salla stores with no rollup entries either", a)
    branch = body[a:b]
    assert "sales_by_store[sid] = [0, 0.0]" in branch, \
        "unusable-badge Salla stores must have Tier 1 blanked — no noise number"


# ── Cross-surface equality by construction ─────────────────────────────────
def test_iter73t_both_surfaces_use_same_since():
    """Both surfaces pass `since = now - timedelta(days=days)` to the
    helper — no accidental window drift."""
    body = _leaderboard_body()
    assert "since = datetime.now(timezone.utc) - timedelta(days=days)" in body, \
        "leaderboard 'since' must be the days-parameterised window"
    body_r = _ranking_body()
    # Ranking uses a `since` variable computed upstream — verify it's the
    # one passed to the helper.
    assert "_salla_badge_revenue_by_store(db, since)" in body_r


def test_iter73t_no_regression_leaderboard_shape():
    """Response shape unchanged: same keys per row, same sort order.
    Frontends of both surfaces keep working without a schema migration."""
    body = _leaderboard_body()
    for k in ('"store"', '"store_id"', '"revenue_est"', '"units_sold"',
              '"products"', '"revenue_status"'):
        assert k in body, f"leaderboard row must still carry `{k}`"
    assert "leaderboard.sort(key=lambda x: (-x[\"revenue_est\"], -x[\"products\"]))" in body


# ── Math regression documentation ───────────────────────────────────────────
def test_iter73t_documents_the_22x_gap_the_fix_closes():
    """Regression comment: Hamtaro's 134,483 (Ranking Tier 2.5) vs
    2,951,442 (Leaderboard Tier 1) — 22× gap — is the exact ratio the
    fix closes."""
    body = _leaderboard_body()
    assert "134,483" in body and "2,951,442" in body, \
        "the iter73t block must document the exact client-reported numbers so a future auditor can trace the fix intent"
    assert "22×" in body or "22x" in body


def test_iter73t_marker_present_on_all_three_surfaces():
    src = _src()
    assert src.count("iter73t") >= 3, \
        "iter73t marker must appear on both surfaces + the shared helper"
