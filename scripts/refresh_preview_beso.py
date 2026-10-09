"""Explicitly authorized Beso-only refresh. Refuses remote Mongo and non-preview origins.

Source URLs/expected identities come from the reviewed evidence manifest; prices and
quantities are ALWAYS fetched anew. No boot tasks, full-store crawls or history edits.
"""
import argparse
import asyncio
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
TARGETS = {"8699245859829", "Hair & Skin", "5065023629268", "5065023629848"}
FIELDS = ("id", "sku", "barcode", "name", "price", "sale_price", "effective_price", "currency",
          "quantity", "is_infinite", "in_stock", "has_options", "is_taxable", "attributes", "images")


def guard(config, preview, supplied):
    if urlsplit(config["MONGO_URL"]).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Refusing non-local MongoDB")
    if preview != supplied or not (urlsplit(preview).hostname or "").endswith(".preview.emergentagent.com"):
        raise RuntimeError("Explicit current preview URL required")
    return config["MONGO_URL"], config["DB_NAME"]


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


async def capture(http, expected):
    url = expected["product_url"]
    response = await http.get(url)
    response.raise_for_status()
    stamp = datetime.now(timezone.utc)
    native = re.search(r"(?:window\.)?productObj\s*=\s*", response.text)
    if native:
        product = json.JSONDecoder().raw_decode(response.text[native.end():])[0]
        raw = {k: product[k] for k in FIELDS if k in product}
        if product.get("variants"):
            raw["variants"] = [{k: child[k] for k in FIELDS if k in child} for child in product["variants"]]
    else:
        soup = BeautifulSoup(response.text, "html.parser")
        products = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                products.extend(n for n in nodes(json.loads(script.string or script.text)) if n.get("@type") == "Product")
            except ValueError:
                continue
        if len(products) != 1 or not soup.select_one(".product-sku"):
            raise RuntimeError("Unambiguous source product identity unavailable")
        product = products[0]
        offer = product["offers"]
        if isinstance(offer, list):
            if len(offer) != 1:
                raise RuntimeError("Unresolved source offers")
            offer = offer[0]
        availability = offer.get("availability", "").rsplit("/", 1)[-1]
        raw = {"id": expected["id"], "sku": soup.select_one(".product-sku").get_text(strip=True),
               "name": product["name"], "price": offer["price"], "currency": offer["priceCurrency"],
               "in_stock": True if availability == "InStock" else False if availability == "OutOfStock" else None,
               "images": product.get("image", [])}
    if raw.get("sku") != expected["sku"] or str(raw.get("id")) != str(expected["id"]):
        raise RuntimeError("Source identity changed: refusing write")
    raw["product_url"] = url
    return raw, stamp, hashlib.sha256(response.content).hexdigest()


async def fingerprints(db):
    result = {}
    for name, query in (("my_products", {"sku": {"$nin": sorted(TARGETS)}}),
                        ("product_snapshots", {"sku": {"$nin": sorted(TARGETS)}}),
                        ("product_matches", {"my_sku": {"$nin": sorted(TARGETS)}})):
        digest = hashlib.sha256()
        async for row in db[name].find(query).sort("_id", 1):
            digest.update(json.dumps(row, sort_keys=True, default=str, ensure_ascii=False).encode())
        result[name] = digest.hexdigest()
    return result


async def main(args):
    config = dotenv_values(ROOT / "backend/.env")
    preview = dotenv_values(ROOT / "frontend/.env")["REACT_APP_BACKEND_URL"]
    url, db_name = guard(config, preview, args.preview_url)
    manifest = json.loads((ROOT / "backend/tests/fixtures/reviewed_beso_sources.json").read_text())
    from crawlers import process_crawled_products, _normalize_raw_product
    from observation_contract import expand_variants, normalize_offer, stable_id
    from own_quarantine import filter_own_rows
    from matcher import run_matching_for_all
    client = AsyncIOMotorClient(url)
    db = client[db_name]
    report = {"id": uuid.uuid4().hex, "preview": preview, "database": db_name,
              "mongo_host": urlsplit(url).hostname, "started_at": datetime.now(timezone.utc).isoformat(),
              "target_skus": sorted(TARGETS), "source_captures": [], "applied": args.apply}
    before = await fingerprints(db)
    try:
        captures = []
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as http:
            for key in ("own_litter", "hair_skin", "petsy_litter", "zarafa_litter"):
                raw, stamp, digest = await capture(http, manifest[key])
                store = await db.stores.find_one({"domain": urlsplit(raw["product_url"]).hostname}, {"_id": 0})
                if not store:
                    raise RuntimeError("Source store is not registered")
                expanded = list(expand_variants({**raw, "_currency": "SAR", "_price_basis": "storefront_inc_vat"}))
                if any(row.get("sku") not in TARGETS for row in expanded):
                    raise RuntimeError("Source includes an out-of-scope variant")
                report["source_captures"].append({"source": key, "url": raw["product_url"], "sha256": digest,
                    "observed_at": stamp.isoformat(), "raw": raw})
                captures.append((store, raw, expanded, stamp))
        if args.apply:
            for store, raw, expanded, stamp in captures:
                if store.get("is_own_store"):
                    accepted, _ = await filter_own_rows(db, store, expanded, "public_crawl", stamp, _normalize_raw_product)
                    for row in accepted:
                        norm = normalize_offer(row, store["name"])
                        if not norm["comparable"]:
                            raise RuntimeError("Quarantined source cannot update own catalogue")
                        fields = {**norm, "quantity": norm["qty"], "quantity_observed_at": stamp.isoformat(),
                                  "last_synced_at": stamp.isoformat(), "store_id": store["id"], "is_own_store": True,
                                  "offer_id": stable_id(store["id"], norm["listing_id"], norm["variant_id"]),
                                  "quarantine_active": False, "known_variant_parent": False,
                                  "price_unavailable_reason": None, "image_url": norm.get("img_url")}
                        await db.my_products.update_one({"sku": norm["sku"]}, {"$set": fields}, upsert=True)
                await process_crawled_products(db, store, [raw], stamp, tier=1, confidence=95)
            report["matching"] = await run_matching_for_all(db, only_skus=sorted(TARGETS))
        after = await fingerprints(db)
        report["unrelated_before"], report["unrelated_after"] = before, after
        report["unrelated_unchanged"] = before == after
        if before != after:
            raise RuntimeError("Out-of-scope data changed during refresh; investigate concurrent writers")
        report["status"] = "completed" if args.apply else "captured_only"
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        path = ROOT / "test_reports/targeted_preview_refresh.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        if args.apply:
            await db.preview_refresh_runs.update_one({"id": report["id"]}, {"$set": {k: v for k, v in report.items() if k != "source_captures"}}, upsert=True)
        client.close()
    print(json.dumps({k: v for k, v in report.items() if k not in ("source_captures",)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preview-url", required=True)
    asyncio.run(main(parser.parse_args()))