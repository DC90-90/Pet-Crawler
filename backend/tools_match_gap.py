"""iter61 — the client's blast radius. READ ONLY, writes nothing.

Counts products that are MISSING A SELLER which we already crawled: a
competitor snapshot exists whose barcode or SKU canonicalises to one of our
product's GTIN-14 keys, and yet no product_matches row links them.

Run against production with the same MONGO_URL / DB_NAME the API uses::

    MONGO_URL=... DB_NAME=... python tools_match_gap.py
    MONGO_URL=... DB_NAME=... python tools_match_gap.py --detail 40

Each missing pair is attributed to one of three causes, because the fix differs:

  gtin14_normalization  the raw strings differ but the GTIN-14 forms are equal
                        — the Hills 052742059518 vs 52742059518 class. Fixed by
                        the matcher change; no re-crawl needed.
  competitor_barcode    the link exists only because the competitor SNAPSHOT
                        carries a barcode. Before iter61 the crawler extracted
                        and discarded it, so on data crawled before the fix
                        this bucket reads 0 and only grows after a re-crawl.
  blocked_by_guard      the keys DO meet, but iter51/52/53 rejected the pair
                        (pack mismatch, weight mismatch, or a >=6x price gap
                        with nothing corroborating pack size). These are NOT
                        missing sellers — they are the guards working, and they
                        are reported separately so the headline count is honest.
"""
import argparse
import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from core.utils import canonical_barcode
from matcher import (MATCH_WINDOW_DAYS, _barcode_key_set, _extract_weight_grams,
                     _pack_compatible, _weights_reject, barcode_price_sane)


def _name(p):
    return f"{p.get('name_ar', '')} {p.get('name_en', '')}".strip()


async def main(detail, window_days):
    db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[
        os.environ.get("DB_NAME", "daleel")]
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    own = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_id = own["id"] if own else None
    store_names = {s["id"]: s.get("name", s["id"]) async for s in db.stores.find({}, {"_id": 0, "id": 1, "name": 1})}

    mine = await db.my_products.find({}, {"_id": 0}).to_list(20000)
    products = {}
    async for p in db.products.find({}, {"_id": 0, "sku": 1, "name_ar": 1, "name_en": 1, "barcode": 1}):
        products[p["sku"]] = p

    # latest competitor snapshot per (sku, store), indexed by every GTIN-14 key
    by_key = {}
    q = {"crawled_at": {"$gte": since}}
    if own_id:
        q["store_id"] = {"$ne": own_id}
    seen = {}
    async for s in db.product_snapshots.find(
            q, {"_id": 0, "sku": 1, "store_id": 1, "barcode": 1, "price": 1, "crawled_at": 1}):
        k = (s.get("sku"), s.get("store_id"))
        if k not in seen or (s.get("crawled_at") or since) > (seen[k].get("crawled_at") or since):
            seen[k] = s
    snaps_with_barcode = 0
    for s in seen.values():
        if s.get("barcode"):
            snaps_with_barcode += 1
        keys = _barcode_key_set(
            barcodes=(s.get("barcode"), (products.get(s.get("sku")) or {}).get("barcode")),
            skus=(s.get("sku"),))
        for k in keys:
            by_key.setdefault(k, []).append(s)

    linked = set()
    async for m in db.product_matches.find({}, {"_id": 0, "my_sku": 1, "competitor_sku": 1, "competitor_store_id": 1}):
        linked.add((m.get("my_sku"), m.get("competitor_sku"), m.get("competitor_store_id")))

    causes = Counter()
    per_store = Counter()
    affected, rows = set(), []
    for mp in mine:
        my_sku = str(mp.get("sku", "")).strip()
        my_bc = str(mp.get("barcode", "")).strip()
        my_keys = _barcode_key_set(barcodes=(my_bc,), skus=(my_sku,))
        if not my_keys:
            continue
        my_literal = {v.lower() for v in (my_bc, my_sku) if v}
        my_name = _name(products.get(my_sku, {})) or f"{mp.get('name_ar','')} {mp.get('name_en','')}"
        my_w = _extract_weight_grams(my_name)
        cands = {}
        for k in my_keys:
            for s in by_key.get(k, []):
                cands[(s["sku"], s["store_id"])] = s
        for (c_sku, c_store), s in cands.items():
            if (my_sku, c_sku, c_store) in linked:
                continue
            c_name = _name(products.get(c_sku, {}))
            if not _pack_compatible(my_name, c_name) or _weights_reject(my_w, _extract_weight_grams(c_name)):
                causes["blocked_by_guard"] += 1
                continue
            if not barcode_price_sane(mp.get("sale_price") or mp.get("price"),
                                      s.get("price"), my_name, c_name)[0]:
                causes["blocked_by_guard"] += 1
                continue
            # a genuinely missing seller — attribute it
            comp_literal = {str(v).lower() for v in (s.get("sku"), s.get("barcode")) if v}
            if my_literal & comp_literal:
                cause = "other"                       # raw strings already agreed
            elif s.get("barcode") and canonical_barcode(s["barcode"]) in my_keys:
                cause = "competitor_barcode"
            else:
                cause = "gtin14_normalization"
            causes[cause] += 1
            per_store[store_names.get(c_store, c_store)] += 1
            affected.add(my_sku)
            rows.append((my_sku, my_bc, c_sku, s.get("barcode") or "-",
                         store_names.get(c_store, c_store), s.get("price"), cause))

    real = sum(v for k, v in causes.items() if k != "blocked_by_guard")
    print(f"catalogue products            {len(mine)}")
    print(f"competitor snapshots examined {len(seen)}  ({snaps_with_barcode} carry a barcode)")
    print(f"existing product_matches      {len(linked)}")
    print(f"\nMISSING SELLERS               {real}")
    print(f"products affected             {len(affected)} "
          f"({100 * len(affected) / max(len(mine), 1):.1f}% of catalogue)")
    for k, v in causes.most_common():
        print(f"  {k:<22} {v}")
    print("\nby store:")
    for k, v in per_store.most_common():
        print(f"  {k:<22} {v}")
    if detail:
        print(f"\nfirst {detail} missing pairs:")
        print(f"  {'our_sku':<16}{'our_barcode':<16}{'comp_sku':<20}{'comp_barcode':<16}{'store':<14}{'price':>8}  cause")
        for r in rows[:detail]:
            print(f"  {str(r[0]):<16}{str(r[1]):<16}{str(r[2]):<20}{str(r[3]):<16}{str(r[4]):<14}{str(r[5]):>8}  {r[6]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", type=int, default=25)
    ap.add_argument("--window-days", type=int, default=MATCH_WINDOW_DAYS)
    a = ap.parse_args()
    asyncio.run(main(a.detail, a.window_days))
