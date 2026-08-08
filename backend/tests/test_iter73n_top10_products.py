"""iter73n — Store Profile "Top 10 Products" card now shows up to 10 rows
for EVERY store, not just those with dense sold-counter data (Aug 3 2026).

Client report (screenshot): production Store Profile card rendered "1 sold"
with only ONE product visible under "TOP 10 PRODUCTS". Same issue was
present across every store whose platform did not expose sold-counters —
Salla stores in particular. The card was silently short because the old
implementation ONLY iterated `sku_sales` (units-sold dict) and stopped when
the dict ran out.

Fix contract:
  * Rows with measured sales come first, sorted by units_sold desc, and
    carry `basis="measured"` + the real `units_sold` figure.
  * When the store has < 10 measured rows, fill the remaining slots with
    catalog rows sorted by (latest price × latest observable qty) —
    stable, non-fabricated ordering — carrying `basis="catalog"` and
    `units_sold=0`.
  * If `db.products` lookup fails on a measured SKU, fall back to the
    snapshot's store_name so the row is NOT silently dropped.
  * Frontend renders "in catalog" tag on catalog-fill rows so the two
    kinds are visually distinct.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _profile_block():
    src = (BACKEND / "server.py").read_text()
    a = src.index("# Top 10 products by sales")
    b = src.index("# Category distribution", a)
    return src[a:b]


# ── backend contract ────────────────────────────────────────────────────────
def test_iter73n_marker_present():
    body = _profile_block()
    assert "iter73n" in body, "iter73n marker missing on the top-10 block"


def test_top_products_iterates_all_measured_first():
    """The measured pass iterates over ALL sku_sales entries (sorted desc) —
    not just [:10]. It breaks internally when it reaches 10 rows, but the
    important invariant is: every measured SKU is a candidate, even if
    products.find_one fails for the FIRST few — the SUCCESSFUL ones still
    fill the top-10."""
    body = _profile_block()
    assert "_top_measured = sorted(sku_sales.items()" in body
    # No hard [:10] slice on _top_measured — that was the old bug
    assert "sorted(sku_sales.items(), key=lambda x: x[1], reverse=True)[:10]" not in body


def test_measured_rows_tagged_basis_measured():
    body = _profile_block()
    assert '"basis": "measured"' in body


def test_missing_product_row_falls_back_to_snapshot():
    """A measured SKU whose db.products doc is missing (rare race between
    snapshot write and products upsert) must NOT be silently dropped. The
    row uses the snapshot's store_name/sku as a fallback name."""
    body = _profile_block()
    assert "_fallback_snap" in body
    assert 'p = {"name_ar": ""' in body


def test_catalog_fill_when_fewer_than_10_measured():
    body = _profile_block()
    assert "if len(top_products) < 10:" in body
    assert "_catalog_score" in body
    # ranked by price × clipped qty (revenue-potential)
    assert "_catalog_score[sku] = _p * _q_clip" in body


def test_catalog_fill_skips_zero_price():
    """A product with no observed price cannot contribute to catalog
    ordering — it would just noise the tail. Fence guard."""
    body = _profile_block()
    assert "if _p <= 0:" in body
    assert "continue" in body.split("if _p <= 0:")[1][:100]


def test_catalog_qty_clipped_at_200():
    """iter34 reference: qty > 200 marks unlimited-stock and would dominate
    the score. Cap at 200 so a real stocked product doesn't disappear
    beneath a phantom infinite-stock row."""
    body = _profile_block()
    assert "min(_q, 200)" in body


def test_catalog_rows_tagged_basis_catalog_and_units_zero():
    body = _profile_block()
    # after the fill branch: rows must carry basis=catalog and units_sold=0
    fill_a = body.index("if len(top_products) < 10:")
    fill = body[fill_a:]
    assert '"basis": "catalog"' in fill
    assert '"units_sold": 0' in fill


def test_hard_cap_at_10_still_enforced():
    """Even with catalog fill, the card renders at MOST 10 rows."""
    body = _profile_block()
    assert body.count("len(top_products) >= 10:") >= 2, \
        "both measured + catalog loops must break at 10"


def test_seen_skus_prevents_duplicate_between_measured_and_catalog():
    """A SKU that lands in the measured list must NOT reappear in the
    catalog-fill list (duplicate rows on the same card would confuse
    ranking)."""
    body = _profile_block()
    assert "_seen_skus = set()" in body
    assert "_seen_skus.add(sku)" in body
    # catalog loop must guard against seen SKUs
    fill = body[body.index("if len(top_products) < 10:"):]
    assert "if sku in _seen_skus:" in fill


# ── frontend contract ───────────────────────────────────────────────────────
def test_frontend_renders_basis_tag():
    """`CompetitorProfilePage.jsx` renders catalog-fill rows with an "in
    catalog" tag so users can distinguish them from measured rows. Fence
    against silent regression to the old "N sold" for every row."""
    fe = (BACKEND.parent / "frontend" / "src" / "pages" / "CompetitorProfilePage.jsx").read_text()
    assert 'p.basis === "catalog"' in fe, \
        "frontend must branch on `basis === 'catalog'`"
    assert "in catalog" in fe, "frontend must render the 'in catalog' badge"


def test_frontend_falls_back_to_name_en_or_sku_when_name_ar_empty():
    """If a measured SKU came through with an empty name_ar (fallback shape
    from the missing-product-doc branch), the row must still render — via
    name_en or sku, not as an empty line."""
    fe = (BACKEND.parent / "frontend" / "src" / "pages" / "CompetitorProfilePage.jsx").read_text()
    assert "p.name_ar || p.name_en || p.sku" in fe


def test_frontend_hides_dash_when_brand_or_category_empty():
    """Catalog-fill rows for some Salla stores carry empty brand/category
    strings — rendering `{brand} · {category}` would show a bare " · ".
    Filter empty tokens; render "—" if both are empty."""
    fe = (BACKEND.parent / "frontend" / "src" / "pages" / "CompetitorProfilePage.jsx").read_text()
    assert '[p.brand, p.category].filter(Boolean).join(" · ")' in fe
