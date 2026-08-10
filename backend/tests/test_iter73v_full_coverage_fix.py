"""iter73v — Complete Zarafa/Petsy coverage fix (Aug 8 2026).

Client mandate: "This cannot be marked resolved until iter73u is deployed,
full recrawl/backfill is completed, coverage report confirms full
Zarafa/Petsy coverage, regression tests pass, frontend evidence confirms
Zarafa/Petsy appear correctly."

This suite exercises the 9 scenarios in the client's regression brief +
the code-shape fences that make iter73u + iter73v stick:

  1. Zarafa variant-level SKU     — captured as primary + as barcode
  2. Petsy product match          — barcode intersect finds it
  3. SKU 052742024363             — end-to-end key family
  4. Leading-zero UPC-A           — canonical 14-digit key
  5. UPC-A → GTIN-14 matching     — 12-digit ↔ 14-digit join
  6. Arabic/English title diffs   — matcher tolerant
  7. Different weight variants    — variant arrays capture BOTH
  8. OOS products still appear    — `in_stock=False` not a filter for seller list
  9. Sales data unavailable       — store still surfaces as carrying

Plus fences:

  * Salla supplement caps removed (SALLA_DETAIL_SUPPLEMENT_CAP + DOM_CAP raised to 100000).
  * Synthetic S-* SKUs never appear as identity in `product_matches`.
  * Coverage report + admin recrawl / rematch endpoints exist and are
    super-admin-gated.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from crawlers import _normalize_raw_product, _collect_variant_field_list, \
    SALLA_DETAIL_SUPPLEMENT_CAP, SALLA_DOM_BARCODE_CAP  # noqa: E402
from matcher import _barcode_key_set  # noqa: E402
from utils import canonical_barcode  # noqa: E402


# ── Client requirement 1 & 3: Zarafa variant SKU end-to-end ────────────────
def test_zarafa_variant_sku_052742024363_end_to_end():
    """The exact SKU the client screenshotted. Zarafa's payload:
    root sku null, variant carries the EAN in `skus[].sku`. Must produce a
    matchable snapshot."""
    raw = {"id": 42, "name": "هيلز طعام جاف بالدجاج للقطط الصغيرة 3 كج",
           "skus": [{"sku": "052742024363", "barcode": "052742024363",
                     "price": {"amount": 265}}]}
    n = _normalize_raw_product(raw, "Zarafa")
    # Primary fields populated from variant
    assert n["sku"] == "052742024363"
    assert n["barcode"] == "052742024363"
    # Variant arrays include it
    assert "052742024363" in n["variant_skus"]
    assert "052742024363" in n["variant_barcodes"]


# ── Client requirement 2 & 4 & 5: Petsy/Hamtaro variants join to Zarafa ────
def test_multi_store_join_via_canonical_gtin14_key():
    """Zarafa (variant sku with leading zero) + Petsy (barcode at root
    with leading zero) + Hamtaro (root sku no leading zero) all
    canonicalise to the SAME GTIN-14 key. The matcher's Level-1
    intersect must find EACH of them regardless of which side stored
    the string with or without the leading zero."""
    zarafa = _normalize_raw_product(
        {"id": 1, "name": "X", "skus": [{"sku": "052742024363"}]}, "Zarafa")
    petsy = _normalize_raw_product(
        {"id": 2, "name": "X", "barcode": "052742024363"}, "Petsy")
    hamtaro = _normalize_raw_product(
        {"id": 3, "name": "X", "sku": "52742024363"}, "Hamtaro")

    # Client's own product's barcode key set.
    own = _barcode_key_set(barcodes=("052742024363",), skus=("052742024363",))
    for store_snap, label in ((zarafa, "Zarafa"), (petsy, "Petsy"),
                              (hamtaro, "Hamtaro")):
        keys = _barcode_key_set(
            barcodes=tuple([store_snap.get("barcode")]) + tuple(store_snap.get("variant_barcodes") or ()),
            skus=tuple([store_snap.get("sku")]) + tuple(store_snap.get("variant_skus") or ()))
        assert own & keys, f"{label} must intersect the client's key set"
        assert "00052742024363" in keys, \
            f"{label} must produce the GTIN-14 canonical key"


# ── Client requirement 6: Arabic / English titles ─────────────────────────
def test_matcher_barcode_step_ignores_title_language():
    """Level-1 barcode step is title-agnostic — an Arabic title on Zarafa
    and an English title on the client's own product must still match
    when the barcode/SKU keys intersect."""
    own = _barcode_key_set(barcodes=("052742024363",), skus=("052742024363",))
    zarafa_ar = _normalize_raw_product(
        {"id": 1, "name": "هيلز 3 كج", "skus": [{"sku": "052742024363"}]}, "Zarafa")
    petsy_en = _normalize_raw_product(
        {"id": 2, "name": "Hills Kittens 3KG", "sku": "052742024363"}, "Petsy")
    for store, name in ((zarafa_ar, "Zarafa"), (petsy_en, "Petsy")):
        keys = _barcode_key_set(
            barcodes=(store.get("barcode"),),
            skus=(store.get("sku"),))
        assert own & keys, f"{name}: barcode step must be title-agnostic"


# ── Client requirement 7: multiple weight variants captured ────────────────
def test_multiple_weight_variants_captured_on_parent_snapshot():
    """A product with 3KG / 7KG / 15KG variants, each with a distinct
    barcode, must land ALL barcodes on the parent's `variant_barcodes`
    array — the matcher can then intersect on ANY of the three."""
    raw = {"id": 99, "name": "Hills Kittens (multi-pack)",
           "skus": [
               {"sku": "052742024363", "barcode": "052742024363"},   # 3KG
               {"sku": "052742024370", "barcode": "052742024370"},   # 7KG
               {"sku": "052742024387", "barcode": "052742024387"},   # 15KG
           ]}
    n = _normalize_raw_product(raw, "Zarafa")
    assert set(n["variant_barcodes"]) >= {"052742024363", "052742024370", "052742024387"}
    assert set(n["variant_skus"])     >= {"052742024363", "052742024370", "052742024387"}


# ── Client requirement 8 & 9: OOS / no-sales-data still carries product ────
def test_seller_snapshots_does_not_filter_by_stock_state():
    """Code fence — `_seller_snapshots` must NOT gate on `in_stock` or
    `qty_available`. A competitor whose product went OOS 3 days ago
    still carries the product from a business standpoint (the shelf
    still exists). The `revenue_status` / `sales_data_unavailable`
    label lives elsewhere and never removes a store from the seller
    set."""
    body = (BACKEND / "server.py").read_text()
    a = body.index("async def _seller_snapshots(db, sku, product,")
    b = body.index("    return kept, set(sku_keys), len(excluded)", a)
    seller = body[a:b]
    # No `in_stock` / `qty_available` predicates in the query.
    lines = [ln for ln in seller.splitlines() if "query" in ln and ("in_stock" in ln or "qty_available" in ln)]
    assert not lines, \
        "_seller_snapshots must NOT filter competitors by stock state"


def test_sales_data_unavailable_does_not_remove_store_from_seller_list():
    """The two surfaces MUST be independent:
      * "This store carries product X" — driven by product_snapshots
        presence + `_seller_snapshots` direct-key fallback.
      * "This store's sales data is unavailable" — driven by
        `revenue_status` on the leaderboard / ranking / store profile.
    Confirm the seller endpoint doesn't accidentally cross the two."""
    body = (BACKEND / "server.py").read_text()
    a = body.index("async def _seller_snapshots(db, sku, product,")
    b = body.index("    return kept, set(sku_keys), len(excluded)", a)
    seller = body[a:b]
    assert "sales_data_unavailable" not in seller
    assert "insufficient_history" not in seller


