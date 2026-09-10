"""iter76 — the three defects the iter75 drop left behind, fenced.

1. `fetch_policy.polite_get` documents "never raises", but `_penalise` read
   `resp.headers` directly. Any response object without that attribute turned a
   real HTTP status into an "exception" in the crawl log — the per-status
   buckets (`failed_403=`, `failed_429=`) that make a defended route
   diagnosable were silently lost.

2. The Salla velocity POOL reads the SEALED KSA window (today excluded by
   design), so a `sku_sales_daily` row dated TODAY is invisible to it. Two
   ranking suites seeded exactly that and — once iter75 stopped them from
   running against the real database — every pool came out at zero velocity,
   every Salla estimate was 0, and `revenue_tier` fell to "none". Fenced here so
   nobody re-seeds "today" and re-breaks them.

3. The API-contract suite creates stores on *.example.com and left them ACTIVE,
   so "TEST_Regression_Store" and "Test Store" showed on the client's Stores
   page, in the active-store counts and in the crawl schedule.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["DB_NAME"] = "test_iter76_stability"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_iter76_stability"
import fetch_policy  # noqa: E402
import ledger  # noqa: E402
import server  # noqa: E402
import store_registry  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")


# ── 1. polite_get never raises, whatever the response looks like ─────────────
class _HeaderlessResp:
    """A response object with no `headers` — what every hand-rolled test double
    and some non-httpx clients look like."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.content = b"x"

    def json(self):
        return {}


class _Client:
    def __init__(self, resp):
        self.resp = resp
        self.calls = 0

    async def get(self, url, params=None, headers=None):
        self.calls += 1
        return self.resp


def test_polite_get_survives_a_response_without_headers():
    fetch_policy.reset_hosts()
    client = _Client(_HeaderlessResp(403))
    saved = fetch_policy._curl_requests
    fetch_policy._curl_requests = None          # no outbound impersonation here
    try:
        resp = asyncio.run(fetch_policy.polite_get(
            client, "https://example.com/x", attempts=2))
    finally:
        fetch_policy._curl_requests = saved
        fetch_policy.reset_hosts()
    # the STATUS is returned — not swallowed into "exception"
    assert resp is not None and resp.status_code == 403
    assert client.calls == 2


def test_penalise_reads_retry_after_when_it_is_present():
    class _WithHeaders(_HeaderlessResp):
        headers = {"Retry-After": "3"}

    state = {"delay": fetch_policy.BASE_DELAY, "next_at": 0.0, "ok_streak": 4,
             "throttled": 0, "requests": 0, "impersonated": 0}
    assert fetch_policy._penalise(state, _WithHeaders(429)) == 3.0
    assert state["ok_streak"] == 0 and state["throttled"] == 1


# ── 2. the sealed-window fixture contract ────────────────────────────────────
def test_todays_rollup_row_is_invisible_to_the_sealed_ranking_window():
    """The property both ranking suites must respect when seeding sales."""
    now = server.datetime.now(server.timezone.utc)
    start, end = ledger.sealed_ksa_window(server._RANKING_WINDOW_DAYS, now)
    today = server._metric_day_str(now)
    sealed = server._metric_day_str(now - server.timedelta(days=1))
    upper = server._metric_day_str(end - server.timedelta(seconds=1))
    assert today > upper, "a row dated today can never enter the sealed window"
    assert sealed <= upper, "yesterday is the newest day the sealed window sees"
    assert server._metric_day_str(start) <= sealed


def test_ranking_fixtures_seed_a_sealed_day_not_today():
    """Regression fence: re-seeding `_metric_day_str(now)` in either RANKING
    fixture silently zeroes every Salla velocity pool and takes `revenue_tier`
    from "estimated" to "none". (The estimate-PREVIEW fixture in the same file
    is exempt — that endpoint reads an open-ended 30d window.)"""
    for name, func in (("test_salla_sold_velocity.py", "_seed_tiers"),
                       ("test_salla_revenue_estimate.py", "_seed_ranking")):
        src = (Path(__file__).parent / name).read_text()
        body = src.split(f"async def {func}(", 1)[1].split("\n\n\n", 1)[0]
        assert '"date": sealed_day' in body, f"{name}:{func}"
        assert "_metric_day_str(now)" not in body, (
            f"{name}:{func} seeds sku_sales_daily on TODAY, which the sealed "
            "ranking window excludes by design")


# ── 3. reserved-domain test stores never reach the client's Stores page ──────
def test_ensure_stores_removes_reserved_domain_test_stores():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await db.stores.delete_many({})
        await db.stores.insert_many([
            {"id": "t1", "name": "TEST_Regression_Store",
             "domain": "test-regression.example.com", "platform": "salla",
             "is_active": True},
            {"id": "t2", "name": "Test Store", "domain": "test.example.com",
             "platform": "salla", "is_active": True},
            {"id": "real", "name": "Zarafa", "domain": "zarafaksa.com",
             "platform": "salla", "is_active": True},
        ])
        await store_registry.ensure_stores(db)

        for sid in ("t1", "t2"):
            assert await db.stores.find_one({"id": sid}) is None, sid
        # a genuine storefront is untouched
        assert (await db.stores.find_one({"id": "real"}))["is_active"] is True
        await db.stores.delete_many({})
    asyncio.run(main())


def test_create_store_refuses_reserved_domains():
    """Boot-time hygiene alone would let the next regression run re-add them
    until the following restart — so the create path refuses at the boundary."""
    src = Path(server.__file__).read_text()
    body = src.split("async def create_store(", 1)[1].split("\n\n", 1)[0]
    assert 'endswith("example.com")' in body
    assert "raise HTTPException(400" in body
