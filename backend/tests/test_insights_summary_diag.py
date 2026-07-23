"""iter27 — temporary /api/insights/summary 500-diagnostic instrumentation.

The real _insights_summary_compute uses $push/$addToSet aggregations that the
FerretDB shim can't run, so these tests validate the DIAGNOSTIC WRAPPER by
injecting a stub compute (monkeypatching _insights_summary_compute):

  • success → normal body, byte-identical, no diagnostic keys, cache headers set
  • failure + super_admin → HTTP 200 diagnostic payload with the right shape,
    exception fields, last-2000-char traceback, and the captured failed_stage
  • failure + non-super_admin → re-raises (normal 500)
  • flag off → re-raises even for super_admin
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_diag")
import server  # noqa: E402
from starlette.responses import Response  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

SUPER = {"id": "1", "email": "a.disi@taqueen.sa", "role": "super_admin"}
VIEWER = {"id": "2", "email": "viewer@x.com", "role": "viewer"}
MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")


def _db():
    db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
    server.db = db
    return db


async def _clear_cache(db):
    await db.dashboard_cache.delete_many({})


def test_success_path_byte_identical_no_diag_keys():
    async def main():
        db = _db(); await _clear_cache(db)
        payload = {"total_skus": 5, "price_drops": 2, "product_gaps": 1,
                   "median_spread": 3.14, "avg_confidence": 95.0,
                   "freshness_breakdown": {"today": 4}, "market_position_summary": None}

        async def ok_compute(_db, _days):
            server._diag_stage("build_response")
            return payload
        orig = server._insights_summary_compute
        server._insights_summary_compute = ok_compute
        try:
            r = Response()
            body = await server.insights_summary(days=30, response=r, user=SUPER)
            assert body == payload, body
            assert "error" not in body
            assert r.headers.get("x-cache-source") in ("live_fallback", "cache")
        finally:
            server._insights_summary_compute = orig
        print("PASS: success path byte-identical, no diagnostic keys")
    asyncio.run(main())


def test_failure_super_admin_gets_200_diagnostic():
    async def main():
        db = _db(); await _clear_cache(db)

        async def boom_compute(_db, _days):
            server._diag_stage("market_position:fetch_matches")
            raise ValueError("simulated production boom")
        orig = server._insights_summary_compute
        server._insights_summary_compute = boom_compute
        try:
            r = Response()
            body = await server.insights_summary(days=30, response=r, user=SUPER)
            assert body["error"] is True, body
            assert body["exception_type"] == "ValueError"
            assert "simulated production boom" in body["exception_message"]
            assert body["failed_stage"] == "market_position:fetch_matches", body["failed_stage"]
            assert body["traceback"] and len(body["traceback"]) <= 2000
            assert "ValueError" in body["traceback"]
        finally:
            server._insights_summary_compute = orig
        print("PASS: super_admin gets 200 diagnostic with stage + traceback")
    asyncio.run(main())


def test_failure_non_super_admin_reraises():
    async def main():
        db = _db(); await _clear_cache(db)

        async def boom_compute(_db, _days):
            raise RuntimeError("nope")
        orig = server._insights_summary_compute
        server._insights_summary_compute = boom_compute
        try:
            raised = False
            try:
                await server.insights_summary(days=30, response=Response(), user=VIEWER)
            except RuntimeError:
                raised = True
            assert raised, "non-super_admin must get the raw exception (→ 500)"
        finally:
            server._insights_summary_compute = orig
        print("PASS: non-super_admin re-raises (normal 500)")
    asyncio.run(main())


def test_flag_off_reraises_for_super_admin():
    async def main():
        db = _db(); await _clear_cache(db)

        async def boom_compute(_db, _days):
            raise RuntimeError("nope")
        orig_compute = server._insights_summary_compute
        orig_flag = server.INSIGHTS_SUMMARY_DIAGNOSTIC
        server._insights_summary_compute = boom_compute
        server.INSIGHTS_SUMMARY_DIAGNOSTIC = False
        try:
            raised = False
            try:
                await server.insights_summary(days=30, response=Response(), user=SUPER)
            except RuntimeError:
                raised = True
            assert raised, "flag off → even super_admin gets the raw 500"
        finally:
            server._insights_summary_compute = orig_compute
            server.INSIGHTS_SUMMARY_DIAGNOSTIC = orig_flag
        print("PASS: flag off → re-raises for super_admin too")
    asyncio.run(main())


if __name__ == "__main__":
    test_success_path_byte_identical_no_diag_keys()
    test_failure_super_admin_gets_200_diagnostic()
    test_failure_non_super_admin_reraises()
    test_flag_off_reraises_for_super_admin()
    print("ALL INSIGHTS-SUMMARY DIAGNOSTIC TESTS PASSED")
