"""iter73w — Salla soft-block guard: refuse to persist snapshots when the
crawl produced far fewer products than the store's recent baseline.

Classic signature: Salla (fronted by Cloudflare/WAF) returns HTTP 200 with a
well-formed JSON envelope carrying an empty `data: []` (or a small subset)
under rate-limiting. Before this guard, the crawler treated the response as
success — snapshots for the 3-10 products still returned were written and
the OTHER hundreds of products silently "disappeared" from the store's
inventory in every downstream surface (Stores Carrying, Discounts, Revenue).

The guard compares current product count vs the median of the last N
successful crawls in the past 30 days. Baselines below SOFT_BLOCK_MIN_BASELINE
and stores with < SOFT_BLOCK_MIN_SAMPLES history are ALLOWED THROUGH — the
first crawl of a new store and small catalogs must never be punished.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_soft_block_guard")
import crawlers  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
STORE = {"id": "st-zarafa", "name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla"}


def _get_db():
    return AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]


async def _reset(db):
    await db.crawl_logs.delete_many({})
    await db.product_snapshots.delete_many({})


async def _seed_history(db, counts, store_id=STORE["id"]):
    """Insert a series of successful crawl_logs, oldest first. Each with the
    given products_found. Timestamps are staggered 1 day apart, newest last.
    """
    now = datetime.now(timezone.utc)
    docs = []
    for i, c in enumerate(counts):
        ts = (now - timedelta(days=len(counts) - i)).isoformat()
        docs.append({
            "id": f"log-{store_id}-{i}",
            "store_id": store_id,
            "store_name": STORE["name"],
            "tier_used": 1,
            "products_found": c,
            "snapshots_created": c,
            "completed_at": ts,
        })
    if docs:
        await db.crawl_logs.insert_many(docs)


def _make_log():
    return crawlers._make_crawl_log(STORE, tier_attempted=1)


# ── config sanity ───────────────────────────────────────────────────────────

def test_config_constants_are_sane():
    """Guard constants must produce a policy that neither punishes small
    stores nor lets a full-store wipe slip through."""
    assert crawlers.SOFT_BLOCK_MIN_BASELINE >= 20
    assert 0 < crawlers.SOFT_BLOCK_FLOOR_RATIO < 0.5
    assert crawlers.SOFT_BLOCK_LOOKBACK_DAYS >= 7
    assert crawlers.SOFT_BLOCK_SAMPLE_SIZE >= 3
    assert crawlers.SOFT_BLOCK_MIN_SAMPLES >= 3


def test_helpers_are_exported():
    assert callable(crawlers._detect_soft_block)
    assert callable(crawlers._apply_soft_block)


# ── detection semantics ─────────────────────────────────────────────────────

def test_insufficient_history_passes_through():
    """New store, only 2 successful crawls → never soft-blocked."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [400, 380])
        crawl_log = _make_log()
        blocked, reason = await crawlers._detect_soft_block(db, STORE, 5, crawl_log)
        assert blocked is False
        assert reason == ""
        assert crawl_log["soft_block"]["decision"] == "insufficient_history"
        assert crawl_log.get("soft_blocked") is not True
    asyncio.run(main())


def test_small_catalog_baseline_below_min_passes_through():
    """Store whose historical baseline is < SOFT_BLOCK_MIN_BASELINE (e.g., a
    genuinely small 30-product boutique) is never guarded — a real drop in
    such a store is indistinguishable from noise."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [30, 32, 31, 29, 30])
        crawl_log = _make_log()
        blocked, _ = await crawlers._detect_soft_block(db, STORE, 5, crawl_log)
        assert blocked is False
        assert crawl_log["soft_block"]["decision"] == "baseline_below_min"
    asyncio.run(main())


def test_normal_crawl_within_floor_passes_through():
    """Baseline 400, current 350 (87.5%) — well above the 20% floor, passes."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [420, 415, 400, 395, 405, 410, 400])
        crawl_log = _make_log()
        blocked, _ = await crawlers._detect_soft_block(db, STORE, 350, crawl_log)
        assert blocked is False
        assert crawl_log["soft_block"]["decision"] == "passed"
        assert crawl_log["soft_block"]["baseline_median"] == 405
        assert crawl_log["soft_block"]["floor"] == int(405 * 0.2)
    asyncio.run(main())


