"""iter78 — nightly PRICE HISTORY ARCHIVE to Emergent object storage.

The client asked to "keep the history entirely for each store and for each
product". MongoDB holds the working set; this writes an immutable copy of every
crawl day to object storage so the record survives a database prune, a bad
migration or a re-crawl that overwrites a snapshot.

One night = one folder, never overwritten:

    daleel/archive/{ksa_date}/snapshots/{store_id}.jsonl.gz   one file per store
    daleel/archive/{ksa_date}/rollups/sku_sales_daily.jsonl.gz
    daleel/archive/{ksa_date}/rollups/daily_ledger.jsonl.gz
    daleel/archive/{ksa_date}/manifest.json                   row counts + sizes

Every file is also recorded in `archive_files`, which is what the admin panel
lists from — the storage API has no delete and no presigned URLs, so Mongo is the
index and downloads are proxied by the backend.
"""
import asyncio
import gzip
import io
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests

from ledger import KSA_TZ, ksa_day_str

logger = logging.getLogger(__name__)

APP_NAME = "daleel"
# `or`, not a default= argument: the platform sets this to "" when it has no value.
STORAGE_BASE = ((os.environ.get("INTEGRATION_PROXY_URL") or "").strip()
                or "https://integrations.emergentagent.com")
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"

SNAPSHOT_FIELDS = ("sku", "barcode", "store_id", "store_name", "product_name",
                   "price", "sale_price", "original_price", "discount_pct",
                   "qty_available", "in_stock", "product_url", "image_url",
                   "confidence_score", "match_method", "crawled_at")

storage_key = None


def _emergent_key():
    return os.environ.get("EMERGENT_LLM_KEY")


def init_storage(force: bool = False):
    """Mint (once) the session-scoped storage key. force=True replaces a dead one."""
    global storage_key
    if storage_key and not force:
        return storage_key
    resp = requests.post(f"{STORAGE_URL}/init",
                         json={"emergent_key": _emergent_key()}, timeout=30)
    resp.raise_for_status()
    storage_key = resp.json()["storage_key"]
    return storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    url = f"{STORAGE_URL}/objects/{path}"
    resp = requests.put(url, headers={"X-Storage-Key": key,
                                      "Content-Type": content_type},
                        data=data, timeout=180)
    if resp.status_code == 404:
        # 404 here means the storage key went inactive, not "no such object" —
        # a bare init_storage() would hand back the same dead key.
        resp = requests.put(url, headers={"X-Storage-Key": init_storage(force=True),
                                          "Content-Type": content_type},
                            data=data, timeout=180)
    resp.raise_for_status()
    return resp.json()


def get_object(path: str):
    key = init_storage()
    url = f"{STORAGE_URL}/objects/{path}"
    resp = requests.get(url, headers={"X-Storage-Key": key}, timeout=120)
    if resp.status_code == 404:
        resp = requests.get(url, headers={"X-Storage-Key": init_storage(force=True)},
                            timeout=120)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


# ── helpers ──────────────────────────────────────────────────────────────────
def _jsonl_gz(rows) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for r in rows:
            gz.write((json.dumps(r, ensure_ascii=False, default=str) + "\n").encode())
    return buf.getvalue()


def ksa_day_bounds_utc(date_str: str):
    start = datetime.fromisoformat(date_str).replace(tzinfo=KSA_TZ)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def previous_ksa_day(now=None) -> str:
    now = now or datetime.now(timezone.utc)
    return ksa_day_str(now - timedelta(days=1))


def _slim(doc):
    doc.pop("_id", None)
    return {k: doc[k] for k in SNAPSHOT_FIELDS if k in doc}


