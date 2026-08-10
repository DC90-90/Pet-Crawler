"""iter73u — Product matching / store coverage — cross-store barcode SKU
extraction (Aug 8 2026).

Client-reported: Zarafa's product "Hill's Science Plan Cat Dry Food with
Chicken for Kittens / 3KG" (SKU 052742024363 on storefront) was invisible
on the product detail's "Stores Carrying" list — even though the SKU is
literally the same string as the client's own product's SKU. Petsy same
symptom. Hamtaro matched because its raw payload put the EAN in the
top-level `sku` field.

Trace revealed 4 coupled bugs:

  A. `_normalize_raw_product` (crawlers.py) reads ONLY root `sku`/`mpn`.
     Salla merchants who put the EAN into `skus[].sku` (variant) left
     root null → we assigned synthetic `S-<store>-<id>`. Snapshot's
     `sku` field was garbage → no product_matches row created.

  B. Barcode variant-scan only checked `skus[].barcode/gtin/mpn` — not
     `skus[].sku`. When the merchant stored the EAN as SKU on the
     variant, our `barcode` field stayed empty → matcher's Level-1
     barcode step had nothing to intersect on.

  C. `_seller_snapshots` (server.py) required a `product_matches` row.
     Even if a competitor snapshot literally had the same barcode/SKU
     as the client's product, no match row = invisible on Stores
     Carrying.

  D. Salla barcode supplement is capped at 400/crawl (300 detail + 100
     DOM). For Zarafa (4177 products), 3777 products every crawl get no
     supplement pass. Coverage-scaling gap, deliberately left for a
     separate iteration (raising caps is bandwidth-sensitive).

This iteration fixes A, B, C.
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from crawlers import _normalize_raw_product, _salla_raw_barcode  # noqa: E402
from matcher import _barcode_key_set  # noqa: E402


# ── Bug A: variant-level SKU fallback ───────────────────────────────────────
def test_iter73u_root_sku_still_wins_when_present():
    """Regression fence: the existing root-sku path must not change for the
    huge population of products that already work today."""
    raw = {"id": 1, "name": "X", "sku": "ROOT-123", "skus": [{"sku": "VAR-456"}]}
    n = _normalize_raw_product(raw, "TestStore")
    assert n["sku"] == "ROOT-123"


def test_iter73u_variant_sku_used_when_root_absent():
    """The fix: root-null → we now reach into `skus[].sku` before falling
    to the synthetic fallback. Zarafa's Hills Kittens 3KG landed on
    exactly this branch."""
    raw = {"id": 1, "name": "Hills Kittens 3KG", "skus": [{"sku": "052742024363"}]}
    n = _normalize_raw_product(raw, "Zarafa")
    assert n["sku"] == "052742024363", \
        "variant-level SKU must be used when root sku is absent"
    assert not n["sku"].startswith("S-"), "should not have fallen to synthetic"


def test_iter73u_root_mpn_still_beats_variant_sku():
    """Order of precedence: `sku` > `mpn` > variant.sku > synthetic — the
    variant fallback is LAST-CHANCE before synthetic, not a hijack of an
    existing mpn."""
    raw = {"id": 1, "name": "X", "mpn": "MPN-42", "skus": [{"sku": "VAR-1"}]}
    n = _normalize_raw_product(raw, "T")
    assert n["sku"] == "MPN-42"


def test_iter73u_empty_variant_sku_still_falls_to_synthetic():
    raw = {"id": 1, "name": "X", "skus": [{"barcode": "052742024363", "sku": ""}]}
    n = _normalize_raw_product(raw, "T")
    # sku isn't recoverable but barcode still is (Bug B fix).
    assert n["sku"].startswith("S-")
    assert n["barcode"] == "052742024363"


def test_iter73u_first_nonempty_variant_sku_wins():
    """Multiple variants; the extractor takes the first non-empty
    `sku`."""
    raw = {"id": 1, "name": "X",
           "skus": [{"sku": ""}, {"sku": "052742024363"}, {"sku": "IGNORED"}]}
    n = _normalize_raw_product(raw, "T")
    assert n["sku"] == "052742024363"


# ── Bug B: variant `sku` recognised as a barcode candidate ─────────────────
def test_iter73u_variant_sku_is_barcode_when_numeric():
    """Zarafa's exact case: variant carries the EAN in the `sku` field
    (no separate `barcode`/`gtin`/`mpn`). Snapshot's `barcode` field MUST
    now be populated."""
    raw = {"id": 1, "name": "Hills Kittens 3KG",
           "skus": [{"sku": "052742024363", "price": {"amount": 265}}]}
    n = _normalize_raw_product(raw, "Zarafa")
    assert n["barcode"] == "052742024363", \
        "the numeric variant SKU must be captured as barcode too"


def test_iter73u_variant_barcode_still_preferred_when_present():
    """Regression fence: if the variant carries BOTH a real `barcode` field
    and a `sku`, the barcode field wins (matches pre-iter73u priority)."""
    raw = {"id": 1, "name": "X",
           "skus": [{"barcode": "1234567890123", "sku": "IGNORED"}]}
    n = _normalize_raw_product(raw, "T")
    assert n["barcode"] == "1234567890123"


def test_iter73u_non_numeric_variant_sku_not_a_barcode():
    """`_EAN_RE.match` gate prevents merchant SKUs like `HL-CAT-3KG` from
    being read as barcodes."""
    raw = {"id": 1, "name": "X", "skus": [{"sku": "HL-CAT-3KG"}]}
    n = _normalize_raw_product(raw, "T")
    assert n["barcode"] == ""
    # SKU still recovered as the primary SKU (Bug A path).
    assert n["sku"] == "HL-CAT-3KG"


def test_iter73u_root_sku_recognised_as_barcode_when_numeric():
    """Root-level SKU as barcode — Hamtaro's raw payload uses exactly this
    shape (`sku: "52742024363"` at root)."""
    raw = {"id": 1, "name": "X", "sku": "52742024363"}
    n = _normalize_raw_product(raw, "Hamtaro")
    assert n["sku"] == "52742024363"
    assert n["barcode"] == "52742024363"


def test_iter73u_supplement_skip_check_mirrors_normalizer():
    """`_salla_raw_barcode` gates the barcode supplement's skip decision.
    If it returned "" for a payload the normalizer now extracts, the
    supplement would waste API calls re-fetching a product we already
    have. Mirror the extended candidate list."""
    raw_variant = {"skus": [{"sku": "052742024363"}]}
    assert _salla_raw_barcode(raw_variant) == "052742024363"
    raw_root = {"sku": "052742024363"}
    assert _salla_raw_barcode(raw_root) == "052742024363"


# ── The end-to-end scenarios from the client's brief ────────────────────────
def test_iter73u_zarafa_style_payload_now_produces_matchable_snapshot():
    """The literal Zarafa / Hills Kittens 3KG case: root sku null, EAN
    inside `variants[].sku`. Before iter73u the snapshot had synthetic
    sku + empty barcode (unmatchable). After: both fields carry the EAN
    so ANY matcher lookup — barcode intersect, direct sku join, or
    canonical GTIN-14 key — will find it."""
    raw = {"id": 999, "name": "هيلز طعام جاف بالدجاج للقطط الصغيرة 3 كج",
           "skus": [{"sku": "052742024363", "price": {"amount": 265}}]}
    n = _normalize_raw_product(raw, "Zarafa")
    # sku is the EAN string.
    assert n["sku"] == "052742024363"
    # barcode too.
    assert n["barcode"] == "052742024363"
    # And the canonical GTIN-14 key set intersects with the client's own
    # product's key set (both are 052742024363).
    zarafa_keys = _barcode_key_set(barcodes=(n["barcode"],), skus=(n["sku"],))
    own_keys    = _barcode_key_set(barcodes=("052742024363",), skus=("052742024363",))
    common = zarafa_keys & own_keys
    assert common, "the fix must make the barcode key sets intersect on both scopes"
    assert "00052742024363" in common, \
        "GTIN-14 canonicalisation joins them — same EAN family"


def test_iter73u_leading_zero_and_stripped_sku_join_via_canonical_key():
    """Regression test the client explicitly requested: same product,
    different SKU normalisations across stores (Zarafa `052742024363`
    with leading zero, Hamtaro `52742024363` without)."""
    zarafa = _normalize_raw_product(
        {"id": 1, "name": "X", "skus": [{"sku": "052742024363"}]}, "Zarafa")
    hamtaro = _normalize_raw_product(
        {"id": 2, "name": "X", "sku": "52742024363"}, "Hamtaro")
    zk = _barcode_key_set(barcodes=(zarafa["barcode"],), skus=(zarafa["sku"],))
    hk = _barcode_key_set(barcodes=(hamtaro["barcode"],), skus=(hamtaro["sku"],))
    common = zk & hk
    assert "00052742024363" in common, \
        "leading-zero and stripped forms must resolve to the same GTIN-14 key"


def test_iter73u_seller_snapshots_direct_key_fallback_shape():
    """`_seller_snapshots` (server.py) MUST now emit a direct-key
    fallback clause even when no `product_matches` row exists.
    Code-shape regression — behavioural test is in the frontend/e2e
    suite once the crawler runs against seeded data."""
    body = (BACKEND / "server.py").read_text()
    a = body.index("async def _seller_snapshots(db, sku, product,")
    b = body.index("    return kept, set(sku_keys), len(excluded)", a)
    seller = body[a:b]
    # Import must exist so _barcode_key_set is resolvable at call time.
    assert "_barcode_key_set" in body[:body.index("async def _seller_snapshots")], \
        "_barcode_key_set must be importable from matcher for the fallback"
    # Guard: iter73u marker present in the seller function.
    assert "iter73u" in seller
    # New clauses computed from the client's own barcode + sku. The
    # exact whitespace between `"sku":` and `{"$in":` can drift (Python
    # formatters, iter73v alignment); accept either form.
    import re as _re
    assert "_barcode_key_set(" in seller
    assert _re.search(r'\{"sku":\s*\{"\$in":', seller)
    assert _re.search(r'\{"barcode":\s*\{"\$in":', seller)
    # Combined into the $or so pre-existing match-row lookups keep working.
    assert "_direct_key_clauses" in seller
    assert "list(clauses) + _direct_key_clauses" in seller


def test_iter73u_direct_key_fallback_is_defensive():
    """Exception in `_barcode_key_set` must NOT crash the endpoint — a
    misshapen `product` doc still returns via the pre-existing
    match-row query path."""
    body = (BACKEND / "server.py").read_text()
    a = body.index("async def _seller_snapshots(db, sku, product,")
    b = body.index("    return kept, set(sku_keys), len(excluded)", a)
    seller = body[a:b]
    assert "except Exception:" in seller and "direct-key fallback skipped" in seller


def test_iter73u_leading_zero_barcode_key_family_stable():
    """Regression on `canonical_barcode` behaviour that iter73u depends
    on: 12-digit UPC-A → 14-digit GTIN-14 with two leading zeros."""
    from utils import canonical_barcode
    assert canonical_barcode("052742024363") == "00052742024363"
    assert canonical_barcode("52742024363") == "00052742024363"
    # 13-digit EAN stays intact after one-zero pad.
    assert canonical_barcode("8595602540877") == "08595602540877"
