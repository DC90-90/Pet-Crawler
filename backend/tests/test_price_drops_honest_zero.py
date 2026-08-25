"""iter66 — the Insights "Price Drops" KPI reports the true count, honest 0 included.

The line used to read

    price_drops = drops_count if drops_count > 0 else random.randint(8, 25)

— a demo-era fallback that survived into production. Whenever the real windowed
count was zero (a genuinely quiet window, or a deploy whose rollups had not yet
backfilled), the API fabricated a number between 8 and 25. The card could never
legitimately display 0, and both audit passes flagged it independently. A
paying client makes pricing decisions off this card; an invented value is
strictly worse than an honest zero.

These tests pin the fix and its converse:
- drops_count == 0  ->  the KPI is exactly 0, deterministically (no randomness)
- drops_count > 0   ->  the KPI is exactly that count, unchanged
- no live code path in server.py calls random.* outside the SEED_DEMO_DATA-gated
  seed_database — so this class of fabrication cannot quietly return.
"""
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_price_drops_zero"
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")


async def _seed(db, drops_rows):
    for c in ("products", "metric_daily_rollups", "sku_store_coverage",
              "my_products", "product_matches", "own_store_orders", "stores",
              "dashboard_cache"):
        await db[c].delete_many({})
    await db.products.insert_one(
        {"sku": "S1", "name_ar": "منتج", "name_en": "P1", "category": "cat_food"})
    if drops_rows:
        await db.metric_daily_rollups.insert_many(drops_rows)


def _rollup(store_id, days_ago, drops):
    day = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return {"_id": f"{store_id}|{day}", "store_id": store_id, "date": day,
            "drops": drops, "conf_sum": 95.0, "conf_count": 1}


class _stubbed_coverage_helpers:
    """FerretDB implements neither $min/$max nor $dateToString, so the
    UNRELATED spread/gaps/freshness helpers inside _insights_summary_compute
    are stubbed to empties. _drops_from_rollups — the pipeline under test —
    runs for real against the seeded rollups."""

    def __enter__(self):
        async def _empty_list(_db, _since):
            return []

        async def _zero(_db, _since):
            return 0

        async def _fresh(*_a):
            return {"total": 0, "d1": 0, "d7": 0, "d30": 0, "stale": 0}

        async def _mp(_db):
            return None
        self.orig = (server._gaps_from_coverage, server._spread_docs_from_coverage,
                     server._freshness_from_coverage, server._compute_market_position_summary)
        server._gaps_from_coverage = _zero
        server._spread_docs_from_coverage = _empty_list
        server._freshness_from_coverage = _fresh
        server._compute_market_position_summary = _mp
        return self

    def __exit__(self, *a):
        (server._gaps_from_coverage, server._spread_docs_from_coverage,
         server._freshness_from_coverage, server._compute_market_position_summary) = self.orig


def test_zero_drops_returns_exactly_zero_not_a_random_number():
    """The fix itself. Run the compute several times: under the old code the
    odds of random.randint(8, 25) returning the same value 5 times are ~1 in
    100k, and it could never return 0 at all — so equality with 0 on every run
    is proof the fabrication is gone, not luck."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db, drops_rows=[])            # no rollups: true count is 0
        server.db = db
        with _stubbed_coverage_helpers():
            for _ in range(5):
                out = await server._insights_summary_compute(db, 30)
                assert out["price_drops"] == 0, out
    asyncio.run(main())


def test_a_real_count_passes_through_unchanged():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db, drops_rows=[
            _rollup("store-a", 2, 3), _rollup("store-a", 5, 4),
            _rollup("store-b", 1, 5),
            _rollup("store-c", 90, 999),          # outside the 30d window
        ])
        server.db = db
        with _stubbed_coverage_helpers():
            out = await server._insights_summary_compute(db, 30)
        assert out["price_drops"] == 12          # 3 + 4 + 5, window-bounded
    asyncio.run(main())


def test_no_live_code_path_uses_random():
    """Regression fence: every random.* call in server.py must sit inside
    seed_database (gated by SEED_DEMO_DATA) — comments and string literals
    aside. If this fails, a fabricated value crept back into a live path."""
    src = Path(server.__file__).read_text().splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith("async def seed_database"))
    end = next(i for i in range(start + 1, len(src))
               if re.match(r"^(async def |def |@)", src[i]))
    offenders = []
    for i, line in enumerate(src):
        if start <= i < end:
            continue
        code = line.split("#", 1)[0]              # strip trailing comments
        if re.search(r"\brandom\.\w+\(", code) and "'" not in code and '"' not in code:
            offenders.append((i + 1, line.strip()))
    assert offenders == [], offenders


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception:
            bad += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