# ── Salla supplement caps removed ──────────────────────────────────────────
def test_iter73v_salla_supplement_caps_removed():
    """Client mandate: high-catalog Salla stores must be crawled
    completely. Both caps are lifted to a very large sentinel (100K)
    that no real store's catalog can hit — effectively unlimited while
    keeping `min(cap, missing_total)` diagnostics readable."""
    assert SALLA_DETAIL_SUPPLEMENT_CAP >= 10000
    assert SALLA_DOM_BARCODE_CAP >= 10000


# ── Synthetic SKU fence ───────────────────────────────────────────────────
def test_iter73v_synthetic_skus_never_hit_product_matches():
    """Regression fence on the matcher: synthetic `S-<store>-<hash>`
    SKUs (the crawler's last-resort fallback when neither root nor
    variant produced a real SKU) must NEVER seed a `product_matches`
    row. They're internal-only identifiers."""
    src = (BACKEND / "matcher.py").read_text()
    a = src.index("if my_barcode_candidates:\n        for snap in comp_snapshots:")
    b = src.index("common_barcodes = my_barcode_candidates & comp_barcode_candidates", a)
    barcode_step = src[a:b]
    assert 'c_sku.startswith("S-")' in barcode_step, \
        "matcher must skip synthetic S-* SKUs in the barcode step"


def test_iter73v_synthetic_sku_prefix_stays_stable():
    """Regression: the crawler's synthetic-SKU prefix is `S-`. If a
    future change alters the prefix, the matcher fence and the coverage
    report's `synthetic_sku_rate_pct` must be updated in lockstep."""
    src = (BACKEND / "crawlers.py").read_text()
    # Fallback lives inside _normalize_raw_product's sku_raw computation.
    assert 'f"S-{store_name[:2].upper()}-{raw.get(' in src, \
        "the synthetic-SKU fallback prefix must stay `S-` — matcher fence depends on it"


