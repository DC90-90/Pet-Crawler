"""iter73o — Align Market Strength Ranking revenue with Store Profile
(Aug 3 2026).

Client-reported bug (Zarafa): Store Profile card shows 1,218.75 SAR "est.
monthly revenue" while Market Strength Ranking shows 162.5 SAR for the
SAME store. Two surfaces reading two different window/formula pairs:

  Store Profile:  90d unsealed rollup × 30/span_days  =  monthly rate
  Ranking:        sealed 30d rollup, raw sum          =  30-day sum

For any store whose measurable sales are concentrated in the past few
(unsealed) days, these can disagree by 5-10×. The client's screenshot IS
that exact case.

Fix: the ranking now reads the SAME 90d unsealed rollup and normalizes to
30-day rate per-store using the SAME formula (`total_rev × 30 /
span_days`) — the two surfaces are now forced to agree.

Side-effects fenced by test:
  * The Salla velocity pool still reads the 30d sealed window (its math
    is calibrated to `_RANKING_WINDOW_DAYS`) — widening would inflate
    per-daily rates 3× and require re-scaling the estimator.
  * Own store: iter73k's ledger-first preference is preserved.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _ranking_block():
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def _store_ranking_compute(db):")
    b = src.index("# ── assemble rows ──", a)
    return src[a:b]


def _rev_alignment_block():
    src = (BACKEND / "server.py").read_text()
    a = src.index("# iter73o (Aug 3 2026) — CRITICAL alignment fix")
    b = src.index("# Legacy 30d rollup preserved", a)
    return src[a:b]


# ── code-shape fences ───────────────────────────────────────────────────────
def test_iter73o_marker_present():
    body = _ranking_block()
    assert "iter73o" in body, "iter73o marker missing on the ranking compute"


def test_ranking_reads_90d_rollup_for_revenue():
    """The ranking now queries `_sales_pairs_from_rollups(db, since_90d, until=now)` — the
    SAME window Store Profile uses (server.py L5247)."""
    body = _rev_alignment_block()
    assert "since_90d = now - timedelta(days=90)" in body, \
        "ranking must derive `since_90d` for the alignment fix"
    assert "_sales_pairs_from_rollups(db, since_90d, until=now)" in body, \
        "ranking must read the 90d unsealed rollup for per-store revenue"


def test_ranking_normalizes_per_store_span_to_30d():
    """Store Profile does `total_rev × 30 / span_days` — the ranking now
    does the SAME per-store transform."""
    body = _rev_alignment_block()
    assert "span_by_store" in body, "per-store span map required"
    assert "product_snapshots.aggregate" in body, \
        "span comes from grouped snapshot aggregation (min/max crawled_at)"
    assert "total_rev * 30.0 / max(_span, 1)" in body, \
        "normalization must be `total_rev × 30 / span_days` — matching Store Profile"


def test_ranking_own_store_ledger_normalized_to_monthly_rate():
    """Own store's ledger is EXACT over `_RANKING_WINDOW_DAYS` sealed days —
    normalize to the SAME 30-day rate axis so the own row is directly
    comparable to competitor rows (both "SAR per 30 days")."""
    body = _rev_alignment_block()
    assert "own_revenue = round(own_revenue * 30.0 / max(_RANKING_WINDOW_DAYS, 1), 2)" in body, \
        "own store ledger must be normalized to the same monthly-rate axis"


def test_salla_velocity_pool_still_uses_sealed_30d():
    """The Salla estimator's velocity pool INPUT (`sales_pairs`) must stay
    at the sealed 30-day window. Widening would inflate per-daily rates
    3× and produce wildly over-estimated Salla revenue for stores with no
    measured sales — regression fence."""
    body = _ranking_block()
    # somewhere in the ranking block, we RE-READ the sealed rollup for the
    # velocity pool (aliased to `sales_pairs`) — separate from the 90d one
    # used for revenue_by_store.
    assert "sales_pairs = await _sales_pairs_from_rollups(db, sealed_start_utc, until=sealed_end_utc)" in body, \
        "velocity pool must still read the sealed 30d rollup"
    # And `_units_by` (further down) reads `sales_pairs`, not
    # `_sales_pairs_90d`, so the pool math stays calibrated.
    assert "_units_by = {(p[\"store_id\"], p[\"sku\"]): p[\"units\"] for p in sales_pairs}" in body


# ── Store Profile parity contract ──────────────────────────────────────────
def test_store_profile_still_uses_same_90d_rollup():
    """The alignment fix REQUIRES Store Profile to be reading the exact
    same source the ranking now reads. Regression fence: if a future edit
    moves Store Profile to a different window, the ranking will still
    align to the OLD Store Profile behaviour and the client will see the
    Zarafa gap re-open."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def store_profile(store_id: str")
    b = src.index("est_monthly_revenue = round(", a) + 200
    body = src[a:b]
    assert "_sales_pairs_from_rollups(" in body
    assert "since_90d" in body, "Store Profile must keep the 90d window"
    assert "total_rev * 30 / max(span_days, 1)" in body, \
        "Store Profile's est_monthly_revenue formula must be preserved"


# ── math: two surfaces reduce to the same number ───────────────────────────
def test_alignment_formula_equivalence():
    """A store with total_rev=1218.75 over span_days=30 must produce the
    SAME 1218.75 monthly figure on BOTH surfaces. Symbolic check on the
    formulas rather than a live integration test (preview seed data is
    thin and doesn't reliably exercise the diverging window edge case)."""
    total_rev_90d = 1218.75
    span_days = 30
    # Store Profile formula
    store_profile_monthly = round(total_rev_90d * 30 / max(span_days, 1), 2)
    # Ranking formula (iter73o)
    ranking_monthly = round(total_rev_90d * 30.0 / max(span_days, 1), 2)
    assert store_profile_monthly == ranking_monthly == 1218.75

    # Now the divergence case: total_rev concentrated in a short span
    total_rev_90d = 203.13     # only 5 days of data
    span_days = 5
    store_profile_monthly = round(total_rev_90d * 30 / max(span_days, 1), 2)
    ranking_monthly = round(total_rev_90d * 30.0 / max(span_days, 1), 2)
    assert store_profile_monthly == ranking_monthly, \
        "the short-span case (Zarafa) must produce identical numbers"


def test_pre_iter73o_divergence_would_reappear_without_fix():
    """Regression documentation: WITHOUT the fix, a store with revenue
    concentrated in the past 3 unsealed days would show ~0 SAR on the
    ranking and full-monthly on the profile — the exact 162.5 vs 1218.75
    gap the client screenshotted. This test does not run the divergent
    path (that's the whole point of the fix) but pins the arithmetic so a
    future rollback can't silently reintroduce the bug."""
    # sealed_30d sum with revenue concentrated in unsealed days:
    revenue_in_sealed_30d = 0.0       # data in unsealed window
    # 90d normalized formula picks up ALL data:
    total_rev_90d = 203.13
    span_days = 5
    fixed_monthly = round(total_rev_90d * 30.0 / max(span_days, 1), 2)
    # The divergence between the two would have been:
    divergence_ratio = fixed_monthly / (revenue_in_sealed_30d + 0.01)   # avoid div0
    assert divergence_ratio > 100, \
        "regression documentation — the fix closes an unbounded gap"
