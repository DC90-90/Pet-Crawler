"""Real order ingestion from the Zid Merchant Orders API (Feb 2026).

Why this exists: "My Revenue" used to be *estimated* from own-store stock
depletion between crawl snapshots, which structurally captures only ~55-70%
of actual sales (untracked-inventory SKUs, same-interval sell+restock, price
drift, shipping excluded). Zid's Orders API has the exact ledger, so own-store
revenue/units are now computed from real orders stored in the
`own_store_orders` collection. Competitor stores keep the estimation path
untouched — there is no ledger for them.

Field extraction is deliberately defensive (same policy as
_extract_zid_sold_count): Zid has shifted field names/shapes across API
versions, and this module must degrade to "skipped + logged", never to a
wrong number.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger("zid_orders")

ZID_ORDERS_ENDPOINT = "https://api.zid.sa/v1/managers/store/orders"

# Zid order lifecycle statuses that must NOT count toward revenue. Normalized
# to lowercase; matched against both status code and status name.
EXCLUDED_ORDER_STATUSES = {
    "cancelled", "canceled", "refunded", "reversed", "reverse_in_progress",
    "rejected", "returned", "draft", "payment_failed", "expired", "deleted",
}

# The merchant's Zid dashboard buckets days in store-local time (Asia/Riyadh).
# For "on this calendar day" queries to reconcile with that dashboard, order
# day-windows are interpreted in KSA time, then converted to UTC for storage
# comparison. Rolling windows (7D/30D/...) are unaffected.
KSA_TZ = timezone(timedelta(hours=3))

# Incremental syncs re-pull this many recent days on every run so late status
# changes (cancellation, refund, reversal) get picked up after first ingest.
INCREMENTAL_REFRESH_DAYS = 14

_TOTAL_FIELD_CANDIDATES = ("order_total", "grand_total", "total", "totals")
_DATE_FIELD_CANDIDATES = ("created_at", "issue_date", "created_at_str", "date", "updated_at")
# Line items that are expansions of a bundle parent must not be counted a
# second time — the parent line already carries the sale.
_BUNDLE_CHILD_MARKERS = ("parent_id", "parent_product_id", "parent_order_product_id", "bundle_id", "bundle_parent_id")


def _coerce_money(val):
    """Coerce Zid money shapes (12.5 | "12.50" | "1,234.50 SAR" | {"value": ...}) to float."""
    if val is None:
        return None
    if isinstance(val, dict):
        for k in ("value", "amount", "total"):
            if k in val:
                return _coerce_money(val[k])
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned) if cleaned not in ("", "-", ".", "-.") else None
    except ValueError:
        return None


def parse_order_datetime(val):
    """Parse Zid order timestamps to an aware UTC datetime.

    Zid returns store-local (KSA) wall-clock strings without an offset in most
    payloads, so naive values are interpreted as Asia/Riyadh and converted.
    """
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, str) and val.strip():
        s = val.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KSA_TZ)
    return dt.astimezone(timezone.utc)


def _extract_status(raw: dict) -> str:
    status = raw.get("order_status") or raw.get("status") or ""
    if isinstance(status, dict):
        status = status.get("code") or status.get("slug") or status.get("name") or ""
    return str(status).strip().lower().replace(" ", "_")


def _is_bundle_child_line(line: dict) -> bool:
    return any(line.get(marker) for marker in _BUNDLE_CHILD_MARKERS)


def normalize_zid_order(raw: dict):
    """Reshape one raw Zid order payload into the own_store_orders document.

    Returns None when the payload has no usable id (never guess an identity).

    Bundle correctness: revenue comes from the ORDER total, which Zid computes
    once per order regardless of how bundle lines are expanded — so revenue
    can never double-count a bundle. Units skip bundle *child* expansion lines
    (parent-line markers) so a "Bundle of 5" order counts as 1 bundle unit,
    not 1 + 5 components.
    """
    order_id = raw.get("id") or raw.get("order_id") or raw.get("code")
    if not order_id:
        return None

    created_at = None
    for f in _DATE_FIELD_CANDIDATES:
        created_at = parse_order_datetime(raw.get(f))
        if created_at:
            break

    total = None
    for f in _TOTAL_FIELD_CANDIDATES:
        total = _coerce_money(raw.get(f))
        if total is not None:
            break

    status = _extract_status(raw)
    excluded = status in EXCLUDED_ORDER_STATUSES

    items, units = [], 0
    for line in (raw.get("products") or raw.get("items") or []):
        if not isinstance(line, dict):
            continue
        if _is_bundle_child_line(line):
            continue  # already represented by its bundle parent line
        qty = line.get("quantity") or line.get("qty") or 0
        try:
            qty = int(float(qty))
        except (ValueError, TypeError):
            qty = 0
        unit_price = _coerce_money(line.get("price"))
        line_total = _coerce_money(line.get("total"))
        if line_total is None and unit_price is not None:
            line_total = round(unit_price * qty, 2)
        sku = str(line.get("sku") or "").strip()
        name = line.get("name")
        if isinstance(name, dict):
            name = name.get("ar") or name.get("en") or ""
        items.append({
            "sku": sku,
            "name": str(name or ""),
            "qty": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "is_bundle": bool(line.get("is_bundle") or line.get("bundle_products")),
        })
        units += max(0, qty)

    return {
        "order_id": str(order_id),
        "code": str(raw.get("code") or order_id),
        "status": status,
        "excluded": excluded,
        "created_at": created_at,
        "currency": str(raw.get("currency_code") or raw.get("currency") or "SAR"),
        "total": total if total is not None else 0.0,
        "units": units,
        "items": items,
        "source": "zid_orders_api",
    }


def aggregate_orders(order_docs):
    """Pure aggregation over normalized order docs (excluded ones skipped).

    Returns {revenue, orders_count, units, by_sku: {sku: {units, revenue}}}.
    Revenue = Σ order totals (what the Zid dashboard reports, shipping/fees
    included). by_sku uses line totals for product-level attribution.
    """
    revenue, units, count = 0.0, 0, 0
    by_sku = {}
    for o in order_docs:
        if o.get("excluded"):
            continue
        count += 1
        revenue += float(o.get("total") or 0)
        units += int(o.get("units") or 0)
        for it in (o.get("items") or []):
            sku = it.get("sku")
            if not sku:
                continue
            agg = by_sku.setdefault(sku, {"units": 0, "revenue": 0.0})
            agg["units"] += max(0, int(it.get("qty") or 0))
            agg["revenue"] += float(it.get("line_total") or 0)
    return {
        "revenue": round(revenue, 2),
        "orders_count": count,
        "units": units,
        "by_sku": {k: {"units": v["units"], "revenue": round(v["revenue"], 2)} for k, v in by_sku.items()},
    }


def orders_day_window(on_date: str):
    """UTC [start, end) for one KSA calendar day, matching the Zid dashboard."""
    start_local = datetime.fromisoformat(on_date).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=KSA_TZ)
    return start_local.astimezone(timezone.utc), (start_local + timedelta(days=1)).astimezone(timezone.utc)


async def sync_own_store_orders(db, full_backfill=False, max_pages=400, per_page=100):
    """Pull orders from the Zid Merchant API into db.own_store_orders (idempotent
    upsert by order_id).

    Incremental mode (default) walks newest-first and stops once a full page is
    older than INCREMENTAL_REFRESH_DAYS — recent orders are re-upserted every
    run so late cancellations/refunds correct history. full_backfill walks all
    pages until the API runs out (bounded by max_pages).
    """
    token = os.environ.get("ZID_API_TOKEN")
    store_id = os.environ.get("ZID_STORE_ID")
    if not token or not store_id:
        return {"status": "missing_token", "upserted": 0, "pages": 0}

    # iter75 — Zid splits its API across TWO credentials, and the orders route
    # is on the other side of the split from the catalogue route:
    #   * `/v1/products/`             → the store's Access-Token works (verified,
    #                                   200 with 2233 products).
    #   * `/v1/managers/store/orders` → requires a PARTNER-APP OAuth access token
    #                                   in `Authorization: Bearer` *alongside*
    #                                   the store token in `X-Manager-Token`.
    # Probed all five header permutations with the store token alone: every one
    # answers 401 "Unauthenticated". So the missing piece is a credential, not
    # code — and the moment `ZID_OAUTH_TOKEN` is present we send the dual-header
    # form Zid documents, with no further changes needed.
    oauth_token = (os.environ.get("ZID_OAUTH_TOKEN") or "").strip()
    headers = {
        "Access-Token": token,
        "Store-Id": store_id,
        "Role": "Manager",
        "Accept-Language": "en",
        "Accept": "application/json",
    }
    if oauth_token:
        headers["Authorization"] = f"Bearer {oauth_token}"
        headers["X-Manager-Token"] = token
    refresh_floor = datetime.now(timezone.utc) - timedelta(days=INCREMENTAL_REFRESH_DAYS)
    upserted, skipped, pages = 0, 0, 0
    oldest_seen = None

    try:
        async with httpx.AsyncClient(timeout=45.0) as http:
            for page in range(1, max_pages + 1):
                resp = await http.get(
                    ZID_ORDERS_ENDPOINT,
                    params={"page": page, "per_page": per_page},
                    headers=headers,
                )
                if resp.status_code in (401, 403):
                    logger.error(
                        "[Orders] auth rejected status=%s oauth_token_present=%s. "
                        "Zid's orders route needs a PARTNER-APP OAuth access "
                        "token (Authorization: Bearer) alongside the store token "
                        "(X-Manager-Token) — set ZID_OAUTH_TOKEN in the "
                        "environment. The catalogue route is unaffected.",
                        resp.status_code, bool(oauth_token))
                    return {"status": "auth_failed", "upserted": upserted,
                            "pages": pages,
                            "needs": None if oauth_token else "ZID_OAUTH_TOKEN",
                            "hint": "Zid Partner dashboard → your app → OAuth "
                                    "access token for store " + str(store_id)}
                resp.raise_for_status()
                payload = resp.json()
                rows = payload.get("orders") or payload.get("results") or payload.get("data") or []
                if not isinstance(rows, list) or not rows:
                    break
                pages += 1

                page_all_old = True
                for raw in rows:
                    doc = normalize_zid_order(raw)
                    if doc is None:
                        skipped += 1
                        continue
                    if doc["created_at"] is None:
                        # Undatable orders can't participate in windowed KPIs.
                        skipped += 1
                        logger.warning(f"[Orders] order {doc['order_id']} has no parseable date — skipped")
                        continue
                    doc["synced_at"] = datetime.now(timezone.utc)
                    await db.own_store_orders.update_one(
                        {"order_id": doc["order_id"]}, {"$set": doc}, upsert=True
                    )
                    upserted += 1
                    if oldest_seen is None or doc["created_at"] < oldest_seen:
                        oldest_seen = doc["created_at"]
                    if doc["created_at"] >= refresh_floor:
                        page_all_old = False

                if not full_backfill and page_all_old:
                    break  # incremental: everything on this page predates the refresh window
                await asyncio.sleep(0.15)
    except httpx.HTTPError as e:
        logger.error(f"[Orders] network error after {upserted} orders: {e}")
        return {"status": "partial" if upserted else "network_failed",
                "upserted": upserted, "skipped": skipped, "pages": pages,
                "oldest_seen": oldest_seen.isoformat() if oldest_seen else None}

    logger.info(f"[Orders] synced {upserted} orders across {pages} page(s) "
                f"(full_backfill={full_backfill}, oldest={oldest_seen})")
    return {"status": "ok", "upserted": upserted, "skipped": skipped, "pages": pages,
            "oldest_seen": oldest_seen.isoformat() if oldest_seen else None}
