"""Evidence contract v2. Unknown is None; discovery keys never carry prices."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

VERSION = 2
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
               "_unresolved_parent": unresolved_identity(raw)}
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
        row = {k: raw[k] for k in ("name", "title", "images", "image", "urls", "url", "html_url", "product_url", "categories", "brand", "currency", "_currency", "_price_basis") if k in raw}
        row.update(variant)
        row.update(_listing_id=str(raw.get("id") or raw.get("listing_id") or raw.get("sku") or stable_id(raw.get("name"))),
                   _variant_id=vid, attributes=attrs, _parent_sku=raw.get("sku"), _resolved_child=True)
        if not row.get("sku"):
            row["sku"] = f"variant:{row['_listing_id']}:{vid}"
        # Explicit child descriptors take priority. Parent-only names remain evidence, not identity.
        yield row


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
    if raw.get("skus") or raw.get("variants") or unresolved_identity(raw):
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
    images = raw.get("images") or raw.get("image") or []
    image = images[0] if isinstance(images, list) and images else images if isinstance(images, (dict, str)) else {}
    image = (image.get("url") or image.get("src") or image.get("origin") or "") if isinstance(image, dict) else image
    urls = raw.get("urls") or {}
    url = (urls.get("customer") or urls.get("store")) if isinstance(urls, dict) else None
    name = raw.get("name") or raw.get("title") or ""
    if isinstance(name, dict):
        name = name.get("ar") or name.get("en") or ""
    brand = raw.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    return dict(sku=sku, barcode=barcode, name_ar=str(name), name_en=str(name),
                brand=str(brand) if brand else None, brand_source="store_supplied" if brand else "unresolved",
                listing_id=listing, variant_id=variant, attributes=raw.get("attributes") or [],
                price=price, original_price=original, sale_price=price if price and original and price < original else None,
                price_decimal=str(Decimal(str(price))) if price is not None else None,
                currency=currency, price_basis=basis, price_kind="effective", qty=qty, in_stock=available,
                sold_count=sold, sold_count_cumulative=sold, sold_count_capped=capped,
                sold_count_observed=sold is not None, quantity_observed=qty is not None,
                img_url=image, product_url=url or raw.get("html_url") or raw.get("product_url") or raw.get("url") or "",
                variant_skus=[sku], variant_barcodes=[barcode] if barcode else [],
                observation_version=VERSION, is_synthetic=False, data_origin="store_observation",
                comparable=not reasons, quarantine_reasons=reasons, present_on_store=not hidden)
