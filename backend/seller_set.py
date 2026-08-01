"""iter60 — the full seller set behind "Stores Carrying".

The product-detail seller list was built as::

    db.product_snapshots.find({"sku": sku, "crawled_at": {"$gte": now - 30d}})

which quietly imposes two filters that hide sellers we have already proven
carry the product:

1. **exact SKU string equality.** ``product_matches`` — the output of the whole
   matching engine — was never read by this endpoint. A competitor linked to our
   SKU by barcode, or by any key other than a byte-identical SKU string, exists
   in the database, passed every matcher guard, and is still absent from the
   table. That is a post-match filter: the match is made and then discarded at
   render time.
2. **a hard 30-day cliff.** A store crawled 31 days ago does not appear as a
   stale seller — it disappears, and the client reads "nobody else carries this"
   from what is actually "we have not looked recently".

Both are fixed here by widening what is *fetched*, not by weakening what is
*trusted*. Rows admitted through ``product_matches`` are re-checked against the
iter51–53 pack guard before they are shown, so this cannot re-open the
pack-collision defects: the goal is to stop hiding correct matches, not to start
admitting wrong ones.

Everything in this module is pure and DB-free so the seller-set rules can be
tested without a Mongo round trip.
"""
from datetime import datetime, timezone, timedelta

from matcher import _pack_compatible

# How far back a seller row may be sourced from. This is NOT a freshness
# promise — it is the point past which a price is too old to be worth showing at
# all. Rows older than STALE_AFTER_DAYS are shown WITH a label, never dropped.
SELLER_LOOKBACK_DAYS = 180

# Beyond this age a row is labelled stale. It still appears, still counts as a
# seller, and still carries its price — the client needs to know WHO carries the
# product, and "Zarafa, 118 SAR as of 12 Jun" is strictly more useful than a
# blank row.
STALE_AFTER_DAYS = 7

# Upper bound on snapshot rows pulled for one product across the whole lookback.
# The query sorts DESCENDING and is reversed in Python so that hitting this cap
# drops the OLDEST rows; an ascending sort with a cap would silently discard the
# recent prices — the only ones that matter.
SELLER_SNAPSHOT_CAP = 8000


def alias_map_from_matches(matches, sku):
    """{store_id: {competitor_sku, ...}} for every store matched to `sku`.

    `matches` are raw ``product_matches`` docs. Matching is hub-and-spoke — every
    row is ``{my_sku, competitor_sku, competitor_store_id}`` and anchors on one
    of OUR SKUs — so a product's full seller set is the union of:

      * rows whose ``my_sku`` is this SKU (we are the hub), and
      * rows whose ``competitor_sku`` is this SKU (someone else's row for the
        same product; the caller resolves those hubs and passes their rows in
        too).

    Both directions land here and are merged per store.
    """
    out = {}
    for m in matches or []:
        sid = m.get("competitor_store_id")
        csku = m.get("competitor_sku")
        if not sid or not csku:
            continue
        out.setdefault(sid, set()).add(str(csku))
    return out


def hub_skus_from_matches(matches, sku):
    """Our SKUs that some store links to `sku` — the reverse hop.

    Opening the panel on a competitor's SKU should still show every seller of the
    product, not just the one store whose SKU string was clicked.
    """
    return sorted({
        str(m["my_sku"]) for m in matches or []
        if m.get("my_sku") and str(m.get("competitor_sku") or "") == str(sku)
    })


def snapshot_or_clauses(sku_keys, alias_by_store):
    """Mongo ``$or`` clauses selecting the direct SKU keys plus each store's
    matched SKU.

    `sku_keys` is the SKU itself, or the set of SKUs that reach this product
    without a match (itself plus any reverse-hop hubs).

    Alias SKUs are scoped to the store that owns them. An unscoped
    ``{"sku": {"$in": [...]}}`` would let a generic competitor SKU string (say
    "1234") pull in unrelated products from every other store — widening the key
    space is exactly how the iter50-53 false lows happened, so it is done
    narrowly.
    """
    keys = {str(sku_keys)} if isinstance(sku_keys, str) else {str(k) for k in sku_keys}
    base = sorted(keys)
    clauses = [{"sku": base[0]} if len(base) == 1 else {"sku": {"$in": base}}]
    for sid in sorted(alias_by_store):
        extra = sorted(s for s in alias_by_store[sid] if s not in keys)
        if extra:
            clauses.append({"store_id": sid, "sku": {"$in": extra}})
    return clauses


def pack_guard_ok(hub_name, comp_name):
    """(ok, reason) — re-apply the iter51/52 pack guard to a matched row.

    ``product_matches`` rows written before those guards existed are still in the
    collection, and this endpoint is now reading them for the first time. Showing
    a single 400g tin as a seller of a 24-tin carton would be a wrong match, and
    requirement 3 of this fix is that wrong matches stay out.

    Exact-SKU rows are NOT passed through here: they are the pre-existing
    behaviour of the endpoint, and re-filtering them would remove sellers the
    client can see today.
    """
    if not hub_name or not comp_name:
        return True, None                       # no evidence either way — keep
    if _pack_compatible(hub_name, comp_name):
        return True, None
    return False, "pack_mismatch"


def _as_aware(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def freshness_labels(crawled_at, now=None, stale_after_days=STALE_AFTER_DAYS):
    """Labels that let a stale row be SHOWN rather than dropped."""
    now = now or datetime.now(timezone.utc)
    ts = _as_aware(crawled_at)
    if ts is None:
        return {"days_since_crawl": None, "is_stale": True,
                "price_as_of": None, "data_status": "unknown"}
    age = max(0, (now - ts).days)
    stale = age >= stale_after_days
    return {
        "days_since_crawl": age,
        "is_stale": stale,
        "price_as_of": ts.date().isoformat(),
        "data_status": "stale" if stale else "live",
    }


def stock_labels(stock_signal, in_stock, qty_available):
    """OOS is a fact about the seller, not a reason to hide the seller."""
    oos = (stock_signal == "OOS") or (in_stock is False)
    if not oos and in_stock is None and (qty_available or 0) <= 0 and stock_signal in (None, "OOS"):
        oos = True
    return {"stock_status": "OOS" if oos else "IN_STOCK", "is_oos": oos}


def latest_per_store(rows):
    """Last snapshot per store from a list already ordered oldest → newest."""
    out = {}
    for r in rows:
        sid = r.get("store_id")
        if sid:
            out[sid] = r
    return out


def seller_summary(store_prices, excluded=0):
    """Counts that make the widened set auditable in the payload itself."""
    total = len(store_prices)
    return {
        "total": total,
        "live": sum(1 for r in store_prices if r.get("data_status") == "live"),
        "stale": sum(1 for r in store_prices if r.get("data_status") != "live"),
        "oos": sum(1 for r in store_prices if r.get("is_oos")),
        "via_sku": sum(1 for r in store_prices if r.get("match_source") == "sku"),
        "via_match": sum(1 for r in store_prices if r.get("match_source") == "matched"),
        "excluded_wrong_match": excluded,
    }
