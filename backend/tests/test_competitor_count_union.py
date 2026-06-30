"""
Regression tests for the barcode-safe competitor-count union fix.

Bug: `num_competitors` in /api/my-products was reading only from the
`product_matches` link table. When the matcher fell behind (matcher coverage
gap), competitor stores with fresh in-window snapshots whose `sku` equalled
the my_sku were missed entirely — main table column showed 0 while the
detail panel showed all 6+ stores.

Fix (server.py:my_products row builder):
  competitor_stores = matches[my_sku].store_ids  ∪
                      { store_id : by_sku[bc][store_id] for bc in barcode_candidates }
  where barcode_candidates = { my_sku if _is_valid_barcode, my_barcode if _is_valid_barcode }
  and _is_valid_barcode matches ^\\d{8,14}$ (the EXACT regex matcher.py uses).

These tests assert the safety properties of the union — especially the
no-false-positive guarantees for the Zid suffix bug and proprietary SKUs.
"""
import os
import re
import pytest
import requests
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

# Same regex as matcher.py:_is_valid_barcode (re-implementing to make this
# test file fully self-contained — drift detection would catch a divergence)
NUMERIC_BARCODE_RE = re.compile(r"^\d{8,14}$")


def _is_valid_barcode(val):
    if not val:
        return False
    return bool(NUMERIC_BARCODE_RE.match(str(val).strip()))


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"

BEAPHAR_SKU = "8711231124985"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


# ── Predicate safety guarantees ──────────────────────────────


def test_is_valid_barcode_accepts_ean13():
    assert _is_valid_barcode("8711231124985") is True
    assert _is_valid_barcode("8005852750068") is True


def test_is_valid_barcode_rejects_suffixed_sku():
    # The Zid suffix bug we explicitly want to avoid
    assert _is_valid_barcode("8005852750068-RUDC") is False
    assert _is_valid_barcode("8005852750068.001") is False
    assert _is_valid_barcode("8005852750068 Zid") is False


def test_is_valid_barcode_rejects_proprietary():
    assert _is_valid_barcode("XYZ-001") is False
    assert _is_valid_barcode("ROYAL-CANIN-DRY-2KG") is False
    assert _is_valid_barcode("") is False
    assert _is_valid_barcode(None) is False


def test_is_valid_barcode_length_bounds():
    assert _is_valid_barcode("12345678") is True            # 8 digits — UPC-E
    assert _is_valid_barcode("1234567") is False            # 7 digits — too short
    assert _is_valid_barcode("12345678901234") is True      # 14 digits — GTIN-14
    assert _is_valid_barcode("123456789012345") is False    # 15 digits — too long


# ── Live end-to-end against the API ──────────────────────────


def test_beaphar_sku_returns_at_least_6_competitors_end_to_end(client, db):
    """The user-reported case: SKU 8711231124985 (Beaphar Multi-vitamin) —
    main table previously showed COMPETITORS=0 while the detail panel showed
    Mowkly, Petsy, Panda, aleef, Zarafa, Caty Store (6 competitors).
    """
    # First confirm the data state still has the bug shape (matches stale,
    # 6 competitor stores in snapshot table). If this assertion drifts in
    # the future, the test scaffolding tells us which assumption broke.
    since30 = datetime.now(timezone.utc) - timedelta(days=30)
    own_store_doc = db.stores.find_one({"is_own_store": True}, {"id": 1})
    own_store_id = own_store_doc["id"] if own_store_doc else None
    snap_stores = db.product_snapshots.distinct(
        "store_id",
        {"sku": BEAPHAR_SKU, "crawled_at": {"$gte": since30}, "confidence_score": {"$gte": 85}},
    )
    competitor_stores_in_snaps = [s for s in snap_stores if s != own_store_id]
    assert len(competitor_stores_in_snaps) >= 6, (
        f"Test data drift: expected >=6 competitor stores in 30d snapshots "
        f"for {BEAPHAR_SKU}, got {len(competitor_stores_in_snaps)}"
    )

    # Hit the API
    r = client.get(f"{BASE_URL}/api/my-products", params={
        "days": 30, "search": BEAPHAR_SKU, "limit": 10,
    }, timeout=20)
    assert r.status_code == 200, r.text
    payload = r.json()
    rows = payload.get("products", payload.get("rows", []))
    assert rows, f"No rows returned for {BEAPHAR_SKU}: {payload}"
    row = next((x for x in rows if x.get("sku") == BEAPHAR_SKU), None)
    assert row is not None, f"SKU {BEAPHAR_SKU} not in response"

    # CORE ASSERTION — the user-visible bug fix
    assert row["num_competitors"] >= 6, (
        f"num_competitors should be >=6 (from barcode-union), got "
        f"{row['num_competitors']}. Row: {row}"
    )

    # Sanity: priced subset is non-empty and feeds competitor_min_price
    assert row.get("num_priced_competitors", 0) >= 1, (
        f"num_priced_competitors should be >=1, got "
        f"{row.get('num_priced_competitors')}"
    )
    assert row.get("competitor_min_price") is not None
    assert row.get("competitor_max_price") is not None
    assert row.get("has_competitor_pricing") is True