# ── Coverage report + rematch admin endpoints exist ────────────────────────
def test_iter73v_admin_coverage_report_endpoint_defined():
    src = (BACKEND / "server.py").read_text()
    assert '@router.get("/admin/coverage-report")' in src
    assert "async def admin_coverage_report(" in src
    # Must be super-admin gated.
    admin_line_idx = src.index("async def admin_coverage_report(")
    signature = src[admin_line_idx:admin_line_idx + 200]
    assert "require_super_admin" in signature


def test_iter73v_admin_recrawl_and_rematch_endpoints_defined():
    src = (BACKEND / "server.py").read_text()
    assert '@router.post("/admin/recrawl-store/{store_id}")' in src
    assert "async def admin_recrawl_store(" in src
    assert '@router.post("/admin/rematch")' in src
    assert "async def admin_rematch(" in src
    # Recrawl uses `crawl_store_waterfall` (the real single-store crawler),
    # not a stub.
    idx = src.index("async def admin_recrawl_store(")
    body = src[idx:idx + 1000]
    assert "crawl_store_waterfall(db, store)" in body
    # Rematch supports store_id scope AND fleet-wide (None → all).
    idx = src.index("async def admin_rematch(")
    body = src[idx:idx + 1500]
    assert "payload.store_id" in body
    assert "run_matching_for_all(db)" in body


def test_iter73v_coverage_report_response_shape():
    """Response fields the operator needs to see (client's brief item 8)."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def admin_coverage_report(")
    b = src.index("@router.post(\"/admin/recrawl-store", a)
    body = src[a:b]
    for field in ('"products_crawled"', '"variants_captured"',
                  '"sku_coverage_pct"', '"barcode_coverage_pct"',
                  '"synthetic_sku_rate_pct"', '"matched_products"',
                  '"unmatched_products"', '"last_full_crawl"'):
        assert field in body, f"coverage report must expose `{field}` per the client's requirement"


# ── Variant array collection helper — corner cases ─────────────────────────
def test_collect_variant_field_list_dedupe_and_order():
    raw = {"skus": [{"sku": "A"}, {"sku": "B"}, {"sku": "A"}]}
    got = _collect_variant_field_list(raw, ("sku",), fallback="PRIMARY")
    # Fallback prepended, duplicates dropped, order preserved.
    assert got == ["PRIMARY", "A", "B"]


def test_collect_variant_field_list_numeric_only_filters_non_ean():
    raw = {"skus": [{"sku": "052742024363"}, {"sku": "HL-CAT-3KG"}]}
    got = _collect_variant_field_list(raw, ("sku",), fallback="",
                                       numeric_only=True)
    assert "052742024363" in got
    assert "HL-CAT-3KG" not in got


# ── Direct-key fallback (iter73u) still queries variant arrays ─────────────
def test_iter73v_direct_key_fallback_includes_variant_arrays():
    """`_seller_snapshots` MUST query the 4 direct-key clauses so a
    competitor snapshot whose primary sku is synthetic but whose
    `variant_barcodes` array contains the client's EAN is still
    surfaced."""
    import re as _re
    body = (BACKEND / "server.py").read_text()
    a = body.index("async def _seller_snapshots(db, sku, product,")
    b = body.index("    return kept, set(sku_keys), len(excluded)", a)
    seller = body[a:b]
    # All four clauses present (whitespace-flexible).
    for field in ("sku", "barcode", "variant_skus", "variant_barcodes"):
        assert _re.search(rf'\{{"{field}":\s*\{{"\$in":', seller), \
            f"seller_snapshots direct-key fallback must include the `{field}` clause"


# ── Canonical GTIN-14 family — regression on the primitive ──────────────────
def test_canonical_barcode_leading_zero_family():
    assert canonical_barcode("052742024363") == "00052742024363"
    assert canonical_barcode("52742024363")  == "00052742024363"


# ── Matcher's competitor lookup projects variant arrays ─────────────────────
def test_iter73v_matcher_pipeline_projects_variant_arrays():
    """The $group $first stage in `_build_competitor_lookups` MUST carry
    `variant_barcodes` and `variant_skus` through so the barcode step
    can intersect on any variant key."""
    src = (BACKEND / "matcher.py").read_text()
    a = src.index("$group\": {")
    b = src.index("]", a)
    group_stage = src[a:b]
    assert '"variant_barcodes": {"$first": "$variant_barcodes"}' in group_stage
    assert '"variant_skus": {"$first": "$variant_skus"}' in group_stage
