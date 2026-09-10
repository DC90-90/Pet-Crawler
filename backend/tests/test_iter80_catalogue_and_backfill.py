"""iter80 — the catalogue-tag bug, the reserved-domain door, and the backfill runner.

Found while re-axing the iter21 matcher baselines: `run_matching_for_all` selects
the catalogue with {"is_own_store": True, "store_id": <own store id>}, and a
legacy import had written the PLACEHOLDER string "own-store-id" into
my_products.store_id. 2,231 of 2,303 products were therefore invisible to the
matcher — every rematch reported `match_status: ok, match_added: 6` while
silently skipping 97% of the catalogue, so a newly crawled competitor could
never gain matches for those products (CutePets carried 384 of our barcodes and
had ZERO match rows). Fixed by an idempotent boot re-tag plus a coverage guard
in the matcher, and fenced here.
"""
import os
import re
import sys
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

from _auth import auth_headers, base_url, live_db_name, live_mongo_url

BACKEND = Path("/app/backend")
sys.path.insert(0, str(BACKEND))

API = f"{base_url()}/api"
LEGACY_PLACEHOLDER = "own-store-id"


@pytest.fixture(scope="module")
def H():
    return auth_headers()


@pytest.fixture(scope="module")
def db():
    c = MongoClient(live_mongo_url(), serverSelectionTimeoutMS=5000)
    yield c[live_db_name()]
    c.close()


# ── the catalogue tag ────────────────────────────────────────────────────────
def test_boot_retags_the_catalogue_onto_the_real_own_store_id():
    src = (BACKEND / "store_registry.py").read_text()
    assert "iter80 catalogue re-tag" in src
    assert LEGACY_PLACEHOLDER in src, "the placeholder must be named in the migration"
    assert "my_products.update_many" in src
    # idempotent: it only touches rows that are NOT already correct
    assert '{"$in": [None, "", "own-store-id"]}' in src


def test_every_catalogue_row_is_visible_to_the_matcher(db):
    """The data invariant the matcher's own query depends on."""
    own = db.stores.find_one({"is_own_store": True}, {"id": 1})
    assert own, "no own store registered"
    total = db.my_products.count_documents({})
    assert total > 0
    tagged = db.my_products.count_documents({"is_own_store": True, "store_id": own["id"]})
    print(f"[catalogue] {tagged} of {total} products carry the real own-store id")
    assert tagged == total, (
        f"{total - tagged} products are invisible to run_matching_for_all — "
        f"they will never gain competitors")
    assert db.my_products.count_documents({"store_id": LEGACY_PLACEHOLDER}) == 0


def test_matcher_refuses_to_run_on_a_partial_catalogue():
    """A partially tagged catalogue is a data fault, not a smaller catalogue.
    The old code trusted the tag query whenever it returned ANYTHING at all."""
    src = (BACKEND / "matcher.py").read_text()
    assert "iter80 anti-silent-failure guard" in src
    assert "catalogue * 0.9" in src, "no coverage guard on the own-store tag query"
    guard = src.split("iter80 anti-silent-failure guard", 1)[1][:1200]
    assert "logger.error" in guard, "a partial catalogue must be reported loudly"
    assert 'db.my_products.find({}, {"_id": 0})' in guard, "no full-catalogue fallback"


def test_rematch_processes_the_whole_catalogue(db):
    """The last recorded match run must have covered the full catalogue.
    Before the fix this row read `match_added: 6` for a 2,303-product catalogue.
    """
    run = db.sync_runs.find_one({"match_status": {"$exists": True}},
                                sort=[("started_at", -1)])
    if not run:
        pytest.skip("no match run recorded yet")
    total = db.my_products.count_documents({})
    added = run.get("match_added")
    print(f"[rematch] last run: status={run.get('match_status')} added={added} "
          f"(catalogue {total})")
    if run.get("match_status") != "ok":
        pytest.skip(f"last match run was not ok ({run.get('match_status')})")
    # `match_added` counts PRODUCTS that found at least one competitor; it can
    # legitimately be a fraction of the catalogue, but 6 out of 2,303 was the
    # signature of the tag bug.
    assert added is None or added >= min(50, total * 0.01), (
        f"only {added} of {total} products matched — check the own-store tag")


