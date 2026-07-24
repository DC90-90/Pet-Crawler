"""Central registry of tracked stores (competitors + own store).

Single source of truth consumed by both server.py (startup) and
run_market_crawl.py (one-shot orchestrator). Add newly discovered stores to
REQUIRED_STORES — `ensure_stores(db)` is idempotent and syncs config changes
(platform, endpoints, crawl strategy, proxy routing) into the stores collection
on every startup.

Store dict fields:
  name                      display name
  domain                    bare domain (no scheme)
  platform                  "salla" | "zid" | "shopify"
  priority                  1 = crawl every 12h, 2 = every 24h
  working_endpoint          cached JSON products endpoint (speeds up Tier 1)
  use_storefront_categories True → skip Tier 1, walk category pages (stores
                            with the public products API disabled)
  tier1_only                True → never fall through to browser tiers
  is_own_store              True → synced into my_products (benchmark catalog)
  discovery                 evidence/source note for stores found via research
"""

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("store_registry")

# Stores that route Tier 1/2/3 traffic through the Saudi residential proxy
# (Webshare). Bandwidth is finite (50 GB/month) so we explicitly opt-in per
# domain rather than proxy everything.
PROXY_STORES = {"cutecat.com.sa", "cutepets.com.sa", "hamtaro.sa", "lanapets.com", "zarafaksa.com", "caty-store.com"}

