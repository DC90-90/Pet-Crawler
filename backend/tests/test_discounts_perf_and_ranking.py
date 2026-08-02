"""iter73g — the "All Stores" filter must never silently return an empty
Discounts table, and `_discount_history` must never scan the whole snapshots
collection just because we didn't pass a store filter.

Client reported on production (Aug 2 2026):
  1. Discount tab took 8+ seconds to load with the default "All Stores".
  2. With "All Stores" the top-pct / top-amount tables read "No data
     available", yet filtering to a specific store (e.g. Zarafa, Hamtaro)
     revealed 30 rows immediately.

Both symptoms trace to the same class of defect: cross-cutting queries that
don't constrain by store. `_discount_history` fetched ALL snapshots for
each SKU across ALL stores × 90 days (slow); the top-pct/amount pipeline
sorted by STORED `discount_pct` (missing the arithmetic-only rows) and let
iter73e's try/except silently swallow the resulting timeout on production.

These tests are pure code-shape assertions — they don't need live data or a
network — so they run in every environment.
"""
from pathlib import Path
import re

BACKEND = Path(__file__).resolve().parents[1]
SERVER = (BACKEND / "server.py").read_text()


# ── Bug A: `_discount_history` must not scan by sku alone ─────────────────
def test_discount_history_filters_by_pair_not_just_sku():
    """The pair filter is what turns an 8+ second All-Stores scan into a
    sub-second one. Guard against a future "simpler" refactor accidentally
    reverting to `{"sku": {"$in": [...]}}` alone."""
    m = re.search(
        r"async def _discount_history\([^)]*\):(?P<body>.+?)^async def ",
        SERVER, re.DOTALL | re.MULTILINE)
    assert m, "_discount_history not found"
    body = m.group("body")
    # The `sku ∈ {...}` alone pattern is the anti-pattern we removed.
    # It should NOT appear in the current body.
    assert '"sku": {"$in": sorted({k[0] for k in keys})}' not in body, \
        "_discount_history has reverted to a sku-only IN filter — this is the O(N) scan bug"
    # The intended pattern: an $or over (sku, store_id) pairs.
    assert '"$or": or_clause' in body, \
        "_discount_history must $or over (sku, store_id) pairs, not filter by sku alone"
    assert 'chunk = pairs_list[start:start + 200]' in body, \
        "_discount_history must chunk pairs (protects against very large $or filters)"


def test_discount_history_run_detection_accepts_arithmetic_proof():
    """The run-of-discount-snapshots detection used to check `discount_pct
    > 0` only, so legacy rows with `original_price > price` but stored
    pct=0 were treated as non-discount days — cutting the run short and
    reporting `days_on_discount = 0` for genuinely-on-sale products."""
    m = re.search(
        r"async def _discount_history\([^)]*\):(?P<body>.+?)^async def ",
        SERVER, re.DOTALL | re.MULTILINE)
    body = m.group("body")
    # anti-pattern: stored-only check
    stored_only = re.search(r"^\s*if \(s\.get\(\"discount_pct\"\) or 0\) > 0:\s*$",
                            body, re.MULTILINE)
    assert not stored_only, \
        "_discount_history still treats a stored-0 row as a non-discount day"
    # intended pattern: stored OR arithmetic
    assert "stored_pct > 0 or (op > 0 and pp > 0 and op > pp)" in body, \
        "run detection must accept both stored AND arithmetic proof of a discount"


# ── Bug B: top-pct / top-amount rank by the EFFECTIVE discount ────────────
def test_top_pct_pipeline_ranks_by_effective_discount():
    """A row that is genuinely on sale but carries a stored `discount_pct=0`
    (arithmetic-only) MUST make it through the $limit. That's only possible
    if the sort is on the row-level effective discount, not the stored one."""
    m = re.search(
        r'@router\.get\("/discounts/top-pct"\)(?P<body>.+?)@router\.',
        SERVER, re.DOTALL)
    assert m, "/discounts/top-pct not found"
    body = m.group("body")
    # anti-pattern: sort by stored discount_pct after the group
    assert '{"$sort": {"discount_pct": -1}}' not in body, \
        "top-pct still sorts by stored discount_pct — arithmetic-only rows drop out"
    # intended: an $addFields _eff_pct then $sort on _eff_pct
    assert '"_eff_pct"' in body, "top-pct must materialise the effective pct as _eff_pct"
    assert '{"$sort": {"_eff_pct": -1}}' in body, \
        "top-pct must rank on _eff_pct, not on the raw stored discount_pct"


def test_top_amount_pipeline_ranks_by_effective_saving():
    """Same class of defect: top-amount used to sort by stored discount_pct
    then re-rank in Python. It must materialise the SAR saving inside the
    pipeline and use that for the pre-limit sort so arithmetic-only rows
    survive to enrichment."""
    m = re.search(
        r'@router\.get\("/discounts/top-amount"\)(?P<body>.+?)@router\.',
        SERVER, re.DOTALL)
    assert m
    body = m.group("body")
    assert '{"$sort": {"discount_pct": -1}}' not in body, \
        "top-amount still sorts by stored discount_pct pre-limit"
    assert '"_saving"' in body and '"$subtract"' in body, \
        "top-amount must materialise the SAR saving via $subtract inside the pipeline"
    assert '{"$sort": {"_saving": -1}}' in body


def test_pipelines_add_effective_field_after_the_group_not_before():
    """`$addFields` must run AFTER `_latest_per_pair_stage`, not before —
    otherwise the group's `$first` picks the newest doc but the effective
    field would be attached to a document that then gets dropped."""
    for endpoint in ("top-pct", "top-amount"):
        m = re.search(
            r'@router\.get\("/discounts/' + endpoint + r'"\)(?P<body>.+?)@router\.',
            SERVER, re.DOTALL)
        body = m.group("body")
        # crude ordering check: the pipeline literal contains the stages in order
        i_group = body.find("_latest_per_pair_stage()")
        i_addf  = body.find("$addFields")
        assert 0 <= i_group < i_addf, \
            f"{endpoint}: $addFields must come AFTER _latest_per_pair_stage()"
        i_sort  = body.find("$sort", i_addf + 1)
        i_limit = body.find("$limit", i_sort + 1)
        assert 0 <= i_addf < i_sort < i_limit, \
            f"{endpoint}: order must be $addFields → $sort → $limit"


# ── Regression: iter73e try/except still there ───────────────────────────
def test_top_pct_and_top_amount_still_have_try_except():
    """iter73e added defensive try/except. If a future refactor drops it,
    a single bad-typed row on production takes the whole tab down. Guard."""
    for endpoint in ("top-pct", "top-amount"):
        m = re.search(
            r'@router\.get\("/discounts/' + endpoint + r'"\)(?P<body>.+?)@router\.',
            SERVER, re.DOTALL)
        body = m.group("body")
        assert re.search(r"try:\s*\n[^\n]*aggregate", body), \
            f"{endpoint} lost its try/except wrapper"
        assert "logger.exception" in body


# ── Cross-endpoint: All Stores must not degenerate ────────────────────────
def test_discount_match_still_accepts_no_store_filter():
    """When `store_id` is None the predicate must NOT add a store_id
    constraint at all — that's what the "All Stores" case relies on."""
    m = re.search(
        r"def _discount_match\([^)]*\):(?P<body>.+?)^def ",
        SERVER, re.DOTALL | re.MULTILINE)
    body = m.group("body")
    # positive: guard clause requires BOTH truthy AND != 'all'
    assert re.search(r'if store_id and store_id != "all":\s*\n\s*m\["store_id"\] = store_id',
                     body), "the None-store guard is missing"
