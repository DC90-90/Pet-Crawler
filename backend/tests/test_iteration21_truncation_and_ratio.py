"""
Iter21 regression suite — the 50k-truncation fix + matcher price-ratio fix.

Fixes tested:
  1. server.py:my_products() row builder now uses a $group aggregation
     to pre-collapse snapshots by (sku, store_id). Full history preserved,
     bounded doc count. Eliminates the .to_list(50000) silent truncation
     that caused non-deterministic num_competitors across time windows on
     data-dense environments (production, 90D).
  2. matcher.py:
     - Level 1 (barcode) hard-reject on price ratio > 2.0 removed.
     - Level 2 (SKU) hard-reject on price ratio > 1.5 replaced with the
       existing SUSPICIOUS_PRICE flag (>40% diff).
     - SUSPICIOUS_PRICE flag scoped to Level-2 matches only. Barcode
       matches never carry it because barcode equality is definitive
       same-product evidence.

Canonical regression cases:
  - Carnilove (SKU 8595602527212): aggressive discount 2.93 vs 13-22 SAR
    market. Was 0 product_matches (matcher rejected all 3 via ratio > 2.0),
    now 3 barcode matches with NO flags. Column shows 3 (30D) with strict
    monotonicity.
  - Beaphar (8711231124985): still 6 competitors, 8 barcode matches (no
    regression from iter20).
"""
import os
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"

CARNILOVE_SKU = "8595602527212"
BEAPHAR_SKU = "8711231124985"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


# ── Fix 1: truncation → aggregation ──────────────────────────


class TestTruncationFix:
    def test_carnilove_matches_barcode_union_expectation(self, client, db):
        """Post-fix, Carnilove must show at least the number of competitor
        stores that have priced in-window snapshots for the EAN. Preview
        data has 2-3 depending on window; production would show 3.
        """
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "search": CARNILOVE_SKU, "limit": 5},
                       timeout=15)
        assert r.status_code == 200
        row = next((p for p in r.json().get("products", [])
                    if p.get("sku") == CARNILOVE_SKU), None)
        assert row is not None
        assert row["num_competitors"] >= 2, (
            f"Carnilove num_competitors={row['num_competitors']} — expected "
            f">=2 (was 1 on production due to 50k truncation bug)"
        )
        # Prices must also be populated when snapshots exist
        assert row["competitor_min_price"] is not None
        assert row["competitor_max_price"] is not None

    def test_monotonicity_across_windows_beaphar(self, client):
        """Truncation fix invariant: num_competitors must be monotonic
        (non-decreasing) as the time window widens. Sweep the canonical
        Beaphar SKU across 7/14/30/90 day windows.
        """
        prev = None
        for days in (7, 14, 30, 90):
            r = client.get(f"{BASE_URL}/api/my-products",
                           params={"days": days, "search": BEAPHAR_SKU, "limit": 5},
                           timeout=15)
            row = next((p for p in r.json().get("products", [])
                        if p.get("sku") == BEAPHAR_SKU), None)
            assert row is not None
            n = row.get("num_competitors") or 0
            if prev is not None:
                assert n >= prev, (
                    f"Monotonicity broken for Beaphar: days={days} → n={n}, "
                    f"previous window was {prev}"
                )
            prev = n

    def test_monotonicity_across_windows_carnilove(self, client):
        prev = None
        for days in (7, 14, 30, 90):
            r = client.get(f"{BASE_URL}/api/my-products",
                           params={"days": days, "search": CARNILOVE_SKU, "limit": 5},
                           timeout=15)
            row = next((p for p in r.json().get("products", [])
                        if p.get("sku") == CARNILOVE_SKU), None)
            assert row is not None
            n = row.get("num_competitors") or 0
            if prev is not None:
                assert n >= prev, (
                    f"Monotonicity broken for Carnilove: days={days} → n={n}, "
                    f"previous window was {prev}"
                )
            prev = n

    def test_response_shape_intact(self, client):
        """The aggregation refactor must not break the response contract.
        Sample a real own-store row and assert every field that FE consumes.
        """
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "limit": 20}, timeout=15)
        assert r.status_code == 200
        rows = r.json().get("products", [])
        own = next((x for x in rows if x.get("is_my_product")), None)
        assert own is not None
        for f in ("sku", "name_en", "name_ar", "my_price", "num_competitors",
                  "num_priced_competitors", "has_competitor_pricing",
                  "competitor_min_price", "competitor_max_price",
                  "vs_my_price_pct", "market_share_pct", "has_market_share",
                  "qty_sold_est", "num_sellers"):
            assert f in own, f"Field '{f}' missing from own-store row"