REQUIRED_STORES = [
    # ── Own store (benchmark for all SKU comparisons) ──
    {"name": "Pets Houses", "domain": "pets-houses.com", "platform": "zid", "priority": 1,
     "working_endpoint": "/api/v1/products", "is_own_store": True},

    # ── Competitors (original registry) ──
    {"name": "CuteCat", "domain": "cutecat.com.sa", "platform": "salla", "priority": 1, "use_storefront_categories": True,
     "discovery": "Jul 2026: indexed URLs now show WooCommerce paths (/en/product-category/...) — may have migrated off Salla; verify on next crawl"},
    {"name": "CutePets", "domain": "cutepets.com.sa", "platform": "salla", "priority": 1, "use_storefront_categories": True},
    {"name": "Hamtaro", "domain": "hamtaro.sa", "platform": "salla", "priority": 2, "use_storefront_categories": True},
    # iter40 — platform corrected salla→zid: mowkly.com serves a Zid-style
    # /api/v1/products API (page pagination, quantity exposed) and produces
    # measurable sales signals; the old "salla" tag made the ranking's
    # "Not measurable (Salla)" label incoherent. ensure_stores syncs this
    # correction into db.stores on next boot.
    {"name": "Mowkly", "domain": "mowkly.com", "platform": "zid", "priority": 1, "working_endpoint": "/api/v1/products"},
    {"name": "Aleef", "domain": "aleef.com", "platform": "zid", "priority": 1, "working_endpoint": "/api/v1/products"},
    {"name": "Hobba", "domain": "hobbapet.com", "platform": "zid", "priority": 1, "working_endpoint": "/api/v1/products"},
    {"name": "Petsy", "domain": "petsysa.com", "platform": "zid", "priority": 2, "working_endpoint": "/api/v1/products"},
    {"name": "Panda Store", "domain": "matjarpanda.com", "platform": "zid", "priority": 1, "working_endpoint": "/api/v1/products"},
    {"name": "Caty", "domain": "caty-store.com", "platform": "salla", "priority": 2, "working_endpoint": "/en/api/v1/products"},
    {"name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla", "priority": 1, "use_storefront_categories": True},
    {"name": "Lana Pets", "domain": "lanapets.com", "platform": "salla", "priority": 1,
     "discovery": "re-verified Jul 2026: live, carries Royal Canin/Schesir/Applaws/Kit Cat"},

    # ── Competitors discovered Jul 2026 (WebSearch sweep; platform attributed
    #    from URL fingerprints — Salla /pNNN //cNNN /category/XXXX short-codes,
    #    Zid /categories/NNNN //products/slug /pages/, or *.zid.store / salla.sa
    #    hosting which is definitive). First crawl will confirm via Tier 1. ──
    {"name": "Waggy", "domain": "waggy.sa", "platform": "salla", "priority": 1,
     "discovery": "salla URL patterns /category/RQEAqo /p474879256; cats/dogs/birds/fish, Tabby installments"},
    {"name": "Cat Fans", "domain": "catfansksa.com", "platform": "salla", "priority": 1,
     "discovery": "salla URL patterns /brand-230787589 /c374241596; cat food/litter, Royal Canin"},
    {"name": "Baboon Store", "domain": "baboonstore.com", "platform": "salla", "priority": 2,
     "discovery": "salla short-code /ar/category/AzGgmq; Royal Canin cat food focus"},
    {"name": "Cat City", "domain": "catcity11.com", "platform": "salla", "priority": 2,
     "discovery": "salla product URLs /p1778290724 /p187286265; Jeddah, Royal Canin/Fancy Feast"},
    {"name": "Anyab", "domain": "anyabstore.com", "platform": "salla", "priority": 1,
     "discovery": "salla URL patterns /p1395756163; Riyadh, cats/rabbits/birds, free delivery 299+ SAR"},
    {"name": "Pet Heaven", "domain": "petheaven.sa.com", "platform": "salla", "priority": 2,
     "discovery": "salla URL patterns /p833196070 /c183764292; Farmina/Applaws cat food"},
    {"name": "Cat Park", "domain": "catpark.sa", "platform": "salla", "priority": 2,
     "discovery": "salla.sa/catpark-sa.com mirror exists; cats/birds/fish"},
    {"name": "Safari Pet Store", "domain": "safariptstore.com", "platform": "salla", "priority": 2,
     "discovery": "salla.sa-hosted mirror salla.sa/safariptstore.com; general pet supplies"},
    {"name": "Pet Req", "domain": "pet-req.com", "platform": "salla", "priority": 2,
     "discovery": "salla.sa/pet-req.com mirror + live custom domain"},
    {"name": "My Cat (Zid)", "domain": "mycat.com.sa", "platform": "zid", "priority": 1,
     "discovery": "zid URL patterns /products/ /categories/ /pages/; same-day Riyadh, free shipping 280+ SAR"},
    {"name": "My Cat (Salla)", "domain": "mycat.sa", "platform": "salla", "priority": 2,
     "discovery": "salla short-code /category/XqoeBz; sister storefront of mycat.com.sa"},
    {"name": "My Cat SA", "domain": "mycatsa.com", "platform": "zid", "priority": 2,
     "discovery": "zid-style /products /categories; third قطتي domain — dedupe with mycat.com.sa if same merchant"},
    {"name": "Refq", "domain": "refqstore.sa", "platform": "zid", "priority": 1,
     "discovery": "zid URL patterns /categories/1322935; cat food/litter, free delivery 250+ SAR"},
    {"name": "Cat Shop", "domain": "catshoop1.com", "platform": "zid", "priority": 2,
     "discovery": "zid URL pattern /en/categories/138647/رويال-كانين; cat supplies + vet products"},
    {"name": "Whiskers", "domain": "whiskers-store.com", "platform": "zid", "priority": 1,
     "discovery": "zid URL pattern /categories/320652/قطط; international-brand pet food"},
    {"name": "Snwr", "domain": "snwr.zid.store", "platform": "zid", "priority": 2,
     "discovery": "definitive: *.zid.store subdomain; cat food/litter/treats"},
    {"name": "Cat Stuff", "domain": "catstuff.zid.store", "platform": "zid", "priority": 2,
     "discovery": "definitive: *.zid.store subdomain; cat supplies + health section"},
    {"name": "FamiliPet", "domain": "familipet.zid.store", "platform": "zid", "priority": 2,
     "discovery": "definitive: *.zid.store subdomain; dogs/cats/birds"},
    {"name": "Petigo", "domain": "j3b3hi.zid.store", "platform": "zid", "priority": 2,
     "discovery": "definitive: *.zid.store subdomain; Josera/Wellness dog & cat food"},
    {"name": "Priceless Pets", "domain": "priceless-pets.store", "platform": "zid", "priority": 2,
     "discovery": "definitive: priceless-pets.zid.store mirror with same products"},
    {"name": "Tena Cattery", "domain": "tenacattery.com", "platform": "zid", "priority": 2,
     "discovery": "medium confidence: /products/<slug> + /en/products, Zid-standard titles; cat houses, Schesir/Kit Cat"},

    # ── salla.sa-hosted stores (no custom domain; base_url is a path on salla.sa).
    #    Tier 1 API paths differ on hosted stores; the waterfall will fall through
    #    to browser tiers if the JSON endpoint 404s. ──
    {"name": "Amazon Pet Shop", "domain": "salla.sa/amazon-pet-shop", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted store path"},
    {"name": "Tagareed Alrass", "domain": "salla.sa/tagareedalrass", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; birds-first, full pet range, est. 2004 Al-Rass"},
    {"name": "Natural Dry Food", "domain": "salla.sa/natural.dried.food", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; licensed Saudi cat-food factory"},
    {"name": "Cat Outlet", "domain": "salla.sa/catoutlet", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; cat dry/wet food, litter"},
    {"name": "Water Life Center", "domain": "salla.sa/waterlifecenter", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; aquatics + cat food"},
    {"name": "Grey Bird", "domain": "salla.sa/grey_bird", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; bird feed and supplies"},
    {"name": "Seven Bird", "domain": "salla.sa/seven_bird", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; birds/rodents + cat supplies"},
    {"name": "Shop Zoo", "domain": "salla.sa/shopzoo", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; full cat range"},
    {"name": "Pretty Cats", "domain": "salla.sa/pretty_catts22", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; cat supplies, cages"},
    {"name": "Catstore", "domain": "salla.sa/catstore_0", "platform": "salla", "priority": 2,
     "discovery": "definitive: salla.sa hosted; small cat store"},

    # ── Market-share context players NOT on Salla/Zid (tracked for completeness,
    #    inactive: the Salla/Zid crawl tiers don't apply; enable only after a
    #    platform-specific crawler exists) ──
    {"name": "Petzone KSA", "domain": "petzone.com", "platform": "other", "priority": 2, "is_active": False,
     "discovery": "Magento-style .html URLs; major GCC chain with Riyadh/Jeddah physical stores"},
    {"name": "Pet Arabia", "domain": "petarabia.sa", "platform": "other", "priority": 2, "is_active": False,
     "discovery": "custom platform; Bahrain-origin chain, 2-4h delivery in KSA"},
    {"name": "Beauty Pets", "domain": "beautypets.com.sa", "platform": "other", "priority": 2, "is_active": False,
     "discovery": "likely WooCommerce; cats/dogs/birds/fish + vet clinic"},
    {"name": "Sharqiya Pets", "domain": "sharqiya-pets.com", "platform": "other", "priority": 2, "is_active": False,
     "discovery": "platform undetermined; Eastern Province — probe when network allows"},
    {"name": "Pets House SA", "domain": "petshouse-sa.com", "platform": "other", "priority": 2, "is_active": False,
     "discovery": "platform undetermined; similar name to pets-houses.com — brand-confusion competitor"},
]


# ── Gated rollout (Jul 2026) ────────────────────────────────
# Newly-discovered market stores ship INACTIVE so a deploy doesn't silently
# expand the crawl surface (user decision: new stores onboard separately from
# the iter22 matcher fix). Flip to True — or activate per-store via the UI —
# when ready to onboard them.
ACTIVATE_NEW_STORES = False
LEGACY_ACTIVE_DOMAINS = {
    "pets-houses.com", "cutecat.com.sa", "cutepets.com.sa", "hamtaro.sa",
    "mowkly.com", "aleef.com", "hobbapet.com", "petsysa.com",
    "matjarpanda.com", "caty-store.com", "zarafaksa.com", "lanapets.com",
}


async def ensure_stores(db):
    """Ensure all required stores exist and have correct configuration."""
    now = datetime.now(timezone.utc)
    added = 0
    for s in REQUIRED_STORES:
        existing = await db.stores.find_one({"domain": s["domain"]})
        if not existing:
            await db.stores.insert_one({
                "id": str(uuid.uuid4()), "name": s["name"], "domain": s["domain"],
                "platform": s["platform"], "base_url": f"https://{s['domain']}",
                "crawl_frequency_hrs": 12 if s["priority"] == 1 else 24,
                "buyer_account_enc": "", "is_active": bool(s.get("is_active", True)) and (ACTIVATE_NEW_STORES or s["domain"] in LEGACY_ACTIVE_DOMAINS), "priority": s["priority"],
                "working_endpoint": s.get("working_endpoint", ""),
                "tier1_only": bool(s.get("tier1_only", False)),
                "use_storefront_categories": bool(s.get("use_storefront_categories", False)),
                "use_proxy": s["domain"] in PROXY_STORES,
                "is_own_store": bool(s.get("is_own_store", False)),
                "discovery": s.get("discovery", ""),
                "last_crawled_at": "", "created_at": now.isoformat(),
            })
            added += 1
            logger.info(f"[Stores] Added: {s['name']} ({s['domain']})")
        else:
            # Sync config drift: platform/working_endpoint/tier1_only/
            # use_storefront_categories/use_proxy/is_own_store
            updates = {}
            if existing.get("platform") != s["platform"]:
                updates["platform"] = s["platform"]
            if s.get("working_endpoint") and not existing.get("working_endpoint"):
                updates["working_endpoint"] = s["working_endpoint"]
            desired_tier1_only = bool(s.get("tier1_only", False))
            if bool(existing.get("tier1_only", False)) != desired_tier1_only:
                updates["tier1_only"] = desired_tier1_only
            desired_storefront = bool(s.get("use_storefront_categories", False))
            if bool(existing.get("use_storefront_categories", False)) != desired_storefront:
                updates["use_storefront_categories"] = desired_storefront
            desired_proxy = s["domain"] in PROXY_STORES
            if bool(existing.get("use_proxy", False)) != desired_proxy:
                updates["use_proxy"] = desired_proxy
            if s.get("is_own_store") and not existing.get("is_own_store"):
                updates["is_own_store"] = True
            if updates:
                await db.stores.update_one({"domain": s["domain"]}, {"$set": updates})
                logger.info(f"[Stores] Updated config for {s['name']}: {updates}")

    # Ensure use_proxy is also set for stores that already exist in DB but aren't
    # in REQUIRED_STORES (e.g. added externally via ingest API).
    for domain in PROXY_STORES:
        await db.stores.update_one(
            {"domain": domain, "use_proxy": {"$ne": True}},
            {"$set": {"use_proxy": True}},
        )
    # Defensive: every other store explicitly off
    await db.stores.update_many(
        {"domain": {"$nin": list(PROXY_STORES)}, "use_proxy": {"$exists": False}},
        {"$set": {"use_proxy": False}},
    )

    # Diagnostic recovery (Feb 2026) — Caty was deactivated earlier due to persistent
    # 404s. Re-enable it now that it's routed through the Saudi proxy.
    await db.stores.update_one(
        {"domain": "caty-store.com"},
        {"$set": {"is_active": True}},
    )

    # Mark pets-houses.com as own store (safety net for pre-registry DBs)
    await db.stores.update_one(
        {"domain": "pets-houses.com"},
        {"$set": {"is_own_store": True}},
    )

    # Fix Cute Pets domain (cutepets.com → cutepets.com.sa) if old entry exists
    old_cute = await db.stores.find_one({"domain": "cutepets.com"})
    new_cute = await db.stores.find_one({"domain": "cutepets.com.sa"})
    if old_cute and new_cute:
        await db.stores.delete_one({"domain": "cutepets.com"})
        logger.info("[Stores] Removed old cutepets.com entry (replaced by cutepets.com.sa)")
    elif old_cute and not new_cute:
        await db.stores.update_one({"domain": "cutepets.com"}, {"$set": {"domain": "cutepets.com.sa", "platform": "salla", "base_url": "https://cutepets.com.sa", "working_endpoint": "/en/api/v1/products"}})
        logger.info("[Stores] Updated cutepets.com → cutepets.com.sa")

    if added:
        logger.info(f"[Stores] Added {added} new stores")
    return added