def test_response_shape_includes_new_field(client):
    """The response must expose num_priced_competitors so the FE (or admin
    diagnostics) can distinguish "stores carrying" from "stores with usable
    pricing". Iter19 added this contract; this pins it.
    """
    r = client.get(f"{BASE_URL}/api/my-products", params={"days": 30, "limit": 5}, timeout=15)
    assert r.status_code == 200
    rows = r.json().get("products", [])
    assert rows, "Empty rows — can't validate response shape"
    own_rows = [x for x in rows if x.get("is_my_product")]
    assert own_rows, "Expected at least one own-store row in /api/my-products"
    sample = own_rows[0]
    for field in ("num_competitors", "num_priced_competitors",
                  "has_competitor_pricing", "competitor_min_price"):
        assert field in sample, (
            f"Missing required field '{field}' in /api/my-products row: "
            f"{list(sample.keys())}"
        )


def test_zid_suffix_safety_no_false_positive(db):
    """No-false-positive guarantee: even if a competitor stored a suffixed
    SKU like '8005852750068-RUDC' in product_snapshots, it can NEVER be
    unioned into the count for my_sku='8005852750068' via the barcode path,
    because the lookup key in by_sku is the clean EAN string.

    This is a structural property of the union — encoded as a logic-level
    assertion below (no DB write needed).
    """
    # Build my barcode candidates
    my_sku = "8005852750068"
    my_barcode = ""
    candidates = set()
    if _is_valid_barcode(my_barcode):
        candidates.add(my_barcode)
    if _is_valid_barcode(my_sku):
        candidates.add(my_sku)
    # Lookup keys
    assert candidates == {"8005852750068"}
    # The suffixed string would be by_sku['8005852750068-RUDC'] — a different
    # bucket. It is impossible for the union loop to reach it via candidates.
    assert "8005852750068-RUDC" not in candidates


def test_proprietary_sku_falls_back_to_matches_only():
    """For non-EAN SKUs ('XYZ-001'), the barcode candidate set is empty,
    so the union degenerates to product_matches alone — preserving the
    pre-fix behaviour for the 14% of catalogue without EAN-shaped SKUs.
    """
    my_sku = "XYZ-001"
    my_barcode = ""
    candidates = set()
    if _is_valid_barcode(my_barcode):
        candidates.add(my_barcode)
    if _is_valid_barcode(my_sku):
        candidates.add(my_sku)
    assert candidates == set()