def test_soft_block_detected_when_current_below_floor():
    """Baseline 400, current 5 (1.25%) — WAY below the 20% floor. This is the
    classic Salla HTTP 200 + data:[] signature: crawl produced almost nothing
    but the store historically returns 400. Must block."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [420, 415, 400, 395, 405, 410, 400])
        crawl_log = _make_log()
        blocked, reason = await crawlers._detect_soft_block(db, STORE, 5, crawl_log)
        assert blocked is True
        assert "soft-block" in reason
        assert "5 products" in reason
        assert crawl_log["soft_block"]["decision"] == "blocked"
        assert crawl_log["soft_blocked"] is True
    asyncio.run(main())


def test_exact_zero_products_is_the_canonical_soft_block():
    """The literal HTTP 200 + data:[] case: current_count == 0."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [400] * 5)
        crawl_log = _make_log()
        blocked, reason = await crawlers._detect_soft_block(db, STORE, 0, crawl_log)
        assert blocked is True
        assert crawl_log["soft_blocked"] is True
        assert "0 products" in reason
    asyncio.run(main())


def test_current_exactly_at_floor_passes():
    """At floor (baseline × ratio) the crawl passes — inclusive boundary."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [100] * 5)  # median 100, floor 20
        crawl_log = _make_log()
        blocked, _ = await crawlers._detect_soft_block(db, STORE, 20, crawl_log)
        assert blocked is False
        assert crawl_log["soft_block"]["decision"] == "passed"
    asyncio.run(main())


def test_current_just_below_floor_blocks():
    """One below the floor is blocked — strict inequality on the below-side."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [100] * 5)  # median 100, floor 20
        crawl_log = _make_log()
        blocked, _ = await crawlers._detect_soft_block(db, STORE, 19, crawl_log)
        assert blocked is True
    asyncio.run(main())