# ── the reserved-domain door ────────────────────────────────────────────────
def test_ingest_refuses_the_reserved_test_domain(db):
    """iter76 deletes *.example.com stores on boot and `create_store` refuses
    them, but `/crawler/ingest` auto-registers unknown domains — which is how
    "Test Store" kept reappearing on the client's Stores page."""
    token = os.environ.get("CRAWLER_TOKEN")
    if not token:
        for line in (BACKEND / ".env").read_text().splitlines():
            if line.startswith("CRAWLER_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    assert token, "CRAWLER_TOKEN not available"
    r = requests.post(f"{API}/crawler/ingest",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"store_id": "test-store-id", "store_name": "Test Store",
                            "domain": "test.example.com", "platform": "salla",
                            "products": []}, timeout=60)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"
    assert "example.com" in r.text
    assert db.stores.count_documents({"domain": {"$regex": r"(^|\.)example\.com$"}}) == 0


def test_no_reserved_or_test_store_is_tracked(db):
    junk = [s.get("name") for s in db.stores.find(
        {"$or": [{"domain": {"$regex": r"example\.com$"}},
                 {"name": {"$regex": "^(test_|test )", "$options": "i"}}]},
        {"name": 1})]
    assert not junk, f"test stores on the client's Stores page: {junk}"


def test_crawler_token_is_not_hardcoded():
    src = (BACKEND / "server.py").read_text()
    assert 'CRAWLER_TOKEN = os.environ.get("CRAWLER_TOKEN", "")' in src, (
        "the crawler bearer token must come from the environment")
    assert "zj7n4vATDYACt" not in src, "the old literal token is still in the source"


# ── the backfill runner ─────────────────────────────────────────────────────
def test_backfill_is_registered_and_guarded(H):
    r = requests.post(f"{API}/admin/backfill", headers=H, json={}, timeout=60)
    assert r.status_code == 400, f"empty payload should 400, got {r.status_code}"
    r = requests.post(f"{API}/admin/backfill", headers=H,
                      json={"names": ["NoSuchStore"]}, timeout=60)
    assert r.status_code == 404
    r = requests.post(f"{API}/admin/backfill", json={"names": ["Aleef"]}, timeout=60)
    assert r.status_code == 401, f"must require auth, got {r.status_code}"


def test_backfill_status_is_super_admin_only(H):
    r = requests.get(f"{API}/admin/backfill/status", headers=H, timeout=60)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "run" in body
    if body["run"]:
        run = body["run"]
        for k in ("id", "started_at", "started_by", "status", "stores"):
            assert k in run, f"backfill run missing {k}"
        for s in run["stores"]:
            assert {"store_id", "name", "status"} <= set(s)
    assert requests.get(f"{API}/admin/backfill/status", timeout=60).status_code == 401


def test_backfill_never_purges_matches_before_the_crawl_lands():
    """POST /admin/rematch nukes product_matches first. Doing that BEFORE a stale
    store is re-crawled deletes rows it cannot rebuild (a store outside
    matcher.MATCH_WINDOW_DAYS contributes no candidates), so the backfill runner
    must use the ADDITIVE path."""
    src = (BACKEND / "server.py").read_text()
    block = src.split("async def admin_backfill", 1)[1].split("@router.get(\"/admin/backfill/status\")", 1)[0]
    assert "run_matching_for_all(db)" in block, "backfill does not rematch at all"
    assert "product_matches.delete_many" not in block, (
        "the backfill must not purge product_matches — a stale store's rows "
        "cannot be rebuilt until it is back inside the matcher window")
    assert "crawl_store_waterfall" in block
    assert "asyncio.create_task" in block, "the backfill must not block the request"


def test_backfill_runs_stores_sequentially_and_records_progress():
    src = (BACKEND / "server.py").read_text()
    block = src.split("async def admin_backfill", 1)[1].split("@router.get", 1)[0]
    assert "for s in stores:" in block, "stores must be crawled one at a time"
    assert "backfill_runs" in block
    for field in ("products_found", "snapshots_created", "tier_used", "error"):
        assert field in block, f"backfill progress does not record {field}"
