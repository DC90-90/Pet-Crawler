"""One-command market crawl orchestrator + report generator.

Runs the full pipeline headlessly (no API server, no auth):

    python run_market_crawl.py                  # crawl all active stores → match → report
    python run_market_crawl.py --report-only    # skip crawling, regenerate report from DB
    python run_market_crawl.py --stores mowkly.com,aleef.com   # limit crawl to these domains
    python run_market_crawl.py --concurrency 4 --days 30

Outputs (under ../reports/YYYY-MM-DD_HHMM/):
    summary.json           headline KPIs (stores, SKUs, matches, price position)
    market_share.csv       per-store catalog size, share %, in-stock rate, avg discount
    price_comparison.csv   every matched SKU: my price vs each competitor
    discounts.csv          all competitor products currently on discount
    out_of_stock.csv       competitor products currently out of stock
    recently_added.csv     products first seen within --recent-days (default 14)
    crawl_status.csv       per-store crawl outcome (tier used, products found, errors)

Requires backend/.env with MONGO_URL, DB_NAME, ENCRYPTION_KEY, JWT_SECRET.
Price history accumulates one point per crawl per SKU — schedule this script
(or run the API server with its built-in scheduler) to build trend data.
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
sys.path.insert(0, str(ROOT_DIR))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from crawlers import crawl_store_waterfall, sync_own_store_prices  # noqa: E402
from matcher import run_matching_for_all  # noqa: E402
from store_registry import ensure_stores  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("market_crawl")


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else (dt or "")


def _parse_dt(val):
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str) and val:
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


async def crawl_all(db, only_domains=None, concurrency=3):
    """Crawl own store first (benchmark catalog), then competitors concurrently."""
    results = []

    own = await db.stores.find_one({"is_own_store": True, "is_active": True}, {"_id": 0})
    if own and (not only_domains or own["domain"] in only_domains):
        logger.info(f"[Own] Syncing benchmark catalog from {own['domain']} ...")
        try:
            r = await sync_own_store_prices(db, store=own)
            results.append({"store": own["name"], "domain": own["domain"], "role": "own",
                            "status": "ok" if not r.get("error") else "error", **{k: r.get(k) for k in ("crawled", "updated", "discovered", "error")}})
        except Exception as exc:
            logger.error(f"[Own] Sync failed: {exc}")
            results.append({"store": own["name"], "domain": own["domain"], "role": "own", "status": "error", "error": str(exc)[:200]})

    comp_query = {"is_active": True, "is_own_store": {"$ne": True}}
    competitors = await db.stores.find(comp_query, {"_id": 0}).to_list(500)
    if only_domains:
        competitors = [s for s in competitors if s["domain"] in only_domains]
    logger.info(f"Crawling {len(competitors)} competitor stores (concurrency={concurrency})")

    sem = asyncio.Semaphore(concurrency)

    async def _one(store):
        async with sem:
            try:
                r = await crawl_store_waterfall(db, store)
                found = r.get("products_found", 0)
                tier = r.get("tier_used")
                logger.info(f"[Crawl] {store['name']}: tier={tier} products={found} err={r.get('error') or '-'}")
                return {"store": store["name"], "domain": store["domain"], "role": "competitor",
                        "platform": store.get("platform"), "tier_used": tier,
                        "products_found": found, "status": "ok" if tier else "failed",
                        "error": (r.get("error") or "")[:300]}
            except Exception as exc:
                logger.error(f"[Crawl] {store['name']} crashed: {exc}")
                return {"store": store["name"], "domain": store["domain"], "role": "competitor",
                        "platform": store.get("platform"), "tier_used": None,
                        "products_found": 0, "status": "error", "error": str(exc)[:300]}

    results.extend(await asyncio.gather(*[_one(s) for s in competitors]))
    return results


async def latest_snapshots(db, since):
    """Latest snapshot per (store_id, sku) since `since` — computed in Python so it
    works on both MongoDB and reduced-aggregation backends (FerretDB)."""
    latest = {}
    cursor = db.product_snapshots.find(
        {"crawled_at": {"$gte": since}},
        {"_id": 0, "sku": 1, "store_id": 1, "store_name": 1, "price": 1,
         "original_price": 1, "discount_pct": 1, "in_stock": 1, "qty_available": 1,
         "crawled_at": 1, "confidence_score": 1, "product_id": 1},
    )
    async for snap in cursor:
        key = (snap["store_id"], snap["sku"])
        prev = latest.get(key)
        if prev is None or _parse_dt(snap.get("crawled_at")) > _parse_dt(prev.get("crawled_at")):
            latest[key] = snap
    return list(latest.values())


async def build_report(db, out_dir: Path, days=30, recent_days=14):
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    stores = {s["id"]: s async for s in db.stores.find({}, {"_id": 0})}
    own_store = next((s for s in stores.values() if s.get("is_own_store")), None)
    snaps = await latest_snapshots(db, since)

    # ── market_share.csv ──
    per_store = defaultdict(lambda: {"skus": 0, "in_stock": 0, "discounted": 0, "discount_sum": 0.0, "price_sum": 0.0})
    for s in snaps:
        st = per_store[s["store_id"]]
        st["skus"] += 1
        st["in_stock"] += 1 if s.get("in_stock") else 0
        d = float(s.get("discount_pct") or 0)
        if d > 0:
            st["discounted"] += 1
            st["discount_sum"] += d
        st["price_sum"] += float(s.get("price") or 0)

    total_skus = sum(v["skus"] for v in per_store.values()) or 1
    my_count = await db.my_products.count_documents({})
    share_rows = []
    for sid, v in sorted(per_store.items(), key=lambda kv: -kv[1]["skus"]):
        meta = stores.get(sid, {})
        share_rows.append({
            "store": meta.get("name", sid), "domain": meta.get("domain", ""),
            "platform": meta.get("platform", ""), "skus_tracked": v["skus"],
            "catalog_share_pct": round(100 * v["skus"] / total_skus, 1),
            "in_stock_rate_pct": round(100 * v["in_stock"] / v["skus"], 1) if v["skus"] else 0,
            "pct_skus_on_discount": round(100 * v["discounted"] / v["skus"], 1) if v["skus"] else 0,
            "avg_discount_pct_when_discounted": round(v["discount_sum"] / v["discounted"], 1) if v["discounted"] else 0,
            "avg_price_sar": round(v["price_sum"] / v["skus"], 2) if v["skus"] else 0,
        })
    _write_csv(out_dir / "market_share.csv", share_rows)

    # ── price_comparison.csv (from product_matches, built by matcher) ──
    comp_rows = []
    async for m in db.product_matches.find({}, {"_id": 0}):
        comp_rows.append({
            "my_sku": m.get("my_sku"), "product": m.get("my_name_en") or m.get("my_name_ar"),
            "my_price_sar": m.get("my_price"),
            "competitor_store": m.get("competitor_store_name"),
            "competitor_price_sar": m.get("competitor_price"),
            "competitor_original_price_sar": m.get("competitor_original_price"),
            "diff_sar": m.get("diff_sar"), "diff_pct": m.get("diff_pct"),
            "my_position": m.get("position"),
            "competitor_in_stock": m.get("competitor_in_stock"),
            "competitor_qty": m.get("competitor_qty"),
            "match_method": m.get("match_method"), "confidence": m.get("confidence"),
            "flags": ";".join(m.get("flags") or []),
        })
    comp_rows.sort(key=lambda r: (r["my_sku"] or "", r["competitor_store"] or ""))
    _write_csv(out_dir / "price_comparison.csv", comp_rows)

    # ── discounts.csv ──
    disc_rows = [{
        "store": s.get("store_name"), "sku": s.get("sku"),
        "price_sar": s.get("price"), "original_price_sar": s.get("original_price"),
        "discount_pct": s.get("discount_pct"), "in_stock": s.get("in_stock"),
        "qty_available": s.get("qty_available"), "crawled_at": _iso(s.get("crawled_at")),
    } for s in snaps if float(s.get("discount_pct") or 0) > 0]
    disc_rows.sort(key=lambda r: -(r["discount_pct"] or 0))
    _write_csv(out_dir / "discounts.csv", disc_rows)

    # ── out_of_stock.csv ──
    oos_rows = [{
        "store": s.get("store_name"), "sku": s.get("sku"), "last_price_sar": s.get("price"),
        "crawled_at": _iso(s.get("crawled_at")),
    } for s in snaps if not s.get("in_stock")]
    _write_csv(out_dir / "out_of_stock.csv", oos_rows)

    # ── recently_added.csv ──
    recent_cut = now - timedelta(days=recent_days)
    recent_rows = []
    async for p in db.products.find({}, {"_id": 0, "sku": 1, "name_en": 1, "name_ar": 1, "brand": 1, "category": 1, "first_seen_at": 1}):
        fs = _parse_dt(p.get("first_seen_at"))
        if fs and fs >= recent_cut:
            recent_rows.append({"sku": p.get("sku"), "name": p.get("name_en") or p.get("name_ar"),
                                "brand": p.get("brand"), "category": p.get("category"),
                                "first_seen_at": _iso(p.get("first_seen_at"))})
    recent_rows.sort(key=lambda r: r["first_seen_at"], reverse=True)
    _write_csv(out_dir / "recently_added.csv", recent_rows)

    # ── summary.json ──
    positions = defaultdict(int)
    matched_skus = set()
    for r in comp_rows:
        positions[r["my_position"]] += 1
        matched_skus.add(r["my_sku"])
    summary = {
        "generated_at": now.isoformat(),
        "window_days": days,
        "own_store": own_store.get("domain") if own_store else None,
        "stores_total": len(stores),
        "stores_with_data": len(per_store),
        "competitor_skus_tracked": total_skus if per_store else 0,
        "my_products": my_count,
        "my_skus_matched_to_competitors": len(matched_skus),
        "match_rows": len(comp_rows),
        "price_position_counts": dict(positions),
        "competitor_skus_on_discount": len(disc_rows),
        "competitor_skus_out_of_stock": len(oos_rows),
        "products_recently_added": len(recent_rows),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def _write_csv(path: Path, rows):
    if not rows:
        path.write_text("")
        return
    fieldnames = []
    for r in rows:  # union of keys, first-seen order (rows can be heterogeneous)
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel opens Arabic correctly
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(rows)


async def main():
    ap = argparse.ArgumentParser(description="Crawl Salla/Zid pet stores and build a market report")
    ap.add_argument("--stores", help="comma-separated domains to crawl (default: all active)")
    ap.add_argument("--skip-crawl", "--report-only", dest="skip_crawl", action="store_true")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--days", type=int, default=30, help="snapshot window for the report")
    ap.add_argument("--recent-days", type=int, default=14, help="window for recently_added.csv")
    ap.add_argument("--skip-matching", action="store_true")
    ap.add_argument("--out", help="report output dir (default ../reports/<timestamp>)")
    args = ap.parse_args()

    mongo_url = os.environ["MONGO_URL"]
    db = AsyncIOMotorClient(mongo_url)[os.environ["DB_NAME"]]

    await ensure_stores(db)
    crawl_results = []
    if not args.skip_crawl:
        only = set(args.stores.split(",")) if args.stores else None
        crawl_results = await crawl_all(db, only_domains=only, concurrency=args.concurrency)
        ok = sum(1 for r in crawl_results if r["status"] == "ok")
        logger.info(f"Crawl finished: {ok}/{len(crawl_results)} stores OK")

    if not args.skip_matching:
        if await db.my_products.count_documents({}) > 0:
            stats = await run_matching_for_all(db)
            logger.info(f"Matching: {stats}")
        else:
            logger.warning("my_products is empty — own-store sync found nothing and no import was done; skipping matching")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    out_dir = Path(args.out) if args.out else ROOT_DIR.parent / "reports" / stamp
    summary = await build_report(db, out_dir, days=args.days, recent_days=args.recent_days)
    if crawl_results:
        _write_csv(out_dir / "crawl_status.csv", crawl_results)

    print("\n=== MARKET CRAWL SUMMARY ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nReport written to {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