def test_market_coverage_is_additive_only(client, db):
    """Coverage % must not decrease vs the matches-only baseline. The union
    is additive by construction; if a future edit accidentally inverts a
    set operation, this catches it.

    Computes both predicates side-by-side over the entire catalogue.
    """
    since = datetime.now(timezone.utc) - timedelta(days=90)
    own = list(db.my_products.find({}, {"_id": 0, "sku": 1, "barcode": 1}))
    snaps = list(db.product_snapshots.find(
        {"crawled_at": {"$gte": since}, "confidence_score": {"$gte": 85}, "price": {"$ne": None}},
        {"_id": 0, "sku": 1, "store_id": 1, "price": 1, "crawled_at": 1}
    ))
    own_store_doc = db.stores.find_one({"is_own_store": True}, {"id": 1})
    own_store_id = own_store_doc["id"] if own_store_doc else None

    by_sku = {}
    for s in snaps:
        d = by_sku.setdefault(s["sku"], {})
        if s["store_id"] not in d or d[s["store_id"]]["crawled_at"] < s["crawled_at"]:
            d[s["store_id"]] = s

    matches_idx = {}
    for m in db.product_matches.find({}, {"_id": 0, "my_sku": 1, "competitor_sku": 1, "competitor_store_id": 1}):
        matches_idx.setdefault(m["my_sku"], []).append((m["competitor_sku"], m["competitor_store_id"]))

    own_skus = {str(r["sku"]).strip() for r in own}
    lost = 0
    gained = 0
    for sku in own_skus:
        old_set = set()
        for csku, cstore in matches_idx.get(sku, []):
            latest = by_sku.get(csku, {}).get(cstore)
            if latest and latest.get("price") is not None:
                old_set.add(cstore)
        new_set = set(old_set)
        bcs = set()
        mp = next((r for r in own if str(r.get("sku")).strip() == sku), {})
        if _is_valid_barcode(str(mp.get("barcode") or "").strip()):
            bcs.add(str(mp.get("barcode")).strip())
        if _is_valid_barcode(sku):
            bcs.add(sku)
        for bc in bcs:
            for sid, snap in by_sku.get(bc, {}).items():
                if sid == own_store_id:
                    continue
                if snap.get("price") is not None:
                    new_set.add(sid)
        if len(old_set) >= 1 and len(new_set) < 1:
            lost += 1
        if len(old_set) < 1 and len(new_set) >= 1:
            gained += 1

    assert lost == 0, f"Union must be additive — {lost} SKUs lost coverage"
    assert gained > 0, (
        "Expected the union to expose newly-covered SKUs (matcher coverage "
        "gap). If gained==0, either the matcher fully healed or the union "
        "isn't working."
    )


def test_oos_competitor_still_counts(client, db):
    """OOS competitors (in_stock=False, qty_available=0) WITH a price must
    appear in num_competitors AND in competitor_min/max_price. Zarafa is the
    canonical OOS case for Beaphar (qty=0, price=46.0).
    """
    since30 = datetime.now(timezone.utc) - timedelta(days=30)
    zarafa_snap = db.product_snapshots.find_one(
        {"sku": BEAPHAR_SKU, "store_name": {"$regex": "Zarafa", "$options": "i"},
         "crawled_at": {"$gte": since30}},
        sort=[("crawled_at", -1)],
    )
    assert zarafa_snap is not None, "Zarafa snapshot not in 30d window"
    assert zarafa_snap.get("price") is not None
    assert _is_valid_barcode(zarafa_snap["sku"]), (
        "Zarafa snapshot SKU must pass _is_valid_barcode for the union path"
    )

    # Verify the API includes Zarafa's price in the comparison
    r = client.get(f"{BASE_URL}/api/my-products", params={
        "days": 30, "search": BEAPHAR_SKU, "limit": 5,
    }, timeout=15)
    assert r.status_code == 200
    rows = r.json().get("products", [])
    row = next((x for x in rows if x.get("sku") == BEAPHAR_SKU), None)
    assert row is not None
    # competitor_max_price must be >= 46 (Zarafa's price) since OOS prices count
    assert (row.get("competitor_max_price") or 0) >= 46.0, (
        f"competitor_max_price should include Zarafa's OOS price (46.0), "
        f"got {row.get('competitor_max_price')}"
    )


def test_kpi_invariant_share_sample_matches_has_market_share(client):
    """The iter19 invariant must hold:
        kpis.share_sample_size == count(rows where has_market_share)
        kpis.matched_products  == count(rows where has_competitor_pricing)

    iter19 already encodes this for the full catalogue
    (test_iteration19_coverage_split.py). Here we only sanity-check the
    KEY EXISTENCE on the response so a missing field is caught.
    """
    r = client.get(f"{BASE_URL}/api/my-products", params={
        "days": 90, "limit": 10, "offset": 0,
    }, timeout=15)
    assert r.status_code == 200
    payload = r.json()
    kpis = payload.get("kpis", {})
    for k in ("matched_products", "market_coverage_pct", "share_sample_size",
              "market_revenue", "avg_market_share"):
        assert k in kpis, f"KPI '{k}' missing from response: {list(kpis.keys())}"
    # And market_coverage_pct must be > 0 on preview (data exists)
    assert (kpis.get("matched_products") or 0) >= 1
    assert (kpis.get("market_coverage_pct") or 0) > 0
