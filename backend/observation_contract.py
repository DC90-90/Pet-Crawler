"""Evidence contract v2. Unknown is None; discovery keys never carry prices."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

VERSION = 2
# Only bases whose VAT treatment is evidenced are comparable. An assumed or
# unknown tax basis is kept on the row for audit but never priced (finding F10).
TRUSTED_PRICE_BASES = {"storefront_inc_vat", "merchant_computed_inc_vat", "merchant_non_taxable"}


def decimal_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        value = value.get("amount")
    text = str(value).strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,"))
    text = text.replace(",", "")
    try:
        number = Decimal(text)
        return number if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def money(value):
    number = decimal_number(value)
    if number is None or number > Decimal('1000000000000'):
        return None
    try:
        return float(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def observed_int(value):
    number = decimal_number(value)
    return int(number) if number is not None and number == number.to_integral_value() else None


def gtin(value):
    text = str(value or "").strip()
    # A lost leading zero can be restored; suffixes must never alias a carton to a unit.
    if not re.fullmatch(r"[0-9]{8,14}", text):
        return None
    text = text.zfill(14)
    check = sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(reversed(text[:-1])))
    return text if (10 - check % 10) % 10 == int(text[-1]) and int(text) != 0 else None


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def is_variant_parent(raw):
    return (any(raw.get(k) in (True, 1, "true", "1") for k in ("has_options", "has_variants", "is_variable", "known_variant_parent"))
            or bool(raw.get("variants") or raw.get("skus")) or raw.get("type") == "variable")


OPTIONS_UNPRICED_CONFIDENCE = 80     # below the 85 the price cohort requires


def options_same_price(raw):
    """A Salla listing flagged `has_options` with no option rows (`skus`) and no
    "starting from" price: the options do not change the listed price as far
    as the store's API shows (Zarafa: 48 of 375 listings, all with
    starting_price null, 19 Oct 2026). It is catalogued as one offer — name,
    stock, sold counter — but kept out of price comparisons (confidence below
    the cohort's 85), because an option could still be another pack size."""
    if str(raw.get("_variant_id") or raw.get("variant_id") or "root") != "root" or raw.get("_unresolved_parent"):
        return False
    if raw.get("skus") or raw.get("variants") or "starting_price" not in raw:
        return False
    return raw.get("has_options") in (True, 1, "true", "1") and not money(raw.get("starting_price"))


def unresolved_identity(raw):
    if raw.get("_unresolved_parent"):
        return True
    variant = str(raw.get("_variant_id") or raw.get("variant_id") or "root")
    return is_variant_parent(raw) and variant == "root"


def expand_variants(raw):
    """Never inherit parent inventory, price, barcode, or SKU into a child offer."""
    variants = raw.get("skus") or raw.get("variants")
    if not isinstance(variants, list) or not variants:
        yield {**raw,
               "_listing_id": str(raw.get('_listing_id') or raw.get('listing_id') or raw.get("id") or raw.get("sku") or ""),
               "_variant_id": str(raw.get('_variant_id') or raw.get('variant_id') or 'root'),
               # A same-price options listing is its own single offer (19 Oct 2026:
               # marking it here kept every one of them quarantined).
               "_unresolved_parent": unresolved_identity(raw) and not options_same_price(raw)}
        return
    if any(not isinstance(v, dict) or not (v.get("id") or v.get("variant_id")
           or (v.get("sku") and v.get("sku") != raw.get("sku")) or gtin(v.get("barcode"))) for v in variants):
        yield {**raw, "_listing_id": str(raw.get("id") or raw.get("listing_id") or raw.get("sku") or ""),
               "_variant_id": "root", "_unresolved_parent": True}
        return
    identities = [str(v.get("id") or v.get("variant_id") or stable_id(v.get("sku"), v.get("barcode"), v.get("attributes") or v.get("options") or [])) for v in variants]
    if len(set(identities)) != len(identities):
        yield {**raw, "_listing_id": str(raw.get("id") or raw.get("listing_id") or raw.get("sku") or ""),
               "_variant_id": "root", "_unresolved_parent": True}
        return
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        attrs = variant.get("attributes") or variant.get("options") or []
        vid = str(variant.get("id") or variant.get('variant_id') or
                  stable_id(variant.get('sku'), variant.get('barcode'), attrs))
        # Tax status is a listing-level attribute in Zid, so children inherit
        # it; inventory, price, barcode and SKU never are.
        row = {k: raw[k] for k in ("name", "title", "images", "image", "urls", "url", "html_url", "product_url", "categories", "brand", "currency", "_currency", "_price_basis", "is_taxable", "taxable") if k in raw}
        row.update(variant)
        row.update(_listing_id=str(raw.get("id") or raw.get("listing_id") or raw.get("sku") or stable_id(raw.get("name"))),
                   _variant_id=vid, attributes=attrs, _parent_sku=raw.get("sku"), _resolved_child=True)
        if not row.get("sku"):
            row["sku"] = f"variant:{row['_listing_id']}:{vid}"
        # Explicit child descriptors take priority. Parent-only names remain evidence, not identity.
        yield row


def image_url(raw):
    """First product image as a URL string.

    Salla: images [{url}] / [{src}]; Zid storefront: images [{id, image:
    {full_size, large, medium, small, thumbnail}}] (verified on mowkly.com,
    16 Oct 2026 — before this, every Zid store saved no image); merchant
    rows built by the crawler carry `img_url`."""
    images = raw.get("images") or raw.get("image") or raw.get("main_image") or []
    first = images[0] if isinstance(images, list) and images else images
    if isinstance(first, dict):
        nested = first.get("image") if isinstance(first.get("image"), dict) else {}
        first = (first.get("url") or first.get("src") or first.get("origin")
                 or nested.get("medium") or nested.get("large") or nested.get("full_size") or nested.get("small")
                 or (first.get("image") if isinstance(first.get("image"), str) else ""))
    if isinstance(first, str) and first.startswith(("http://", "https://", "//")):
        return first
    fallback = raw.get("img_url")
    return fallback if isinstance(fallback, str) and fallback.startswith(("http://", "https://", "//")) else ""


def normalize_offer(raw, store_name):
    """Normalize one specific offer, NOT a multi-variant listing."""
    listing = str(raw.get("_listing_id") or raw.get("id") or raw.get("sku") or "")
    variant = str(raw.get("_variant_id") or "root")
    sku = str(raw.get("sku") or raw.get("mpn") or f"listing:{listing}").strip()
    price_keys = ("effective_price", "sale_price", "special_price", "price")
    currencies = {str(v.get("currency")).upper() for k in price_keys for v in [raw.get(k)] if isinstance(v, dict) and v.get("currency")}
    currency = str(raw.get("currency") or raw.get("_currency") or next(iter(currencies), "unknown")).upper()
    values = {k: money(raw.get(k)) for k in price_keys}
    base = values["price"]
    effective = values["effective_price"]
    sale = values["sale_price"] or values["special_price"]
    price = effective if effective and effective > 0 else sale if sale and (not base or sale < base) else base
    regular = money(raw.get("regular_price"))
    original = max([v for v in (price, base, regular) if v is not None], default=None)
    ambiguous = bool(raw.get("price_from") or raw.get("is_from_price") or raw.get("member_price") or raw.get("coupon_required"))
    reasons = []
    if price is None or price <= 0:
        reasons.append("price_missing_or_invalid")
    if currency != "SAR" or any(c != currency for c in currencies):
        reasons.append("currency_unverified_or_unsupported")
    if ambiguous:
        reasons.append("conditional_or_from_price")
    same_price_options = options_same_price(raw)
    if raw.get("skus") or raw.get("variants") or (unresolved_identity(raw) and not same_price_options):
        reasons.append("unresolved_parent_variants")
        price = None
    basis = raw.get("_price_basis") or raw.get("price_basis") or "unknown"
    if basis not in TRUSTED_PRICE_BASES:
        reasons.append("tax_basis_unverified")
    qty = next((observed_int(raw[k]) for k in ("quantity", "stock_quantity", "qty", "qty_available") if raw.get(k) is not None), None)
    unlimited = bool(raw.get("unlimited_quantity") or raw.get("is_infinite"))
    if unlimited:
        qty = None
    explicit = next((raw[k] for k in ("in_stock", "is_available", "availability") if raw.get(k) is not None), None)
    hidden = str(raw.get("status", "")).lower() in ("draft", "hidden", "deleted", "archived")
    available = True if explicit in (True, "yes", "available", "in_stock") else False if explicit in (False, "no", "unavailable", "out_of_stock", "sold_out") else None
    if hidden:
        available = False
    elif available is None:
        available = True if unlimited else qty > 0 if qty is not None else None
    if "unresolved_parent_variants" in reasons:
        qty, available = None, None
    sold_raw = next((raw[k] for k in ("sold_quantity", "sold_count", "sales_count", "sold_products_count", "total_sold", "orders_count") if raw.get(k) is not None), None)
    sold = observed_int(sold_raw)
    capped = bool(raw.get("sold_count_capped")) or bool(re.search(r"\+|أكثر|اكثر|more than", str(sold_raw), re.I))
    barcode = next((str(raw[k]).strip() for k in ("barcode", "gtin", "ean", "upc", "sku") if gtin(raw.get(k))), "")
    image = image_url(raw)
    urls = raw.get("urls") or {}
    url = (urls.get("customer") or urls.get("store")) if isinstance(urls, dict) else None
    name = raw.get("name") or raw.get("title") or ""
    if isinstance(name, dict):
        name = name.get("ar") or name.get("en") or ""
    brand = raw.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    # A key brand named in the product name wins over the store's tag
    # (Kit Cat items tagged "Almo" — key_brands.py, 21 Oct 2026).
    from key_brands import brand_in_name
    key_brand = brand_in_name(name)
    return dict(sku=sku, barcode=barcode, name_ar=str(name), name_en=str(name),
                brand=key_brand or (str(brand) if brand else None),
                brand_source="key_brand_name" if key_brand else "store_supplied" if brand else "unresolved",
                listing_id=listing, variant_id=variant, attributes=raw.get("attributes") or [],
                price=price, original_price=original, sale_price=price if price and original and price < original else None,
                price_decimal=str(Decimal(str(price))) if price is not None else None,
                currency=currency, price_basis=basis, price_kind="effective", qty=qty, in_stock=available,
                sold_count=sold, sold_count_cumulative=sold, sold_count_capped=capped,
                sold_count_observed=sold is not None, quantity_observed=qty is not None,
                img_url=image, product_url=url or raw.get("html_url") or raw.get("product_url") or raw.get("url") or "",
                variant_skus=[sku], variant_barcodes=[barcode] if barcode else [],
                observation_version=VERSION, is_synthetic=False, data_origin="store_observation",
                comparable=not reasons, quarantine_reasons=reasons, present_on_store=not hidden,
                options_unpriced=same_price_options)


# Observation contract v2 went live on 2026-10-07 (commit 558861e); nothing
# written before that date carries observation_version 2, so every v2 read can
# stop at this bound instead of scanning months of legacy snapshots. On
# production (8.45M snapshots) the unbounded 90-day cohort scan starved the
# database until even the crawl's own writes timed out (11 Oct 2026).
OBSERVATIONS_V2_SINCE_DEFAULT = "2026-10-07T00:00:00+00:00"


def v2_since():
    raw = os.environ.get("OBSERVATIONS_V2_SINCE") or OBSERVATIONS_V2_SINCE_DEFAULT
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        ts = datetime.fromisoformat(OBSERVATIONS_V2_SINCE_DEFAULT)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def since_bound(since):
    """Lower crawl-date bound for reads that only use v2 observations."""
    if since is None:
        return v2_since()
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return max(since, v2_since())
