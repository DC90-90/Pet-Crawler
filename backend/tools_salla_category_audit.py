"""iter73 — Salla Theme Coverage Audit.

Zarafa going dark (0 categories → 0 products → whole catalogue missing from
Daleel) is exactly the kind of silent failure that only becomes visible when
a client asks "why isn't SKU X here?". This tool answers that question
BEFORE the client sees it: for every active Salla store, it runs the same
category-discovery step the crawler uses and reports how many category IDs
came back. Anything below MIN_HEALTHY_CATS is flagged as "at risk" so we can
patch the discovery regex, or verify the theme, or activate a fallback,
BEFORE the store's catalogue quietly stops appearing in Price Intel.

Run as:
    cd /app/backend && python tools_salla_category_audit.py

Persists results to `db.salla_category_audits` (one document per audit run)
so `GET /api/admin/salla-category-audit` (added in server.py) can serve them
without re-launching Playwright. Idempotent: re-running just appends a new
report and updates the "latest" convenience document.

This script talks to the LIVE storefronts, so it needs outbound network + the
Playwright browser. It is deliberately NOT scheduled — the previous crawler
schedule already does the real work. This is a health check, not a crawler.
"""
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from motor.motor_asyncio import AsyncIOMotorClient

from crawlers import _capture_salla_store_identifier, _discover_salla_category_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("salla_category_audit")

# Below this discovery count the store is considered "at risk" — 5 categories
# is the smallest healthy pet-store menu we have observed (typically 20-90).
# 0 means the discovery regex missed the theme entirely (the Zarafa bug); a
# single-digit count often means only the header nav parsed and the mega-menu
# never fired, which is still worth investigating.
MIN_HEALTHY_CATS = 5


async def audit_store(pw, store):
    """Run the category discovery for ONE Salla store and return the report."""
    base = f"https://{store['domain']}"
    report = {
        "store_id": store["id"], "store_name": store["name"], "domain": store["domain"],
        "platform": store.get("platform"), "is_active": store.get("is_active", True),
        "store_identifier": None, "categories_discovered": 0, "sample_ids": [],
        "flagged_at_risk": False, "error": None,
    }
    try:
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                       " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ar-SA",
        )
        page = await ctx.new_page()
        # capture_store_identifier already navigates to `base/` and waits
        report["store_identifier"] = await _capture_salla_store_identifier(page, base)
        # then hover the nav to expand mega-menus, then extract category ids
        ids = await _discover_salla_category_ids(page, base)
        await browser.close()
        report["categories_discovered"] = len(ids)
        report["sample_ids"] = ids[:10]
        report["flagged_at_risk"] = len(ids) < MIN_HEALTHY_CATS
    except Exception as e:
        report["error"] = str(e)[:200]
        report["flagged_at_risk"] = True
    return report


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    stores = [s async for s in db.stores.find(
        {"platform": "salla", "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "domain": 1, "platform": 1, "is_active": 1})]
    logger.info(f"auditing {len(stores)} active Salla stores")

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    reports = []

    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        # Sequential — headless Chromium isn't free on RAM and we prefer
        # honest observability over racing all 20 stores at once. Total run
        # is dominated by network latency (~10-30 s per store), acceptable
        # for a manual health-check tool.
        for i, s in enumerate(stores, 1):
            logger.info(f"[{i:>2}/{len(stores)}] {s['name']}  ({s['domain']}) ...")
            rep = await audit_store(pw, s)
            marker = "AT RISK" if rep["flagged_at_risk"] else "ok"
            err = f"   err={rep['error']}" if rep["error"] else ""
            logger.info(f"     → cats={rep['categories_discovered']:>3}  {marker}{err}")
            reports.append(rep)

    finished_at = datetime.now(timezone.utc)
    doc = {
        "run_id": run_id, "started_at": started_at, "finished_at": finished_at,
        "duration_secs": round((finished_at - started_at).total_seconds(), 1),
        "min_healthy_cats": MIN_HEALTHY_CATS,
        "total_stores": len(reports),
        "at_risk_count": sum(1 for r in reports if r["flagged_at_risk"]),
        "at_risk_stores": [r["domain"] for r in reports if r["flagged_at_risk"]],
        "reports": reports,
    }
    await db.salla_category_audits.insert_one({**doc, "_id": run_id})
    # convenience "latest" pointer for the admin endpoint
    await db.salla_category_audits_latest.replace_one(
        {"_id": "latest"}, {**doc, "_id": "latest"}, upsert=True)

    print()
    print("=" * 72)
    print(f"AUDIT COMPLETE — {doc['at_risk_count']}/{doc['total_stores']} stores flagged as AT RISK")
    print(f"threshold: fewer than {MIN_HEALTHY_CATS} categories discovered")
    print("=" * 72)
    for r in reports:
        if r["flagged_at_risk"]:
            print(f"  ⚠ {r['domain']:32s} cats={r['categories_discovered']:>3}  "
                  f"err={r['error'] or '-'}")
    print()
    print(f"persisted as db.salla_category_audits[_id={run_id!r}] and "
          f"db.salla_category_audits_latest")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
