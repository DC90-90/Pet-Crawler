"""Stock display contract: historical quantities are never current inventory."""
from datetime import datetime, timezone, timedelta
from price_cohort import aware
from observation_contract import observed_int, unresolved_identity


def own_stock(product, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = aware(product.get("quantity_observed_at") or product.get("last_synced_at"))
    reason = ("removed_from_store" if product.get("present_on_store") is False else
              "unresolved_parent_variants" if unresolved_identity(product) else
              product.get("price_unavailable_reason") or
              ("quarantined" if product.get("quarantine_active") else None))
    if not reason and (stamp is None or stamp > now + timedelta(minutes=5) or now-stamp >= timedelta(days=7)):
        reason = "stale_or_unknown_observation"
    qty = observed_int(product.get("quantity"))
    available = product.get("in_stock") if isinstance(product.get("in_stock"), bool) else None
    if not reason and available is None:
        reason = "stock_unknown"
    historical = product.get("historical_quantity")
    historical_at = product.get("historical_quantity_at")
    if reason and qty is not None:
        historical, historical_at = qty, stamp
    return {"quantity": qty if not reason else None, "in_stock": available if not reason else None,
            "stock_status": "unavailable" if reason else "in_stock" if available else "out_of_stock",
            "stock_unavailable_reason": reason, "stock_observed_at": stamp if not reason else None,
            "historical_quantity": historical, "historical_quantity_at": historical_at}


def retained_history(product):
    """Copy last observed values before quarantining; never update observation time."""
    result = {}
    for field, target in (("quantity", "historical_quantity"), ("price", "historical_price")):
        if product.get(field) is not None:
            result[target] = product[field]
            result[target+"_at"] = product.get("quantity_observed_at" if field == "quantity" else "last_synced_at") or product.get("last_synced_at")
    return result