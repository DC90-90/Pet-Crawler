"""Full database export to object storage (14 Oct 2026).

The owner is moving Daleel off the platform. The database is reachable only
from the production deployment, and the nightly archive keeps a slim copy of
price snapshots only, so this writes every collection, every field and the
whole history as raw BSON in gzip parts, exactly as stored (types, dates and
ObjectIds intact): `gunzip -c parts... > coll.bson` restores with mongorestore
or `bson.decode_file_iter`.

    daleel/export/{run_id}/{collection}/{part:05d}.bson.gz
    daleel/export/{run_id}/manifest.json     counts, parts, indexes

Read-only on the data. Files are indexed in `export_files`; downloads are
proxied by the backend behind the super-admin check (same as the archive).
Caches, user accounts and one-time secrets are skipped.
"""
import asyncio
import gzip
import io
import json
import logging
import uuid
from datetime import datetime, timezone

from bson import json_util
from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument

import archive
import job_control

logger = logging.getLogger(__name__)

SKIP = {"cache_blobs", "dashboard_cache", "otp_requests", "zid_oauth_states",
        "job_leases", "export_runs", "export_files", "users"}
CHUNK_DOCS = 50_000
CHUNK_RAW_BYTES = 48 * 1024 * 1024
PAGE_DOCS = 5000
PAGE_RETRY_WAITS = (0, 5, 20, 60)
ID_TYPES = ("objectId", "string", "int", "long", "double", "decimal", "binData", "date", "object", "bool")
COLLECTION_ATTEMPTS = 3
LEASE_KEY = "full-export"
_tasks = {}


def _gzip(parts) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=6) as gz:
        for p in parts:
            gz.write(p)
    return buf.getvalue()


async def _put(path, blob, content_type):
    for wait in (0, 10, 60):
        await asyncio.sleep(wait)
        try:
            return await asyncio.to_thread(archive.put_object, path, blob, content_type)
        except Exception:  # noqa: BLE001 — transient storage errors are retried
            logger.warning("[Export] put %s failed", path, exc_info=True)
    raise RuntimeError(f"storage write failed: {path}")


async def _page(raw, query):
    for wait in PAGE_RETRY_WAITS:
        await asyncio.sleep(wait)
        try:
            return await raw.find(query).sort("_id", 1).limit(PAGE_DOCS).to_list(PAGE_DOCS)
        except Exception:  # noqa: BLE001 — timeouts and dropped connections are retried
            logger.warning("[Export] page read failed, retrying", exc_info=True)
    return await raw.find(query).sort("_id", 1).limit(PAGE_DOCS).to_list(PAGE_DOCS)


async def _export_collection(db, run_id, name):
    raw = db.get_collection(name, codec_options=CodecOptions(document_class=RawBSONDocument))
    files, parts, raw_bytes, docs, part = [], [], 0, 0, 0

    async def flush():
        nonlocal parts, raw_bytes, part
        blob = await asyncio.to_thread(_gzip, parts)
        path = f"{archive.APP_NAME}/export/{run_id}/{name}/{part:05d}.bson.gz"
        res = await _put(path, blob, "application/gzip")
        rec = {"run_id": run_id, "collection": name, "part": part, "path": res.get("path", path),
               "docs": len(parts), "raw_bytes": raw_bytes, "bytes": res.get("size", len(blob)),
               "created_at": datetime.now(timezone.utc)}
        await db.export_files.update_one({"run_id": run_id, "collection": name, "part": part},
                                         {"$set": rec}, upsert=True)
        files.append(rec)
        part += 1
        parts, raw_bytes = [], 0
        await db.export_runs.update_one({"id": run_id}, {"$set": {"current": name, "current_docs": docs}})

    # Short pages in _id order, not one long cursor: production's operation
    # timeout and dropped connections killed a single 8.5M-document cursor
    # three times (14 Oct 2026). A failed page is retried from the last _id.
    # `$gt` compares within one BSON type, so each _id type is paged separately.
    for id_type in ID_TYPES:
        last = None
        while True:
            query = {"_id": {"$type": id_type}} if last is None else {"_id": {"$type": id_type, "$gt": last}}
            page = await _page(raw, query)
            if not page:
                break
            for doc in page:
                parts.append(doc.raw)
                raw_bytes += len(doc.raw)
                docs += 1
                if len(parts) >= CHUNK_DOCS or raw_bytes >= CHUNK_RAW_BYTES:
                    await flush()
            last = page[-1]["_id"]
    if parts:
        await flush()
    # Parts left over from an earlier, longer attempt are no longer part of this export.
    await db.export_files.delete_many({"run_id": run_id, "collection": name, "part": {"$gte": part}})
    return {"docs": docs, "parts": part, "bytes": sum(f["bytes"] for f in files),
            "raw_bytes": sum(f["raw_bytes"] for f in files)}


