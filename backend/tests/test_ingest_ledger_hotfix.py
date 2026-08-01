"""iter68 HOTFIX — the iter67 ledger wiring must never cost an ingest its snapshots.

Production, day after the iter67 deploy: POST /api/crawler/ingest with 1 valid
product returned 200 with

    {"received":1,"inserted":0,"updated":1,"skipped":1,
     "errors":[{"index":0,"sku":"5274204208",
                "error":"NameError: name '_ledger_obs' is not defined"}]}

Mechanism: server.py has known drift between GitHub main and the production
workspace. The iter67 INIT hunk (`_ledger_obs = []`) missed its anchor on the
workspace copy while the APPEND hunk landed — so the append raised NameError
inside the per-row try/except, which recorded it as a ROW failure and skipped
the snapshot write. Every CMD-crawler daily push silently degraded to
products-metadata-only, no prices.

The fix makes the executing path immune to that whole failure mode:
  (a) the buffer is bound at HANDLER START, anchored on the pre-drift auth
      block, before any branch;
  (b) the append site is itself fail-soft — a ledger problem of ANY kind may
      cost ledger rows, never the snapshot beneath it.

These tests run the real handler end-to-end (real Mongo/FerretDB) and pin both
directions: the happy path writes snapshot AND ledger; a ledger blowing up
mid-ingest still writes the snapshot with a clean response.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_ingest_ledger_fix")
import ledger  # noqa: E402
import server  # noqa: E402
from models import IngestPayload  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")

# The production shape: Zarafa via the CMD crawler, the Hills internal-sku row
PAYLOAD = IngestPayload(
    store_id="zarafa-cmd", store_name="Zarafa", domain="zarafaksa.com",
    platform="salla",
    products=[{"sku": "5274204208", "name_ar": "هيلز جي اي بايوم",
               "name_en": "Hills GI Biome Cat 1.5kg", "barcode": "052742059518",
               "price": 170.0, "sale_price": 162.5, "quantity": 5,
               "sold_count": 40, "in_stock": True,
               "product_url": "/ar/hills-gi/p1694697895"}],
)


class _Req:
    def __init__(self, token):
        self.headers = {"authorization": f"Bearer {token}"}


async def _reset(db):
    for c in ("stores", "products", "product_snapshots", "my_products",
              "daily_ledger", "daily_ledger_store", "sku_store_coverage",
              "metric_daily_rollups", "sku_sales_daily"):
        await db[c].delete_many({})


def _payload():
    return IngestPayload(**PAYLOAD.dict())


def test_ingest_writes_snapshot_and_ledger_with_clean_response():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _reset(db)
        server.db = db
        out = await server.crawler_ingest(_Req(server.CRAWLER_TOKEN), _payload())

        # the production symptom, inverted
        assert out.get("errors") in ([], None), out
        assert out.get("skipped") == 0, out
        assert out.get("inserted") == 1, out

        snap = await db.product_snapshots.find_one({"sku": "5274204208"}, {"_id": 0})
        assert snap is not None, "snapshot must be written"
        assert snap["price"] == 162.5 and snap["qty_available"] == 5

        # and the ledger row landed too (the wiring works when healthy)
        day = ledger.ksa_day_str(snap["crawled_at"])
        row = await db.daily_ledger.find_one({"_id": f"{snap['store_id']}|5274204208|{day}"})
        assert row is not None, "ledger observation must be recorded"
        assert row["close_price"] == 162.5
        assert row["sold_count_cumulative"] == 40      # the LEVEL
        assert row["backfilled"] is False
    asyncio.run(main())


def test_ledger_failure_never_costs_the_snapshot():
    """record_observations raising — the iter67 class of failure, forced —
    must leave the ingest completely healthy: snapshot written, no errors,
    nothing skipped."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _reset(db)
        server.db = db
        orig = server.ledger.record_observations

        async def _boom(*a, **k):
            raise RuntimeError("ledger down")
        server.ledger.record_observations = _boom
        try:
            out = await server.crawler_ingest(_Req(server.CRAWLER_TOKEN), _payload())
        finally:
            server.ledger.record_observations = orig

        assert out.get("errors") in ([], None), out
        assert out.get("skipped") == 0, out
        snap = await db.product_snapshots.find_one({"sku": "5274204208"}, {"_id": 0})
        assert snap is not None, "a ledger failure may cost ledger rows, never snapshots"
        assert snap["price"] == 162.5
        # and, this time, no ledger row — the failure cost exactly what it may
        assert await db.daily_ledger.count_documents({}) == 0
    asyncio.run(main())


def test_buffer_is_bound_before_any_branch_and_append_is_guarded():
    """Pin the structural fix at source level, so a future edit cannot
    reintroduce the scoping hazard: the init precedes the outer try, and the
    append sits inside its own try/except."""
    import inspect
    src = inspect.getsource(server.crawler_ingest)
    init_at = src.index("_ledger_obs = []")
    outer_try_at = src.index("\n    try:")
    assert init_at < outer_try_at, "buffer must be bound at handler start, before any branch"
    append_at = src.index("_ledger_obs.append(")
    guard_at = src.rindex("try:", 0, append_at)
    assert guard_at > init_at, "the append site must sit inside its own try/except"
    assert "except Exception as _ledger_err" in src
    asyncio.run(asyncio.sleep(0))  # keep the runner shape uniform
    return None


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