async def archive_day(db, date_str: str, force: bool = False) -> dict:
    """Write one KSA day to object storage. Idempotent: an already-archived day
    is skipped unless `force`, because the storage API overwrites silently."""
    if not _emergent_key():
        return {"date": date_str, "status": "skipped", "reason": "no_emergent_key"}
    existing = await db.archive_files.count_documents({"date": date_str, "is_deleted": False})
    if existing and not force:
        return {"date": date_str, "status": "skipped", "reason": "already_archived",
                "files": existing}

    start_utc, end_utc = ksa_day_bounds_utc(date_str)
    prefix = f"{APP_NAME}/archive/{date_str}"
    written, total_rows, total_bytes = [], 0, 0

    stores = await db.stores.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    for st in stores:
        rows = [_slim(d) async for d in db.product_snapshots.find(
            {"store_id": st["id"], "crawled_at": {"$gte": start_utc, "$lt": end_utc}})]
        if not rows:
            continue
        blob = _jsonl_gz(rows)
        path = f"{prefix}/snapshots/{st['id']}.jsonl.gz"
        res = await asyncio.to_thread(put_object, path, blob, "application/gzip")
        written.append({"kind": "snapshots", "store_id": st["id"],
                        "store_name": st.get("name", ""), "path": res.get("path", path),
                        "rows": len(rows), "bytes": res.get("size", len(blob))})
        total_rows += len(rows)
        total_bytes += res.get("size", len(blob))

    for kind, coll, query in (
        ("sku_sales_daily", "sku_sales_daily", {"date": date_str}),
        ("daily_ledger", "daily_ledger", {"ksa_date": date_str}),
    ):
        rows = []
        async for d in db[coll].find(query):
            d.pop("_id", None)
            rows.append(d)
        if not rows:
            continue
        blob = _jsonl_gz(rows)
        path = f"{prefix}/rollups/{kind}.jsonl.gz"
        res = await asyncio.to_thread(put_object, path, blob, "application/gzip")
        written.append({"kind": kind, "store_id": None, "store_name": "",
                        "path": res.get("path", path), "rows": len(rows),
                        "bytes": res.get("size", len(blob))})
        total_rows += len(rows)
        total_bytes += res.get("size", len(blob))

    if not written:
        return {"date": date_str, "status": "empty", "files": 0, "rows": 0}

    manifest = {"app": APP_NAME, "date": date_str, "files": written,
                "rows": total_rows, "bytes": total_bytes,
                "created_at": datetime.now(timezone.utc).isoformat()}
    m_blob = json.dumps(manifest, ensure_ascii=False, indent=1).encode()
    m_res = await asyncio.to_thread(put_object, f"{prefix}/manifest.json",
                                    m_blob, "application/json")
    written.append({"kind": "manifest", "store_id": None, "store_name": "",
                    "path": m_res.get("path", f"{prefix}/manifest.json"),
                    # rows=0: the manifest is metadata, and this column is summed
                    # into the panel's "rows archived" total.
                    "rows": 0, "bytes": m_res.get("size", len(m_blob))})

    if force:
        await db.archive_files.update_many({"date": date_str}, {"$set": {"is_deleted": True}})
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.archive_files.insert_many([{
        "id": str(uuid.uuid4()), "date": date_str, "created_at": now_iso,
        "content_type": "application/json" if w["kind"] == "manifest" else "application/gzip",
        "is_deleted": False, **w,
    } for w in written])
    logger.info("[Archive] %s — %d files, %d rows, %d bytes",
                date_str, len(written), total_rows, total_bytes)
    return {"date": date_str, "status": "archived", "files": len(written),
            "rows": total_rows, "bytes": total_bytes}


async def archive_status(db) -> dict:
    days = await db.archive_files.aggregate([
        {"$match": {"is_deleted": False}},
        {"$group": {"_id": "$date", "files": {"$sum": 1},
                    "rows": {"$sum": "$rows"}, "bytes": {"$sum": "$bytes"},
                    "created_at": {"$max": "$created_at"}}},
        {"$sort": {"_id": -1}}, {"$limit": 400},
    ]).to_list(400)
    rows = [{"date": d["_id"], "files": d["files"], "rows": d["rows"],
             "bytes": d["bytes"], "created_at": d.get("created_at")} for d in days]
    return {
        "configured": bool(_emergent_key()),
        "storage_url": STORAGE_URL,
        "days": rows,
        "total_days": len(rows),
        "total_files": sum(r["files"] for r in rows),
        "total_rows": sum(r["rows"] for r in rows),
        "total_bytes": sum(r["bytes"] for r in rows),
        "latest_day": rows[0]["date"] if rows else None,
    }
