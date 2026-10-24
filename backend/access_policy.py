"""Server-side permissions. Unknown endpoints fail closed for non-administrators.

23 Oct 2026 — one permission per menu page. The old keys (price_intel,
insights, scanner, discounts, stores) named pages merged into Pricing and
Competitors in Oct 2026, and newer pages (Pricing recommendations, Key
brands, Data quality, Reports) had no rule at all, so a user with every box
ticked was refused them. Old keys are still read and translated.
"""
from fastapi import HTTPException

# The menu, in order; the Users page shows these.
PAGES = ["overview", "my_products", "pricing", "market_share", "key_brands", "opportunities",
         "competitors", "reports", "data_quality", "alerts", "import", "settings"]

# What each retired key opened, in today's pages.
LEGACY = {
    "my_products": {"overview", "my_products", "reports"},
    "price_intel": {"pricing", "opportunities"},
    "insights": {"pricing", "opportunities"},
    "scanner": {"pricing"},
    "discounts": {"pricing"},
    "market_share": {"market_share", "key_brands", "opportunities"},
    "stores": {"competitors", "data_quality"},
}


def effective_pages(pages):
    """Today's pages for a stored list that may hold retired keys."""
    out = set()
    for p in pages or []:
        out |= LEGACY.get(p, {p} if p in PAGES else set())
    return [p for p in PAGES if p in out]


# Lookups every page uses (store logos and names, freshness, one product's
# detail): open to any user who may see at least one page.
SHARED = ("/api/stores/brands", "/api/comparison-stores", "/api/data-freshness", "/api/products/", "/api/jobs/",
          "/api/decisions")     # filters itself by page

# First matching prefix decides; specific prefixes come before general ones.
READ_RULES = (
    ("/api/insights", {"overview", "pricing", "opportunities", "market_share"}),
    ("/api/market-share", {"market_share", "overview", "opportunities", "key_brands"}),
    ("/api/price-intel", {"pricing", "overview", "opportunities", "data_quality", "my_products"}),
    ("/api/pricing", {"pricing"}),
    ("/api/scanner", {"pricing"}),
    ("/api/discounts", {"pricing"}),
    ("/api/promotions", {"pricing"}),
    ("/api/stock", {"opportunities", "pricing"}),
    ("/api/brands/key", {"key_brands"}),
    ("/api/data-quality", {"data_quality"}),
    ("/api/reports", {"reports"}),
    ("/api/digests", {"reports", "overview"}),
    ("/api/notifications/settings", {"reports"}),
    ("/api/notifications", {"alerts"}),
    ("/api/alerts", {"alerts", "my_products"}),
    ("/api/stores", {"competitors", "data_quality", "overview", "my_products", "pricing"}),
    ("/api/baseline", {"overview", "competitors", "market_share"}),
    ("/api/my-products", {"my_products", "pricing"}),
    ("/api/my-skus", {"my_products", "pricing"}),
    ("/api/products", {"my_products", "pricing", "alerts", "key_brands", "market_share", "opportunities"}),
    ("/api/export/products", {"my_products"}),
    ("/api/filters", {"my_products", "pricing"}),
    ("/api/saved-filters", {"my_products", "pricing"}),
    ("/api/import/status", {"import", "my_products"}),
)


def enforce(user, path, method):
    if path in ("/api/auth/me", "/api/auth/logout", "/api/protected"):
        return
    if user.get("role") == "super_admin":
        return
    if path.startswith("/api/admin") or path.startswith("/api/tier4") or path.startswith("/api/scheduler"):
        raise HTTPException(403, "Administrator access required")
    pages = set(effective_pages(user.get("allowed_pages")))
    if method not in ("GET", "HEAD"):
        # Only user-owned alert/filter mutations are available to page readers.
        own_page = "alerts" if path.startswith("/api/alerts") else "my_products" if path.startswith(("/api/filters", "/api/saved-filters")) else None
        if own_page and own_page in pages:
            return
        raise HTTPException(403, "Administrator access required for this operation")
    if pages and path.startswith(SHARED):
        return
    for prefix, required in READ_RULES:
        if path.startswith(prefix):
            if pages & required:
                return
            break
    raise HTTPException(403, "Page permission required")