def test_previously_soft_blocked_crawls_excluded_from_baseline():
    """A crawl already tagged soft_blocked must not poison the baseline for
    the next run — otherwise a bad crawl drags the median down and the guard
    stops firing (the classic silent degradation)."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [400, 400, 400, 400, 400])
        # inject a fake soft-blocked "successful" log at the tail
        await db.crawl_logs.insert_one({
            "id": "log-bad",
            "store_id": STORE["id"],
            "store_name": STORE["name"],
            "tier_used": 1,
            "products_found": 5,
            "soft_blocked": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        crawl_log = _make_log()
        blocked, _ = await crawlers._detect_soft_block(db, STORE, 5, crawl_log)
        assert blocked is True  # baseline still 400 because the bad log was excluded
        assert crawl_log["soft_block"]["baseline_median"] == 400
    asyncio.run(main())


def test_old_history_outside_lookback_window_ignored():
    """Only the last SOFT_BLOCK_LOOKBACK_DAYS days count towards the
    baseline. A 60-day-old crawl of 500 products must not shield today's
    soft-block."""
    async def main():
        db = _get_db(); await _reset(db)
        # Seed old good logs (60 days ago) — should be ignored
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        docs = [{
            "id": f"old-{i}",
            "store_id": STORE["id"],
            "store_name": STORE["name"],
            "tier_used": 1,
            "products_found": 500,
            "completed_at": old_ts,
        } for i in range(5)]
        await db.crawl_logs.insert_many(docs)
        crawl_log = _make_log()
        blocked, _ = await crawlers._detect_soft_block(db, STORE, 0, crawl_log)
        assert blocked is False  # insufficient history within window
        assert crawl_log["soft_block"]["samples"] == 0
    asyncio.run(main())


def test_failed_crawls_excluded_from_baseline():
    """A prior crawl with tier_used=None (a failure) must not be counted as
    a baseline sample — those are noise, not signal."""
    async def main():
        db = _get_db(); await _reset(db)
        # 5 failed crawls + 3 successful @ 400
        failed = [{
            "id": f"fail-{i}",
            "store_id": STORE["id"],
            "store_name": STORE["name"],
            "tier_used": None,
            "products_found": 0,
            "completed_at": (datetime.now(timezone.utc) - timedelta(days=5 + i)).isoformat(),
        } for i in range(5)]
        await db.crawl_logs.insert_many(failed)
        await _seed_history(db, [400, 400, 400])
        crawl_log = _make_log()
        blocked, _ = await crawlers._detect_soft_block(db, STORE, 5, crawl_log)
        assert blocked is True
        assert crawl_log["soft_block"]["samples"] == 3
    asyncio.run(main())


def test_detector_error_fails_open():
    """A broken guard must NEVER cost a working store its snapshots. If the
    detector hits a DB error, it must return (False, '') and pass through."""
    async def main():
        crawl_log = _make_log()
        # Pass a None db — motor call will explode inside the detector
        blocked, reason = await crawlers._detect_soft_block(None, STORE, 5, crawl_log)
        assert blocked is False
        assert reason == ""
        assert crawl_log["soft_block"]["decision"] == "detector_error"
    asyncio.run(main())


# ── _apply_soft_block contract ──────────────────────────────────────────────

def test_apply_soft_block_writes_all_required_fields():
    log = _make_log()
    crawlers._apply_soft_block(log, 5, "/en/api/v1/products", "test reason")
    assert log["tier_used"] is None
    assert log["http_status"] == 200
    assert log["products_found"] == 5
    assert log["snapshots_created"] == 0
    assert log["soft_blocked"] is True
    assert "soft-blocked" in log["endpoint_used"]
    assert log["error"] == "test reason"


def test_apply_soft_block_handles_no_endpoint_tag():
    log = _make_log()
    crawlers._apply_soft_block(log, 0, None, "reason")
    assert log["endpoint_used"] == "soft-blocked"


# ── previous snapshots preserved (regression fence) ─────────────────────────

def test_soft_blocked_crawl_does_not_touch_prior_snapshots():
    """The whole point of the guard: previously written snapshots for the
    store must be untouched. This test seeds N snapshots, calls the guard
    (blocked), and verifies count is unchanged. `process_crawled_products`
    is the ONLY write site for competitor snapshots, and the wiring in
    Tier 1/2/2.5/3 all skip it when soft_blocked=True."""
    async def main():
        db = _get_db(); await _reset(db)
        await _seed_history(db, [400] * 5)
        # Seed 10 prior snapshots for this store
        now = datetime.now(timezone.utc)
        prior = [{
            "id": f"snap-prior-{i}",
            "sku": f"SKU-{i}",
            "store_id": STORE["id"],
            "store_name": STORE["name"],
            "price": 100.0,
            "qty_available": 5,
            "crawled_at": now - timedelta(hours=1),
        } for i in range(10)]
        await db.product_snapshots.insert_many(prior)
        before = await db.product_snapshots.count_documents({"store_id": STORE["id"]})
        # Simulate the soft-block detection + apply
        crawl_log = _make_log()
        blocked, reason = await crawlers._detect_soft_block(db, STORE, 5, crawl_log)
        assert blocked is True
        crawlers._apply_soft_block(crawl_log, 5, "/api", reason)
        # This is the wiring contract: caller MUST skip process_crawled_products
        # when soft_blocked=True. We don't call it here; the snapshot count
        # must therefore be identical to the pre-crawl state.
        after = await db.product_snapshots.count_documents({"store_id": STORE["id"]})
        assert after == before == 10
    asyncio.run(main())


# ── tier wiring — code-shape fences ─────────────────────────────────────────

def test_tier1_calls_detect_soft_block_before_persistence():
    src = Path(crawlers.__file__).read_text()
    # inside crawl_salla_tier1 the detector is called with all_raw's length,
    # before process_crawled_products
    t1_body = src.split("async def crawl_salla_tier1", 1)[1].split("\nasync def ", 1)[0]
    assert "_detect_soft_block(db, store, len(all_raw)" in t1_body, \
        "Tier 1 must call the soft-block guard on len(all_raw) before persistence"
    assert "_apply_soft_block(" in t1_body
    # ordering: detector called before process_crawled_products
    det_pos = t1_body.index("_detect_soft_block(")
    proc_pos = t1_body.index("process_crawled_products(")
    assert det_pos < proc_pos, "guard must run BEFORE persistence in Tier 1"


def test_tier2_xhr_calls_detect_soft_block_before_persistence():
    src = Path(crawlers.__file__).read_text()
    t2_body = src.split("async def crawl_tier2_xhr", 1)[1].split("\nasync def ", 1)[0]
    assert "_detect_soft_block(db, store, len(captured_products)" in t2_body, \
        "Tier 2 XHR must call the soft-block guard on len(captured_products)"
    det_pos = t2_body.index("_detect_soft_block(")
    proc_pos = t2_body.index("process_crawled_products(")
    assert det_pos < proc_pos


def test_tier3_html_calls_detect_soft_block_before_persistence():
    src = Path(crawlers.__file__).read_text()
    t3_body = src.split("async def crawl_tier3_html", 1)[1].split("\nasync def ", 1)[0]
    assert "_detect_soft_block(db, store, len(products_extracted)" in t3_body
    det_pos = t3_body.index("_detect_soft_block(")
    proc_pos = t3_body.index("process_crawled_products(")
    assert det_pos < proc_pos


def test_tier2_5_storefront_categories_calls_detect_soft_block_before_persistence():
    src = Path(crawlers.__file__).read_text()
    t25_body = src.split("async def crawl_salla_storefront_categories", 1)[1].split("\nasync def ", 1)[0]
    assert "_detect_soft_block(db, store, len(captured)" in t25_body, \
        "Tier 2.5 storefront-categories must call the soft-block guard on len(captured)"
    det_pos = t25_body.index("_detect_soft_block(")
    proc_pos = t25_body.index("process_crawled_products(")
    assert det_pos < proc_pos


def test_supplement_is_skipped_when_soft_blocked_in_tier1():
    """When Tier 1 is soft-blocked, the barcode supplement must NOT run —
    there are effectively no items to enrich and the supplement would waste
    proxy bandwidth on a doomed crawl."""
    src = Path(crawlers.__file__).read_text()
    t1_body = src.split("async def crawl_salla_tier1", 1)[1].split("\nasync def ", 1)[0]
    # Extract the "success branch" (else clause of soft_blocked)
    # Confirms both _apply_soft_block AND _maybe_salla_detail_supplement are
    # in DIFFERENT branches of the if soft_blocked / else.
    assert "if soft_blocked:" in t1_body
    # The success branch (else) is where supplement + persistence live together
    else_branch = t1_body.split("if soft_blocked:", 1)[1].split("else:", 1)[1].split("\n    else:", 1)[0]
    assert "_maybe_salla_detail_supplement" in else_branch
    assert "process_crawled_products" in else_branch


def test_apply_soft_block_sets_tier_used_to_none():
    """The store's last_crawl_status will resolve to 'failed' when tier_used
    is None (see _finalize_crawl_log line 494), so a soft-block correctly
    surfaces as a failure in the dashboards and the coverage report."""
    log = _make_log()
    crawlers._apply_soft_block(log, 5, "endpoint", "reason")
    assert log["tier_used"] is None


# ── unit: detector diagnostic block shape ───────────────────────────────────

def test_detector_always_populates_soft_block_field():
    async def main():
        db = _get_db(); await _reset(db)
        crawl_log = _make_log()
        # No history at all — still populates the diagnostic block
        await crawlers._detect_soft_block(db, STORE, 100, crawl_log)
        assert "soft_block" in crawl_log
        assert crawl_log["soft_block"]["current_count"] == 100
        assert crawl_log["soft_block"]["decision"] == "insufficient_history"
    asyncio.run(main())


def test_iter73w_marker_present_in_source():
    """The guard is a distinct iteration and its provenance must survive
    future refactors — grep-friendly marker in the source."""
    src = Path(crawlers.__file__).read_text()
    assert "iter73w" in src
    assert "SOFT_BLOCK_MIN_BASELINE" in src
    assert "SOFT_BLOCK_FLOOR_RATIO" in src
