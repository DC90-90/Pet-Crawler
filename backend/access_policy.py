"""Server-side permissions. Unknown endpoints fail closed for non-administrators."""
from fastapi import HTTPException

READ_RULES = (
    ("/api/comparison-stores", {"market_share", "price_intel", "insights", "scanner"}),
    ("/api/market-share", {"market_share"}),
    ("/api/price-intel", {"price_intel", "insights"}),
    ("/api/insights", {"price_intel", "insights"}),
    ("/api/scanner", {"scanner"}),
    ("/api/discounts", {"discounts"}),
    ("/api/alerts", {"alerts"}),
    ("/api/notifications", {"alerts"}),
    ("/api/stores", {"stores", "my_products", "price_intel", "insights", "scanner", "discounts"}),
    ("/api/my-products", {"my_products"}),
    ("/api/products", {"my_products", "price_intel", "insights", "scanner", "discounts", "alerts"}),
    ("/api/my-skus", {"my_products", "price_intel", "insights", "scanner", "discounts"}),
    ("/api/export/products", {"my_products"}),
    ("/api/import/status", {"import", "my_products"}),
    ("/api/jobs/", {"import", "my_products", "stores"}),
    ("/api/digests", {"insights", "price_intel"}),
    ("/api/filters", {"my_products", "price_intel", "insights"}),
    ("/api/saved-filters", {"my_products", "price_intel", "insights"}),
    ("/api/data-freshness", {"my_products", "price_intel", "insights", "scanner", "discounts", "stores", "market_share"}),
)


def enforce(user, path, method):
    if path in ("/api/auth/me", "/api/auth/logout", "/api/protected"):
        return
    if user.get("role") == "super_admin":
        return
    if path.startswith("/api/admin") or path.startswith("/api/tier4") or path.startswith("/api/scheduler"):
        raise HTTPException(403, "Administrator access required")
    pages = set(user.get("allowed_pages") or [])
    if method not in ("GET", "HEAD"):
        # Only user-owned alert/filter mutations are available to page readers.
        own_page = "alerts" if path.startswith("/api/alerts") else "my_products" if path.startswith(("/api/filters", "/api/saved-filters")) else None
        if own_page and own_page in pages:
            return
        raise HTTPException(403, "Administrator access required for this operation")
    for prefix, required in READ_RULES:
        if path.startswith(prefix):
            if pages & required:
                return
            break
    raise HTTPException(403, "Page permission required")