async def run(db, run_id, owner, only=None):
    try:
        names = sorted(n for n in await db.list_collection_names()
                       if not n.startswith("system.") and n not in SKIP and (not only or n in only))
        await db.export_runs.update_one({"id": run_id}, {"$set": {"collections_planned": names}})
        summary = {}
        for name in names:
            info = {"count_before": await db[name].estimated_document_count()}
            try:
                info["indexes"] = json.loads(json_util.dumps(await db[name].index_information()))
            except Exception:  # noqa: BLE001
                info["indexes"] = None
            for attempt in range(1, COLLECTION_ATTEMPTS + 1):
                try:
                    info.update(await _export_collection(db, run_id, name))
                    info["count_after"] = await db[name].estimated_document_count()
                    info["status"] = "done"
                    info.pop("error", None)
                    break
                except Exception as exc:  # noqa: BLE001 — a dropped cursor restarts this collection
                    logger.warning("[Export] %s attempt %d failed", name, attempt, exc_info=True)
                    info.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]})
                    await asyncio.sleep(30)
            summary[name] = info
            await db.export_runs.update_one({"id": run_id}, {"$set": {f"collections.{name}": info}})
        manifest = {"app": archive.APP_NAME, "run_id": run_id, "format": "raw BSON, gzip parts",
                    "finished_at": datetime.now(timezone.utc).isoformat(), "collections": summary}
        blob = json.dumps(manifest, ensure_ascii=False, indent=1, default=str).encode()
        path = f"{archive.APP_NAME}/export/{run_id}/manifest.json"
        res = await _put(path, blob, "application/json")
        await db.export_files.update_one(
            {"run_id": run_id, "collection": "_manifest", "part": 0},
            {"$set": {"run_id": run_id, "collection": "_manifest", "part": 0,
                      "path": res.get("path", path), "docs": 0, "raw_bytes": len(blob),
                      "bytes": len(blob), "created_at": datetime.now(timezone.utc)}}, upsert=True)
        failed = [n for n, i in summary.items() if i.get("status") != "done"]
        await db.export_runs.update_one({"id": run_id}, {"$set": {
            "status": "partial" if failed else "done", "failed": failed, "current": None,
            "finished_at": datetime.now(timezone.utc)}})
    except Exception as exc:  # noqa: BLE001
        logger.exception("[Export] run %s failed", run_id)
        await db.export_runs.update_one({"id": run_id}, {"$set": {
            "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300],
            "finished_at": datetime.now(timezone.utc)}})
    finally:
        await job_control.release(db, LEASE_KEY, owner)
        _tasks.pop(run_id, None)


async def start(db, started_by, only=None):
    """Start an export in this process; None when one is already running."""
    owner = f"export:{uuid.uuid4().hex[:8]}"
    if not await job_control.acquire(db, LEASE_KEY, owner, hours=6):
        return None
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    await db.export_runs.insert_one({"id": run_id, "status": "running", "started_by": started_by,
                                     "only": sorted(only) if only else None,
                                     "started_at": datetime.now(timezone.utc), "collections": {}})
    _tasks[run_id] = asyncio.get_running_loop().create_task(run(db, run_id, owner, only))
    return run_id
