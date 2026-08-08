"""iter73k — Market Strength Ranking own-store revenue fallback (Aug 3 2026).

Client asked to display their store's revenue on the Market Strength Ranking
"same as the other stores". Previously, when the Zid orders ledger was empty
(auth-blocked / not yet synced), the own-store row rendered "Accumulating"
instead of a SAR figure, while every competitor showed a measured number
from the `sku_sales_daily` rollup.

Fix: own-store revenue preference order is now
  1. Zid orders ledger (`_own_orders_aggregate`) — EXACT when available.
  2. `sku_sales_daily` rollup — SAME source competitors use. Populated from
     the own store's own snapshots (Zid Merchant API's cumulative sold-count
     diffed between crawls + qty depletion). Basis: "computed".
  3. None → "Accumulating" only when BOTH sources are empty.

iter70's honesty contract still holds: the own store never receives an
estimate (±50% category-velocity projection). Only measured figures leak in.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _ranking_source():
    return (BACKEND / "server.py").read_text()


def _own_revenue_block():
    """Return just the own-store revenue branch inside `_store_ranking_compute`.

    iter73s (Aug 2026) introduced a Salla-suppression branch inside the
    competitor `else:` arm, so the historic anchor
    `else:\\n            rev = round(revenue_by_store` no longer exists
    verbatim. The stable anchor is the `        else:` line that starts
    the competitor branch (matches both pre-iter73s and post-iter73s
    layouts)."""
    src = _ranking_source()
    a = src.index("# revenue column — value where measurable, explicit status where not")
    # Anchor: the exact `        else:` that closes the `if is_own:` branch.
    # (Indent is 8 spaces — inside `for sid in ...:` in `_store_ranking_compute`.)
    b = src.index("\n        else:\n", a)
    return src[a:b]


# ── code-shape fences ───────────────────────────────────────────────────────
def test_iter73k_marker_present():
    """The fix block is tagged so future readers know when the change happened."""
    body = _own_revenue_block()
    assert "iter73k" in body, "iter73k marker missing on the own-store branch"


def test_preference_order_ledger_first_then_rollup_then_accumulating():
    """The ordering is critical: ledger (exact) > rollup (measured) >
    accumulating (no data). Regression fence: if any branch reorders,
    an operator will see the fabricated revenue bug of iter62 re-appear."""
    body = _own_revenue_block()
    i_ledger = body.find('own_revenue is not None')
    i_rollup = body.find('_own_rollup > 0')
    i_none   = body.find('None, "accumulating"')
    assert 0 < i_ledger < i_rollup < i_none, \
        f"branch order broken (ledger→rollup→accumulating): {i_ledger}, {i_rollup}, {i_none}"


def test_ledger_branch_tag():
    """When the Zid orders ledger has data, basis must tag as `ledger`."""
    body = _own_revenue_block()
    assert 'revenue, rev_status = own_revenue, "ledger"' in body


def test_rollup_branch_tag_matches_competitors():
    """The rollup fallback tags basis as `computed` — the SAME tag every
    competitor gets from the same `_sales_pairs_from_rollups` source. This
    keeps the frontend's revenue_status renderer symmetric across own vs
    competitor rows (line 125 of PriceIntelHeader.jsx renders `revenue_30d`
    as an SAR value for ANY row where it's non-null)."""
    body = _own_revenue_block()
    assert 'revenue, rev_status = _own_rollup, "computed"' in body


def test_accumulating_only_when_both_sources_empty():
    """A row lands on `accumulating` ONLY when the ledger is empty AND the
    rollup summed to 0. Not before the rollup check."""
    body = _own_revenue_block()
    # the accumulating branch is the final `else`
    idx_else = body.rfind("else:")
    idx_accum = body.rfind('revenue, rev_status = None, "accumulating"')
    assert 0 < idx_else < idx_accum, "accumulating branch is not the final `else`"


def test_own_rollup_read_uses_revenue_by_store():
    """The fallback reads the SAME `revenue_by_store` dict competitors use.
    This is the one-line reason it's now measured, not estimated — and the
    reason it never fabricates: `revenue_by_store` is aggregated from
    `_sales_pairs_from_rollups` which reads only `sku_sales_daily` (own
    snapshot diffs, no category-velocity fill-in)."""
    body = _own_revenue_block()
    assert "revenue_by_store.get(sid, 0.0)" in body, \
        "own-store fallback must read from revenue_by_store (competitor source)"


def test_no_estimate_leak_in_own_branch():
    """Regression fence: an operator must not slip an estimate branch
    (`salla_estimate_with_band`, `revenue_est_salla`, `est_by_store`) into
    the own-store revenue resolution. iter70 explicitly forbids fabricated
    figures for the own store. Only real observations."""
    body = _own_revenue_block()
    for banned in ("est_by_store", "revenue_est_salla", "salla_estimate", "band_pct"):
        assert banned not in body, \
            f"forbidden estimator token '{banned}' leaked into own-store revenue"


def test_iter70_honesty_comment_still_present():
    """iter70's rationale is preserved in the surrounding code (not removed
    or watered down by the iter73k patch)."""
    src = _ranking_source()
    assert "the OWN store gets NO estimate, ever" in src, \
        "iter70 honesty comment removed — regression risk"


# ── behavioural sanity: helper isolation ────────────────────────────────────
def test_own_rollup_variable_scoped_locally():
    """`_own_rollup` is a local of the `is_own` branch — it must not shadow
    or contaminate the competitor branch's `rev` variable below."""
    body = _own_revenue_block()
    # `_own_rollup` should ONLY appear inside the `if is_own:` branch
    assert body.count("_own_rollup") >= 2, \
        "expected `_own_rollup` referenced in both compute + branch check"
    # and never used as the competitor `rev`
    assert 'rev = round(revenue_by_store.get(sid, 0.0), 2)' not in body, \
        "competitor rev leaked into own-store block (should be in else branch)"


# ── frontend contract: RevenueCell already handles revenue_30d != null ─────
def test_frontend_renders_computed_own_revenue_as_sar():
    """The Price Intel frontend renders `revenue_30d` as an SAR value on ANY
    row where it's non-null — regardless of `revenue_status`. So our
    backend fix (setting `revenue_30d = _own_rollup` on the own-store row)
    is picked up by the existing `RevenueCell` component with NO frontend
    change required. This test enforces the contract."""
    fe = (BACKEND.parent / "frontend" / "src" / "components" /
          "priceIntel" / "PriceIntelHeader.jsx").read_text()
    # locate the RevenueCell function
    a = fe.index("function RevenueCell")
    b = fe.index("function ", a + 1)
    body = fe[a:b]
    # Non-null revenue_30d is the FIRST branch in RevenueCell — an SAR value.
    # Regression fence: if a future edit demotes revenue_30d below other
    # branches, own-store rows might mis-render.
    i_check = body.find("row.revenue_30d != null")
    i_return = body.find("SAR", i_check)
    assert 0 < i_check < i_return, \
        "RevenueCell no longer renders revenue_30d as SAR when non-null — " \
        "iter73k own-store fallback will regress"