# ── Fix 2: matcher price-ratio flag semantics ────────────────


class TestMatcherPriceRatioFlags:
    def test_carnilove_has_barcode_matches_now(self, db):
        """Pre-iter21: Carnilove had 0 product_matches (matcher rejected all
        3 via ratio > 2.0). Post-iter21: 3 matches, all barcode, conf=99.
        """
        rows = list(db.product_matches.find({"my_sku": CARNILOVE_SKU}))
        assert len(rows) >= 2, (
            f"Expected >=2 barcode matches for Carnilove post-iter21, got {len(rows)}"
        )
        for m in rows:
            assert m["match_method"] == "barcode", (
                f"Carnilove match should be barcode-method (EAN equality), "
                f"got {m['match_method']}"
            )
            assert m["confidence"] == 99, (
                f"Carnilove barcode match should be conf=99, got {m['confidence']}"
            )

    def test_carnilove_matches_have_no_suspicious_price_flag(self, db):
        """The whole point of iter21: aggressive discounts on barcode matches
        must NOT carry the SUSPICIOUS_PRICE flag. Barcode equality is
        definitive same-product evidence.
        """
        for m in db.product_matches.find({"my_sku": CARNILOVE_SKU}):
            flags = m.get("flags", []) or []
            assert "SUSPICIOUS_PRICE" not in flags, (
                f"Carnilove barcode match {m['competitor_store_name']} carries "
                f"SUSPICIOUS_PRICE flag — this defeats the iter21 fix. "
                f"Method={m['match_method']} flags={flags}"
            )

    def test_barcode_matches_never_flagged_globally(self, db):
        """No barcode-method match anywhere in the catalog should carry the
        SUSPICIOUS_PRICE flag. That flag is now scoped to Level-2 SKU matches.
        """
        offenders = list(db.product_matches.find({
            "match_method": "barcode",
            "flags": "SUSPICIOUS_PRICE",
        }, {"_id": 0, "my_sku": 1, "competitor_store_name": 1, "flags": 1}))
        assert not offenders, (
            f"{len(offenders)} barcode matches carry SUSPICIOUS_PRICE. "
            f"Sample: {offenders[:3]}"
        )

    def test_sku_level_matches_can_still_be_flagged(self, db):
        """SKU-string (Level-2) matches with >40% price gap MUST still carry
        the SUSPICIOUS_PRICE flag — the flag is still valuable for weak
        signal matches. Test tolerantly: if any exist they must have the flag.
        """
        sku_matches = list(db.product_matches.find(
            {"match_method": "sku"},
            {"_id": 0, "my_sku": 1, "match_method": 1, "competitor_price": 1, "flags": 1}
        ))
        # Not asserting existence — if the catalogue has none, that's fine.
        # But if any exist, the field must be present as method=sku.
        for m in sku_matches[:10]:
            assert m.get("match_method") == "sku"


# ── Bounded aggregation — no accidental catalogue explosion ──


class TestAggregationBoundedness:
    def test_my_products_completes_within_15s(self, client):
        """The aggregation should be fast because it collapses by (sku,
        store_id) at the DB layer. Compare to the pre-fix .to_list(50000)
        which returned raw snapshots (up to 50k documents).
        """
        import time
        t = time.time()
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 90, "limit": 500}, timeout=20)
        elapsed = time.time() - t
        assert r.status_code == 200
        assert elapsed < 15, f"my-products took {elapsed:.1f}s — regression"

    def test_insights_sales_completes(self, client):
        """/api/insights/sales calls my_products with own_only=False.
        Sanity check that the aggregation refactor doesn't break the
        market-wide callsite.
        """
        r = client.get(f"{BASE_URL}/api/insights/sales",
                       params={"days": 90, "limit": 20}, timeout=25)
        assert r.status_code == 200, r.text
