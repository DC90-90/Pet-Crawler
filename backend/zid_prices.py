"""Approved price changes to the own Zid store (17 Oct 2026).

The owner approves one recommended shelf price at a time; this module turns it
into the Zid merchant price and updates the product through the Zid Merchant
API, then reads the product back to confirm. Every attempt — sent, confirmed or
refused — is recorded in `price_changes` with who approved it.

Zid merchant prices exclude VAT for a taxable product (the sync grosses them by
1.15 to the shelf price, crawlers.py "merchant_computed_inc_vat"), so the
shelf price is divided by 1.15 before sending. A product on sale has its sale
price changed and its list price kept, unless the new price is at or above the
list price, in which case the sale ends and the list price is set.

Write access: the same Manager headers as the catalogue read, plus the partner
OAuth pair when the store has authorised it. Whether the store token alone may
write is Zid's decision; a refusal is returned to the owner as-is.
"""
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx

from pricing_advisor import vat_factor

logger = logging.getLogger("zid_prices")
API = "https://api.zid.sa/v1"
MAX_CHANGE_PCT = 40.0          # a bigger single move is refused: likely a wrong price


def product_id(mp):
    variant = mp.get("variant_id")
    return variant if variant and variant != "root" else (mp.get("listing_id") or mp.get("zid_id"))


def plan(mp, shelf_price):
    """What would be sent for this shelf price, or the reason it cannot be."""
    pid = product_id(mp)
    factor = vat_factor(mp)
    current = mp.get("sale_price") or mp.get("price")
    list_shelf = mp.get("original_price") or mp.get("price")
    if not pid:
        return {"ok": False, "reason": "no Zid product id for this product"}
    if not shelf_price or shelf_price <= 0:
        return {"ok": False, "reason": "invalid price"}
    if current and abs(shelf_price - current) / current * 100 > MAX_CHANGE_PCT:
        return {"ok": False, "reason": f"change above {MAX_CHANGE_PCT:g}% in one step"}
    merchant = round(shelf_price / factor, 2)
    on_sale = bool(mp.get("sale_price")) and list_shelf and mp["sale_price"] < list_shelf
    if on_sale and shelf_price < list_shelf:
        body = {"sale_price": merchant}
    else:
        body = {"price": merchant, "sale_price": None}
    return {"ok": True, "product_id": pid, "body": body, "shelf_price": shelf_price,
            "vat_factor": factor, "current_shelf_price": current}


async def _headers(db):
    token, store_id = os.environ.get("ZID_API_TOKEN"), os.environ.get("ZID_STORE_ID")
    if not token or not store_id:
        return None, "missing_token"
    headers = {"Access-Token": token, "Store-Id": store_id, "Role": "Manager",
               "Accept-Language": "en", "Accept": "application/json", "Content-Type": "application/json"}
    try:
        import zid_oauth
        creds = await zid_oauth.credentials(db)
    except Exception:  # noqa: BLE001
        creds = None
    if creds:
        headers["Authorization"] = f"Bearer {creds['authorization']}"
        headers["X-Manager-Token"] = creds["access_token"]
    return headers, "partner_oauth" if creds else "store_token_only"


async def apply(db, sku, shelf_price, user_email, http=None):
    mp = await db.my_products.find_one({"sku": sku}, {"_id": 0})
    if not mp:
        return {"ok": False, "status": "not_found", "reason": "product not in my catalogue"}
    p = plan(mp, shelf_price)
    record = {"_id": uuid.uuid4().hex, "sku": sku, "name_ar": mp.get("name_ar"), "requested_shelf_price": shelf_price,
              "previous_shelf_price": p.get("current_shelf_price") or mp.get("price"), "approved_by": user_email,
              "at": datetime.now(timezone.utc), "plan": {k: v for k, v in p.items() if k != "ok"}}
    if not p["ok"]:
        record.update(status="refused_locally", reason=p["reason"])
        await db.price_changes.insert_one(record)
        return {"ok": False, "status": "refused", "reason": p["reason"]}
    headers, auth = await _headers(db)
    if headers is None:
        record.update(status="not_configured", reason="Zid API token missing")
        await db.price_changes.insert_one(record)
        return {"ok": False, "status": "not_configured", "reason": "Zid API token missing on the server"}
    own = http is None
    http = http or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await http.patch(f"{API}/products/{p['product_id']}/", json=p["body"], headers=headers)
        record.update(auth=auth, http_status=resp.status_code)
        if resp.status_code >= 300:
            record.update(status="refused_by_zid", reason=resp.text[:300])
            await db.price_changes.insert_one(record)
            return {"ok": False, "status": "refused_by_zid", "http_status": resp.status_code,
                    "reason": "Zid refused the change" + (" (no write permission for this token)" if resp.status_code in (401, 403) else ""),
                    "detail": resp.text[:300]}
        check = await http.get(f"{API}/products/{p['product_id']}/", headers=headers)
        body = check.json() if check.status_code == 200 else {}
        body = body.get("product") if isinstance(body.get("product"), dict) else body
        sent = p["body"].get("sale_price") if "sale_price" in p["body"] and p["body"]["sale_price"] else p["body"]["price"]
        seen = body.get("sale_price") if p["body"].get("sale_price") else body.get("price")
        try:
            confirmed = seen is not None and abs(float(seen) - float(sent)) < 0.01
        except (TypeError, ValueError):
            confirmed = False
        record.update(status="confirmed" if confirmed else "sent_unconfirmed", zid_price_after=seen)
        await db.price_changes.insert_one(record)
        if confirmed:
            update = {"last_price_change_at": record["at"], "pending_shelf_price": shelf_price}
            await db.my_products.update_one({"sku": sku}, {"$set": update})
        return {"ok": True, "status": record["status"], "merchant_price": sent, "shelf_price": shelf_price}
    except httpx.HTTPError as exc:
        record.update(status="error", reason=f"{type(exc).__name__}: {str(exc)[:200]}")
        await db.price_changes.insert_one(record)
        return {"ok": False, "status": "error", "reason": "could not reach Zid"}
    finally:
        if own:
            await http.aclose()


async def history(db, limit=100):
    return await db.price_changes.find({}, {"_id": 0}).sort("at", -1).to_list(limit)
