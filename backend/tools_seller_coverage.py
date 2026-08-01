"""iter60 — measure the seller-list fix on a real database. READ ONLY.

Reports, for the whole catalogue:

    before   sellers per product under the old rule
             (product_snapshots WHERE sku == my_sku AND crawled_at >= now-30d)
    after    sellers per product under the new rule
             (the same, UNION every store product_matches links to that SKU,
              over a 180-day lookback, minus rows the pack guard rejects)

Run against production with the same MONGO_URL / DB_NAME the API uses::

    MONGO_URL=... DB_NAME=... python tools_seller_coverage.py
    MONGO_URL=... DB_NAME=... python tools_seller_coverage.py 052742059518 3182550702263

Writes nothing. Reads product_snapshots, product_matches, products, my_products.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from seller_set import (SELLER_LOOKBACK_DAYS, alias_map_from_matches,
                        hub_skus_from_matches, latest_per_store, pack_guard_ok,
                        snapshot_or_clauses)

OLD_WINDOW_DAYS = 30


async def _before(db, sku, now):
    since = now - timedelta(days=OLD_WINDOW_DAYS)
    rows = await db.product_snapshots.find(
        {"sku": sku, "crawled_at": {"$gte": since}},
        {"_id": 0, "store_id": 1}).to_list(5000)
    return {r["store_id"] for r in rows if r.get("store_id")}


async def _after(db, sku, now):
    proj = {"_id": 0, "my_sku": 1, "competitor_sku": 1, "competitor_store_id": 1}
    direct = await db.product_matches.find({"my_sku": sku}, proj).to_list(2000)
    reverse = await db.product_matches.find({"competitor_sku": sku}, proj).to_list(2000)
    hubs = hub_skus_from_matches(reverse, sku)
    siblings = (await db.product_matches.find({"my_sku": {"$in": hubs}}, proj).to_list(4000)
                if hubs else [])
    aliases = alias_map_from_matches(direct + reverse + siblings, sku)

    sku_keys = sorted({sku} | set(hubs))
    clauses = snapshot_or_clauses(sku_keys, aliases)
    query = {"crawled_at": {"$gte": now - timedelta(days=SELLER_LOOKBACK_DAYS)}}
    if len(clauses) > 1:
        query["$or"] = clauses
    else:
        query.update(clauses[0])
    rows = await db.product_snapshots.find(
        query, {"_id": 0, "store_id": 1, "sku": 1, "crawled_at": 1}
    ).sort("crawled_at", -1).to_list(8000)
    rows.reverse()

    prod = await db.products.find_one({"sku": sku}, {"_id": 0, "name_ar": 1, "name_en": 1}) or {}
    hub_name = f"{prod.get('name_ar', '')} {prod.get('name_en', '')}".strip()
    alias_skus = sorted({str(r.get("sku")) for r in rows if str(r.get("sku")) not in sku_keys})
    names = {}
    if alias_skus:
        async for p in db.products.find({"sku": {"$in": alias_skus}},
                                        {"_id": 0, "sku": 1, "name_ar": 1, "name_en": 1}):
            names[p["sku"]] = f"{p.get('name_ar', '')} {p.get('name_en', '')}".strip()

    kept, excluded = [], 0
    for r in rows:
        rsku = str(r.get("sku"))
        if rsku in sku_keys or pack_guard_ok(hub_name, names.get(rsku, ""))[0]:
            kept.append(r)
        else:
            excluded += 1
    return set(latest_per_store(kept)), excluded


async def main(skus):
    db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[
        os.environ.get("DB_NAME", "daleel")]
    now = datetime.now(timezone.utc)
    if not skus:
        skus = [p["sku"] async for p in db.my_products.find({}, {"_id": 0, "sku": 1})]
    tot_b = tot_a = gained = excluded_total = 0
    for sku in skus:
        b, (a, ex) = await _before(db, sku, now), await _after(db, sku, now)
        tot_b += len(b)
        tot_a += len(a)
        excluded_total += ex
        if len(a) > len(b):
            gained += 1
        if len(skus) <= 25 or len(a) != len(b):
            print(f"  {sku:<20} before {len(b):>3}  after {len(a):>3}"
                  f"{'  (+%d)' % (len(a) - len(b)) if len(a) != len(b) else ''}"
                  f"{'  guard-excluded %d' % ex if ex else ''}")
    n = max(len(skus), 1)
    print(f"\nproducts                {n}")
    print(f"avg sellers before      {tot_b / n:.2f}")
    print(f"avg sellers after       {tot_a / n:.2f}")
    print(f"products gaining        {gained} ({100 * gained / n:.1f}%)")
    print(f"rows kept out by guard  {excluded_total}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
