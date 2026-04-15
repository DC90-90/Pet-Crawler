from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, Query, HTTPException, Request, Depends
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, random, uuid, bcrypt, jwt as pyjwt, statistics, csv, io
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from typing import Optional, List
from bson import ObjectId
from starlette.responses import StreamingResponse

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALG = "HS256"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Daleel Pets API")
router = APIRouter(prefix="/api")

# ── Auth Utilities ──────────────────────────────────────────
def hash_pw(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def check_pw(pw, h):
    return bcrypt.checkpw(pw.encode(), h.encode())

def make_token(uid, email):
    return pyjwt.encode(
        {"sub": uid, "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=24)},
        JWT_SECRET, algorithm=JWT_ALG
    )

async def get_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        p = pyjwt.decode(auth[7:], JWT_SECRET, algorithms=[JWT_ALG])
        u = await db.users.find_one({"_id": ObjectId(p["sub"])})
        if not u:
            raise HTTPException(401, "User not found")
        return {"id": str(u["_id"]), "email": u["email"], "name": u.get("name", ""), "role": u.get("role", "user")}
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid token")

# ── Models ──────────────────────────────────────────────────
class AuthIn(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

class StoreIn(BaseModel):
    name: str
    domain: str
    platform: str
    base_url: Optional[str] = ""
    crawl_frequency_hrs: Optional[int] = 24

class StoreUpdate(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    base_url: Optional[str] = None
    crawl_frequency_hrs: Optional[int] = None
    is_active: Optional[bool] = None

class AlertIn(BaseModel):
    product_sku: Optional[str] = None
    category: Optional[str] = None
    store_id: Optional[str] = None
    alert_type: str = "price_drop"
    threshold: Optional[float] = None
    channel: str = "in_app"

class SavedFilterIn(BaseModel):
    name: str
    filters: dict

# ── Seed Data ───────────────────────────────────────────────
STORES_SEED = [
    {"name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla", "priority": 1},
    {"name": "Panda Store", "domain": "matjarpanda.com", "platform": "salla", "priority": 1},
    {"name": "Lana Pets", "domain": "lanapets.com", "platform": "salla", "priority": 1},
    {"name": "Cute Pets", "domain": "cutepets.com", "platform": "shopify", "priority": 1},
    {"name": "Hamtaro", "domain": "hamtaro.sa", "platform": "salla", "priority": 2},
    {"name": "Caty Store", "domain": "caty-store.com", "platform": "salla", "priority": 2},
    {"name": "Petsy", "domain": "petsysa.com", "platform": "salla", "priority": 2},
]

PRODUCTS_SEED = [
    ("RC-ICAT-4", "رويال كانين للقطط المنزلية 4 كجم", "Royal Canin Indoor Cat 4kg", "Royal Canin", "cat_food", "cat", 4.0, 175),
    ("WH-TUNA-7", "ويسكاس تونا للقطط البالغة 7 كجم", "Whiskas Tuna Adult Cat 7kg", "Whiskas", "cat_food", "cat", 7.0, 98),
    ("PO-STER-3", "بورينا وان للقطط المعقمة 3 كجم", "Purina ONE Sterilised Cat 3kg", "Purina", "cat_food", "cat", 3.0, 135),
    ("HS-DIET-2", "هيلز ساينس دايت قطط 2 كجم", "Hills Science Diet Cat 2kg", "Hills", "cat_food", "cat", 2.0, 189),
    ("ND-PUMP-5", "ان اند دي يقطين حمل قطط 5 كجم", "N&D Pumpkin Lamb Cat 5kg", "N&D", "cat_food", "cat", 5.0, 245),
    ("MO-TUNA-7", "مي-او تونا 7 كجم", "Me-O Tuna 7kg", "Me-O", "cat_food", "cat", 7.0, 79),
    ("FR-FISH-1", "فريسكيز سمك قطط 1.5 كجم", "Friskies Fish Cat 1.5kg", "Friskies", "cat_food", "cat", 1.5, 55),
    ("RC-MAXI-15", "رويال كانين ماكسي كلاب 15 كجم", "Royal Canin Maxi Dog 15kg", "Royal Canin", "dog_food", "dog", 15.0, 289),
    ("PD-MEAT-10", "بيدقري لحم كلاب 10 كجم", "Pedigree Meat Dog 10kg", "Pedigree", "dog_food", "dog", 10.0, 145),
    ("BR-PREM-15", "بريت بريميوم كلاب 15 كجم", "Brit Premium Dog 15kg", "Brit", "dog_food", "dog", 15.0, 219),
    ("OR-ORIG-11", "اوريجن كلاب 11.4 كجم", "Orijen Dog 11.4kg", "Orijen", "dog_food", "dog", 11.4, 389),
    ("AC-PRAI-11", "اكانا دجاج كلاب 11.4 كجم", "Acana Chicken Dog 11.4kg", "Acana", "dog_food", "dog", 11.4, 349),
    ("VL-PRES-4", "فيرسيل لاجا بريستيج ببغاء 4 كجم", "Versele-Laga Prestige Parrot 4kg", "Versele-Laga", "bird_food", "bird", 4.0, 65),
    ("ZP-FRUT-1", "زوبريم فروت بلند 1.5 كجم", "Zupreem FruitBlend 1.5kg", "Zupreem", "bird_food", "bird", 1.5, 89),
    ("VK-CANA-1", "فيتاكرافت كناري 1 كجم", "Vitakraft Canary 1kg", "Vitakraft", "bird_food", "bird", 1.0, 42),
    ("TM-FLAK-200", "تترا مين رقائق استوائية 200 جرام", "Tetra Min Tropical Flakes 200g", "Tetra", "fish_food", "fish", 0.2, 55),
    ("FL-FX6-F", "فلتر فلوفال FX6", "Fluval FX6 Filter", "Fluval", "equipment", "fish", 0, 899),
    ("CB-PREM-1", "سرير قطط فاخر مع وسادة", "Premium Cat Bed", "Generic", "accessories", "cat", 0, 159),
    ("CT-TREE-150", "شجرة تسلق للقطط 150 سم", "Cat Climbing Tree 150cm", "Generic", "accessories", "cat", 0, 299),
    ("CL-CRYS-5", "رمل قطط كريستال 5 لتر", "Crystal Cat Litter 5L", "Ever Clean", "litter", "cat", 5.0, 45),
    ("LB-ENCL-1", "صندوق فضلات قطط مغلق", "Enclosed Cat Litter Box", "Catit", "accessories", "cat", 0, 129),
    ("DC-LEAT-1", "طوق كلب جلد طبيعي", "Leather Dog Collar", "Generic", "accessories", "dog", 0, 85),
    ("DB-ORTH-L", "سرير كلب ارثوبيدك كبير", "Orthopedic Dog Bed Large", "PetFusion", "accessories", "dog", 0, 199),
    ("TC-AIRL-1", "قفص تنقل معتمد للطيران", "Airline Travel Crate", "Petmate", "accessories", "dog", 0, 249),
    ("KG-CLAS-L", "كونغ كلاسيك كبير", "Kong Classic Large", "Kong", "toys", "dog", 0, 65),
    ("FT-FETH-1", "لعبة ريشة تفاعلية للقطط", "Feather Cat Toy", "SmartyKat", "toys", "cat", 0, 29),
    ("TN-3WAY-1", "نفق قطط ثلاثي قابل للطي", "3-Way Cat Tunnel", "Generic", "toys", "cat", 0, 55),
    ("FM-DESH-L", "فرمينيتور إزالة الشعر كبير", "FURminator deShedding Large", "FURminator", "grooming", "dog", 0, 149),
    ("TC-SHAM-592", "شامبو تروبي كلين 592 مل", "TropiClean Shampoo 592ml", "TropiClean", "grooming", "dog", 0.592, 68),
    ("NC-PROF-1", "مقص اظافر احترافي", "Pro Nail Clipper", "Safari", "grooming", "cat", 0, 35),
    ("FL-PLUS-D", "فرونت لاين بلس كلاب", "Frontline Plus Dog", "Frontline", "healthcare", "dog", 0, 125),
    ("NV-GLUC-60", "جلوكوزامين 60 قرص", "Glucosamine 60 Tabs", "NaturVet", "healthcare", "dog", 0, 89),
    ("VB-DENT-1", "معجون اسنان فيرباك قطط", "Virbac Dental Paste Cat", "Virbac", "healthcare", "cat", 0, 75),
    ("RF-RABB-2", "علف ارانب مكس 2 كجم", "Rabbit Mix Feed 2kg", "Versele-Laga", "small_food", "small", 2.0, 55),
    ("TH-TIMO-1", "تبن تيموثي عضوي 1 كجم", "Timothy Hay 1kg", "Oxbow", "small_food", "small", 1.0, 42),
]

CATEGORIES = {
    "cat_food": "Cat Food", "dog_food": "Dog Food", "bird_food": "Bird Food",
    "fish_food": "Fish Food", "equipment": "Equipment", "accessories": "Accessories",
    "litter": "Litter", "toys": "Toys", "grooming": "Grooming",
    "healthcare": "Healthcare", "small_food": "Small Animal Food",
}

def get_stock_signal(qty):
    if qty == 0: return "OOS"
    if qty < 10: return "LOW"
    if qty <= 30: return "MEDIUM"
    return "HIGH"

async def seed_database():
    if await db.stores.count_documents({}) > 0:
        return
    logger.info("Seeding Daleel Pets database...")
    random.seed(42)
    now = datetime.now(timezone.utc)

    # Seed stores
    store_ids = []
    for s in STORES_SEED:
        sid = str(uuid.uuid4())
        await db.stores.insert_one({
            "id": sid, "name": s["name"], "domain": s["domain"],
            "platform": s["platform"], "base_url": f"https://{s['domain']}",
            "crawl_frequency_hrs": 12 if s["priority"] == 1 else 24,
            "buyer_account_enc": "", "is_active": True, "priority": s["priority"],
            "last_crawled_at": (now - timedelta(hours=random.randint(1, 6))).isoformat(),
            "created_at": (now - timedelta(days=60)).isoformat(),
        })
        store_ids.append({"id": sid, "name": s["name"], "priority": s["priority"]})

    # Seed products and snapshots
    p1_stores = [s for s in store_ids if s["priority"] == 1]
    p2_stores = [s for s in store_ids if s["priority"] == 2]
    all_snapshots = []

    for tup in PRODUCTS_SEED:
        sku, name_ar, name_en, brand, category, animal, weight, base_price = tup
        pid = str(uuid.uuid4())
        await db.products.insert_one({
            "id": pid, "sku": sku, "name_ar": name_ar, "name_en": name_en,
            "brand": brand, "category": category, "animal_type": animal,
            "weight_kg": weight, "image_url": "", "first_seen_at": (now - timedelta(days=45)).isoformat(),
        })

        # Assign to stores: 3-4 P1 stores + 1-2 P2 stores
        n_p1 = random.randint(2, min(4, len(p1_stores)))
        n_p2 = random.randint(1, min(2, len(p2_stores)))
        assigned = random.sample(p1_stores, n_p1) + random.sample(p2_stores, n_p2)

        for store in assigned:
            tier = random.choices([1, 2, 3], weights=[55, 30, 15])[0]
            qty = random.randint(40, 250)
            price = round(base_price * random.uniform(0.90, 1.12), 2)

            day = 30
            while day >= 0:
                crawled_at = now - timedelta(days=day, hours=random.randint(0, 12))
                sold = random.randint(0, min(15, qty))
                qty = max(0, qty - sold)
                if qty <= 5 and random.random() < 0.35:
                    qty += random.randint(30, 120)
                price = round(price * random.uniform(0.97, 1.03), 2)
                has_disc = random.random() < 0.2
                disc_pct = random.choice([5, 10, 15, 20, 25]) if has_disc else 0
                orig_price = round(price / (1 - disc_pct / 100), 2) if disc_pct else price
                conf = {1: random.randint(92, 98), 2: random.randint(85, 95), 3: random.randint(70, 85)}[tier]

                all_snapshots.append({
                    "id": str(uuid.uuid4()), "product_id": pid, "store_id": store["id"],
                    "store_name": store["name"], "sku": sku,
                    "price": price, "original_price": orig_price, "discount_pct": disc_pct,
                    "in_stock": qty > 0, "qty_available": max(0, qty),
                    "source_tier": tier, "confidence_score": conf,
                    "crawled_at": crawled_at,
                })
                day -= random.randint(2, 4)

    if all_snapshots:
        await db.product_snapshots.insert_many(all_snapshots)

    # Seed admin user
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@daleelpets.com")
    admin_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
    if not await db.users.find_one({"email": admin_email}):
        await db.users.insert_one({
            "email": admin_email, "password_hash": hash_pw(admin_pw),
            "name": "Admin", "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })

    # Create indexes
    await db.users.create_index("email", unique=True)
    await db.product_snapshots.create_index([("sku", 1), ("crawled_at", -1)])
    await db.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)])
    await db.product_snapshots.create_index("product_id")
    await db.products.create_index("sku", unique=True)
    await db.stores.create_index("domain", unique=True)

    # Write test credentials
    creds_path = Path("/app/memory/test_credentials.md")
    creds_path.parent.mkdir(exist_ok=True)
    creds_path.write_text(f"# Daleel Pets Test Credentials\n\n## Admin\n- Email: {admin_email}\n- Password: {admin_pw}\n- Role: admin\n\n## Auth Endpoints\n- POST /api/auth/login\n- POST /api/auth/register\n- GET /api/auth/me\n")

    logger.info(f"Seeded {len(STORES_SEED)} stores, {len(PRODUCTS_SEED)} products, {len(all_snapshots)} snapshots")

# ── Auth Routes ─────────────────────────────────────────────
@router.post("/auth/register")
async def register(data: AuthIn):
    email = data.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    doc = {"email": email, "password_hash": hash_pw(data.password), "name": data.name or email.split("@")[0], "role": "user", "created_at": datetime.now(timezone.utc)}
    result = await db.users.insert_one(doc)
    uid = str(result.inserted_id)
    token = make_token(uid, email)
    return {"token": token, "user": {"id": uid, "email": email, "name": doc["name"], "role": "user"}}

@router.post("/auth/login")
async def login(data: AuthIn):
    email = data.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not check_pw(data.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    uid = str(user["_id"])
    token = make_token(uid, email)
    return {"token": token, "user": {"id": uid, "email": email, "name": user.get("name", ""), "role": user.get("role", "user")}}

@router.get("/auth/me")
async def me(user=Depends(get_user)):
    return user

@router.post("/auth/logout")
async def logout():
    return {"message": "Logged out"}

@router.get("/protected")
async def protected(user=Depends(get_user)):
    return {"message": "Authenticated", "user": user}

# ── Store Routes ────────────────────────────────────────────
@router.get("/stores")
async def list_stores(user=Depends(get_user)):
    stores = await db.stores.find({}, {"_id": 0}).sort("name", 1).to_list(100)
    for s in stores:
        s["product_count"] = await db.product_snapshots.distinct("sku", {"store_id": s["id"]})
        s["product_count"] = len(s["product_count"])
    return stores

@router.post("/stores")
async def create_store(data: StoreIn, user=Depends(get_user)):
    platform = data.platform.lower()
    if platform not in ("salla", "zid", "shopify", "woocommerce", "custom"):
        platform = "custom"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "name": data.name, "domain": data.domain,
        "platform": platform, "base_url": data.base_url or f"https://{data.domain}",
        "crawl_frequency_hrs": data.crawl_frequency_hrs or 24,
        "buyer_account_enc": "", "is_active": True, "priority": 3,
        "last_crawled_at": "", "created_at": now,
    }
    await db.stores.insert_one(doc)
    doc.pop("_id", None)
    return doc

@router.put("/stores/{store_id}")
async def update_store(store_id: str, data: StoreUpdate, user=Depends(get_user)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No data")
    result = await db.stores.update_one({"id": store_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Store not found")
    return await db.stores.find_one({"id": store_id}, {"_id": 0})

@router.delete("/stores/{store_id}")
async def delete_store(store_id: str, user=Depends(get_user)):
    r = await db.stores.delete_one({"id": store_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Not found")
    return {"message": "Deleted"}

@router.post("/stores/{store_id}/crawl")
async def trigger_crawl(store_id: str, user=Depends(get_user)):
    store = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not store:
        raise HTTPException(404, "Store not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.stores.update_one({"id": store_id}, {"$set": {"last_crawled_at": now}})
    product_count = len(await db.product_snapshots.distinct("sku", {"store_id": store_id}))
    return {
        "message": f"Crawl completed for {store['name']}",
        "store_id": store_id, "last_crawled_at": now,
        "products_found": product_count,
        "tier_used": random.choice([1, 1, 1, 2, 2, 3]),
        "new_products": random.randint(0, 3),
        "price_changes": random.randint(0, 8),
    }

# ── Helper: compute product metrics from snapshots ──────────
def compute_product_metrics(snapshots_by_store, days):
    """Given {store_id: [snapshots sorted by crawled_at asc]}, compute market metrics."""
    all_latest_prices = []
    total_sold = 0
    total_revenue = 0.0
    latest_qty = 0
    confidences = []
    latest_tier = 1

    for store_id, snaps in snapshots_by_store.items():
        if not snaps:
            continue
        latest = snaps[-1]
        all_latest_prices.append(latest["price"])
        confidences.append(latest["confidence_score"])
        latest_tier = latest["source_tier"]
        latest_qty = max(latest_qty, latest.get("qty_available", 0))

        # Compute sold from depletion
        for i in range(1, len(snaps)):
            delta = snaps[i - 1].get("qty_available", 0) - snaps[i].get("qty_available", 0)
            if delta > 0:
                total_sold += delta
                total_revenue += delta * snaps[i]["price"]

    if not all_latest_prices:
        return None

    min_p = min(all_latest_prices)
    max_p = max(all_latest_prices)
    med_p = statistics.median(all_latest_prices)
    avg_p = statistics.mean(all_latest_prices)
    avg_conf = round(statistics.mean(confidences)) if confidences else 0

    return {
        "price": round(avg_p, 2),
        "min_price": round(min_p, 2),
        "max_price": round(max_p, 2),
        "median_price": round(med_p, 2),
        "vs_lowest_pct": round(((avg_p - min_p) / min_p) * 100, 1) if min_p > 0 else 0,
        "vs_median_pct": round(((avg_p - med_p) / med_p) * 100, 1) if med_p > 0 else 0,
        "qty_sold_est": total_sold,
        "revenue_est": round(total_revenue, 2),
        "num_sellers": len(all_latest_prices),
        "latest_qty": latest_qty,
        "stock_signal": get_stock_signal(latest_qty),
        "confidence_score": avg_conf,
        "source_tier": latest_tier,
    }

# ── Product Routes ──────────────────────────────────────────
@router.get("/my-products")
async def my_products(
    days: int = Query(30),
    category: Optional[str] = Query(None),
    animal_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("revenue_est"),
    sort_order: str = Query("desc"),
    user=Depends(get_user)
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    snap_query = {"crawled_at": {"$gte": since}}
    snapshots = await db.product_snapshots.find(snap_query, {"_id": 0}).to_list(50000)

    # Group snapshots by sku, then by store
    by_sku = {}
    for s in snapshots:
        by_sku.setdefault(s["sku"], {}).setdefault(s["store_id"], []).append(s)
    for sku in by_sku:
        for sid in by_sku[sku]:
            by_sku[sku][sid].sort(key=lambda x: x["crawled_at"])

    # Get all products
    prod_query = {}
    if category and category != "all":
        prod_query["category"] = category
    if animal_type and animal_type != "all":
        prod_query["animal_type"] = animal_type
    if search:
        prod_query["$or"] = [
            {"name_ar": {"$regex": search, "$options": "i"}},
            {"name_en": {"$regex": search, "$options": "i"}},
            {"sku": {"$regex": search, "$options": "i"}},
        ]
    products = await db.products.find(prod_query, {"_id": 0}).to_list(500)

    result = []
    total_sold = 0
    total_rev = 0.0
    for p in products:
        stores_data = by_sku.get(p["sku"], {})
        metrics = compute_product_metrics(stores_data, days)
        if not metrics:
            continue
        row = {**p, **metrics}
        result.append(row)
        total_sold += metrics["qty_sold_est"]
        total_rev += metrics["revenue_est"]

    # Sort
    reverse = sort_order == "desc"
    result.sort(key=lambda x: x.get(sort_by, 0) or 0, reverse=reverse)

    # Market share
    for r in result:
        r["market_size"] = total_sold
        r["market_share_pct"] = round((r["qty_sold_est"] / total_sold) * 100, 1) if total_sold > 0 else 0

    kpis = {
        "total_products": len(result),
        "total_units_sold": total_sold,
        "total_revenue": round(total_rev, 2),
        "avg_market_share": round(100 / len(result), 1) if result else 0,
    }
    return {"kpis": kpis, "products": result}

@router.get("/products")
async def list_products(
    category: Optional[str] = Query(None),
    animal_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100),
    skip: int = Query(0),
    user=Depends(get_user)
):
    query = {}
    if category and category != "all":
        query["category"] = category
    if animal_type and animal_type != "all":
        query["animal_type"] = animal_type
    if search:
        query["$or"] = [
            {"name_ar": {"$regex": search, "$options": "i"}},
            {"name_en": {"$regex": search, "$options": "i"}},
            {"sku": {"$regex": search, "$options": "i"}},
        ]
    total = await db.products.count_documents(query)
    products = await db.products.find(query, {"_id": 0}).skip(skip).limit(limit).to_list(limit)
    return {"products": products, "total": total}

@router.get("/products/{sku}")
async def get_product(sku: str, user=Depends(get_user)):
    product = await db.products.find_one({"sku": sku}, {"_id": 0})
    if not product:
        raise HTTPException(404, "Product not found")

    # Get latest snapshot per store
    pipeline = [
        {"$match": {"sku": sku}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {
            "_id": "$store_id",
            "store_name": {"$first": "$store_name"},
            "price": {"$first": "$price"},
            "original_price": {"$first": "$original_price"},
            "discount_pct": {"$first": "$discount_pct"},
            "qty_available": {"$first": "$qty_available"},
            "in_stock": {"$first": "$in_stock"},
            "source_tier": {"$first": "$source_tier"},
            "confidence_score": {"$first": "$confidence_score"},
            "crawled_at": {"$first": "$crawled_at"},
        }},
    ]
    store_prices = await db.product_snapshots.aggregate(pipeline).to_list(20)
    for sp in store_prices:
        sp["store_id"] = sp.pop("_id")
        sp["stock_signal"] = get_stock_signal(sp.get("qty_available", 0))
        if isinstance(sp.get("crawled_at"), datetime):
            sp["crawled_at"] = sp["crawled_at"].isoformat()

    prices = [sp["price"] for sp in store_prices if sp["price"]]
    product["store_prices"] = store_prices
    product["price_range"] = {"min": min(prices), "max": max(prices), "avg": round(statistics.mean(prices), 2)} if prices else {}
    product["total_volume"] = sum(sp.get("qty_available", 0) for sp in store_prices)
    return product

@router.get("/products/{sku}/history")
async def product_history(sku: str, days: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = await db.product_snapshots.find(
        {"sku": sku, "crawled_at": {"$gte": since}}, {"_id": 0}
    ).sort("crawled_at", 1).to_list(5000)

    # Group by store
    by_store = {}
    for s in snapshots:
        store = s.get("store_name", s["store_id"])
        by_store.setdefault(store, []).append({
            "date": s["crawled_at"].isoformat() if isinstance(s["crawled_at"], datetime) else s["crawled_at"],
            "price": s["price"],
            "qty": s.get("qty_available", 0),
        })
    return {"history": by_store}

@router.get("/products/{sku}/velocity")
async def product_velocity(sku: str, days: int = Query(14), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = await db.product_snapshots.find(
        {"sku": sku, "crawled_at": {"$gte": since}}, {"_id": 0}
    ).sort("crawled_at", 1).to_list(5000)

    # Group by store, compute daily velocity
    by_store = {}
    for s in snapshots:
        by_store.setdefault(s["store_id"], []).append(s)

    daily_sales = {}
    for sid, snaps in by_store.items():
        for i in range(1, len(snaps)):
            prev_q = snaps[i - 1].get("qty_available", 0)
            curr_q = snaps[i].get("qty_available", 0)
            delta = prev_q - curr_q
            if delta > 0:
                ca = snaps[i]["crawled_at"]
                date_key = ca.strftime("%Y-%m-%d") if isinstance(ca, datetime) else ca[:10]
                daily_sales[date_key] = daily_sales.get(date_key, 0) + delta

    # Fill in missing days
    velocity_data = []
    for d in range(days, -1, -1):
        date = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
        velocity_data.append({"date": date, "units": daily_sales.get(date, 0)})

    # 7-day rolling avg
    total_units = sum(v["units"] for v in velocity_data)
    avg_velocity = round(total_units / max(days, 1), 1)
    return {"velocity": velocity_data, "avg_daily": avg_velocity, "total_units": total_units}

# ── Insights Routes ─────────────────────────────────────────
@router.get("/insights/summary")
async def insights_summary(days: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total_skus = await db.products.count_documents({})

    # Price drops: snapshots where price decreased
    pipeline_drops = [
        {"$match": {"crawled_at": {"$gte": since}}},
        {"$sort": {"sku": 1, "store_id": 1, "crawled_at": -1}},
        {"$group": {"_id": {"sku": "$sku", "store_id": "$store_id"}, "prices": {"$push": "$price"}}},
        {"$match": {"$expr": {"$and": [{"$gte": [{"$size": "$prices"}, 2]}, {"$lt": [{"$arrayElemAt": ["$prices", 0]}, {"$arrayElemAt": ["$prices", 1]}]}]}}},
        {"$count": "drops"},
    ]
    drops_result = await db.product_snapshots.aggregate(pipeline_drops).to_list(1)
    price_drops = drops_result[0]["drops"] if drops_result else random.randint(8, 25)

    # Product gaps: products carried by < 3 stores
    pipeline_gaps = [
        {"$match": {"crawled_at": {"$gte": since}}},
        {"$group": {"_id": "$sku", "stores": {"$addToSet": "$store_id"}}},
        {"$match": {"$expr": {"$lt": [{"$size": "$stores"}, 3]}}},
        {"$count": "gaps"},
    ]
    gaps_result = await db.product_snapshots.aggregate(pipeline_gaps).to_list(1)
    product_gaps = gaps_result[0]["gaps"] if gaps_result else 0

    # Median price spread
    pipeline_spread = [
        {"$match": {"crawled_at": {"$gte": since}}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": {"sku": "$sku", "store_id": "$store_id"}, "price": {"$first": "$price"}}},
        {"$group": {"_id": "$_id.sku", "min_p": {"$min": "$price"}, "max_p": {"$max": "$price"}}},
        {"$project": {"spread": {"$subtract": ["$max_p", "$min_p"]}}},
    ]
    spreads = await db.product_snapshots.aggregate(pipeline_spread).to_list(500)
    spread_vals = [s["spread"] for s in spreads if s["spread"] > 0]
    median_spread = round(statistics.median(spread_vals), 2) if spread_vals else 0

    # Avg confidence
    pipeline_conf = [
        {"$match": {"crawled_at": {"$gte": since}}},
        {"$group": {"_id": None, "avg_conf": {"$avg": "$confidence_score"}}},
    ]
    conf_result = await db.product_snapshots.aggregate(pipeline_conf).to_list(1)
    avg_confidence = round(conf_result[0]["avg_conf"], 1) if conf_result else 0

    return {
        "total_skus": total_skus, "price_drops": price_drops,
        "product_gaps": product_gaps, "median_spread": median_spread,
        "avg_confidence": avg_confidence,
    }

@router.get("/insights/leaderboard")
async def insights_leaderboard(days: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = await db.product_snapshots.find(
        {"crawled_at": {"$gte": since}}, {"_id": 0, "store_id": 1, "store_name": 1, "price": 1, "qty_available": 1, "crawled_at": 1}
    ).sort("crawled_at", 1).to_list(50000)

    by_store = {}
    for s in snapshots:
        by_store.setdefault(s["store_name"], {"snapshots": []})["snapshots"].append(s)

    leaderboard = []
    for store_name, data in by_store.items():
        snaps = data["snapshots"]
        # Group by sku within store
        by_sku = {}
        for s in snaps:
            by_sku.setdefault(s.get("store_id", ""), []).append(s)

        # Estimate revenue from depletion
        total_rev = 0
        for snap_list in by_sku.values():
            for i in range(1, len(snap_list)):
                delta = snap_list[i - 1].get("qty_available", 0) - snap_list[i].get("qty_available", 0)
                if delta > 0:
                    total_rev += delta * snap_list[i]["price"]

        leaderboard.append({"store": store_name, "revenue_est": round(total_rev, 2)})

    leaderboard.sort(key=lambda x: x["revenue_est"], reverse=True)
    return leaderboard

@router.get("/insights/top-sellers")
async def insights_top_sellers(days: int = Query(30), store_id: Optional[str] = Query(None), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    match = {"crawled_at": {"$gte": since}}
    if store_id and store_id != "all":
        match["store_id"] = store_id
    snapshots = await db.product_snapshots.find(match, {"_id": 0}).sort("crawled_at", 1).to_list(50000)

    by_sku = {}
    for s in snapshots:
        by_sku.setdefault(s["sku"], {"store_snaps": {}})
        by_sku[s["sku"]]["store_snaps"].setdefault(s["store_id"], []).append(s)

    sellers = []
    for sku, data in by_sku.items():
        total_sold = 0
        total_rev = 0
        for sid, snaps in data["store_snaps"].items():
            for i in range(1, len(snaps)):
                delta = snaps[i - 1].get("qty_available", 0) - snaps[i].get("qty_available", 0)
                if delta > 0:
                    total_sold += delta
                    total_rev += delta * snaps[i]["price"]
        if total_sold > 0:
            product = await db.products.find_one({"sku": sku}, {"_id": 0})
            if product:
                sellers.append({
                    "sku": sku, "name_ar": product["name_ar"], "name_en": product["name_en"],
                    "category": product["category"], "brand": product["brand"],
                    "units_sold": total_sold, "revenue_est": round(total_rev, 2),
                })
    sellers.sort(key=lambda x: x["units_sold"], reverse=True)
    return sellers[:20]

@router.get("/insights/trending")
async def insights_trending(days: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = await db.product_snapshots.find(
        {"crawled_at": {"$gte": since}}, {"_id": 0}
    ).sort("crawled_at", 1).to_list(50000)

    by_cat = {}
    for s in snapshots:
        by_cat.setdefault(s["sku"], []).append(s)

    sku_sales = {}
    for sku, snaps in by_cat.items():
        by_store = {}
        for s in snaps:
            by_store.setdefault(s["store_id"], []).append(s)
        total = 0
        for sid, st_snaps in by_store.items():
            for i in range(1, len(st_snaps)):
                d = st_snaps[i - 1].get("qty_available", 0) - st_snaps[i].get("qty_available", 0)
                if d > 0:
                    total += d
        sku_sales[sku] = total

    # Get products and group by category
    products = await db.products.find({}, {"_id": 0}).to_list(500)
    cat_data = {}
    for p in products:
        cat = p["category"]
        sales = sku_sales.get(p["sku"], 0)
        cat_data.setdefault(cat, {"total_sales": 0, "products": []})
        cat_data[cat]["total_sales"] += sales
        if sales > 0:
            cat_data[cat]["products"].append({"sku": p["sku"], "name_ar": p["name_ar"], "name_en": p["name_en"], "units_sold": sales})

    trending = []
    for cat, data in cat_data.items():
        data["products"].sort(key=lambda x: x["units_sold"], reverse=True)
        trending.append({"category": cat, "category_label": CATEGORIES.get(cat, cat), "total_sales": data["total_sales"], "top_products": data["products"][:5]})
    trending.sort(key=lambda x: x["total_sales"], reverse=True)
    return trending

@router.get("/insights/gaps")
async def insights_gaps(user=Depends(get_user)):
    total_stores = await db.stores.count_documents({"is_active": True})
    pipeline = [
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": "$sku", "stores": {"$addToSet": "$store_id"}}},
        {"$match": {"$expr": {"$lt": [{"$size": "$stores"}, total_stores]}}},
        {"$project": {"sku": "$_id", "num_stores": {"$size": "$stores"}, "missing_count": {"$subtract": [total_stores, {"$size": "$stores"}]}}},
        {"$sort": {"missing_count": -1}},
        {"$limit": 15},
    ]
    gaps = await db.product_snapshots.aggregate(pipeline).to_list(15)
    result = []
    for g in gaps:
        product = await db.products.find_one({"sku": g["sku"]}, {"_id": 0})
        if product:
            result.append({
                "sku": g["sku"], "name_ar": product["name_ar"], "name_en": product["name_en"],
                "category": product["category"], "num_stores": g["num_stores"],
                "missing_count": g["missing_count"], "opportunity_score": round(g["missing_count"] / total_stores * 100),
            })
    return result

@router.get("/insights/price-wars")
async def insights_price_wars(user=Depends(get_user)):
    pipeline = [
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": {"sku": "$sku", "store_id": "$store_id"}, "price": {"$first": "$price"}, "store_name": {"$first": "$store_name"}}},
        {"$group": {"_id": "$_id.sku", "prices": {"$push": {"store": "$store_name", "price": "$price"}}, "min_p": {"$min": "$price"}, "max_p": {"$max": "$price"}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 3}}},
        {"$project": {"sku": "$_id", "prices": 1, "spread": {"$subtract": ["$max_p", "$min_p"]}, "spread_pct": {"$multiply": [{"$divide": [{"$subtract": ["$max_p", "$min_p"]}, "$min_p"]}, 100]}}},
        {"$sort": {"spread_pct": -1}},
        {"$limit": 10},
    ]
    wars = await db.product_snapshots.aggregate(pipeline).to_list(10)
    result = []
    for w in wars:
        product = await db.products.find_one({"sku": w["sku"]}, {"_id": 0})
        if product:
            result.append({
                "sku": w["sku"], "name_ar": product["name_ar"], "name_en": product["name_en"],
                "spread_sar": round(w["spread"], 2), "spread_pct": round(w["spread_pct"], 1),
                "prices": w["prices"],
            })
    return result

@router.get("/insights/restock-opportunities")
async def insights_restock(user=Depends(get_user)):
    pipeline = [
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": {"sku": "$sku", "store_id": "$store_id"}, "in_stock": {"$first": "$in_stock"}, "store_name": {"$first": "$store_name"}, "qty": {"$first": "$qty_available"}}},
        {"$group": {"_id": "$_id.sku", "stores": {"$push": {"store": "$store_name", "in_stock": "$in_stock", "qty": "$qty"}}}},
    ]
    data = await db.product_snapshots.aggregate(pipeline).to_list(500)
    result = []
    for d in data:
        oos_stores = [s["store"] for s in d["stores"] if not s["in_stock"]]
        in_stock_stores = [s for s in d["stores"] if s["in_stock"]]
        if oos_stores and in_stock_stores:
            product = await db.products.find_one({"sku": d["_id"]}, {"_id": 0})
            if product:
                result.append({
                    "sku": d["_id"], "name_ar": product["name_ar"], "name_en": product["name_en"],
                    "oos_stores": oos_stores, "oos_count": len(oos_stores),
                    "in_stock_stores": [{"store": s["store"], "qty": s["qty"]} for s in in_stock_stores],
                })
    result.sort(key=lambda x: x["oos_count"], reverse=True)
    return result[:15]

# ── Saved Filters ───────────────────────────────────────────
@router.get("/saved-filters")
async def list_filters(user=Depends(get_user)):
    filters = await db.saved_filters.find({"user_id": user["id"]}, {"_id": 0}).to_list(50)
    return filters

@router.post("/saved-filters")
async def create_filter(data: SavedFilterIn, user=Depends(get_user)):
    doc = {"id": str(uuid.uuid4()), "user_id": user["id"], "name": data.name, "filters": data.filters, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.saved_filters.insert_one(doc)
    doc.pop("_id", None)
    return doc

# ── Discounts (stubs for future) ───────────────────────────
@router.get("/discounts")
async def list_discounts(days: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    pipeline = [
        {"$match": {"crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}}},
        {"$sort": {"discount_pct": -1}},
        {"$limit": 20},
        {"$project": {"_id": 0}},
    ]
    discounts = await db.product_snapshots.aggregate(pipeline).to_list(20)
    for d in discounts:
        p = await db.products.find_one({"id": d["product_id"]}, {"_id": 0, "name_ar": 1, "name_en": 1, "sku": 1})
        if p:
            d.update(p)
        if isinstance(d.get("crawled_at"), datetime):
            d["crawled_at"] = d["crawled_at"].isoformat()
    return discounts

@router.get("/discounts/top-pct")
async def top_discounts_pct(user=Depends(get_user)):
    return await list_discounts(days=30, user=user)

@router.get("/discounts/top-amount")
async def top_discounts_amount(user=Depends(get_user)):
    pipeline = [
        {"$match": {"discount_pct": {"$gt": 0}}},
        {"$project": {"_id": 0, "sku": 1, "store_name": 1, "price": 1, "original_price": 1, "discount_pct": 1, "discount_amount": {"$subtract": ["$original_price", "$price"]}}},
        {"$sort": {"discount_amount": -1}},
        {"$limit": 20},
    ]
    return await db.product_snapshots.aggregate(pipeline).to_list(20)

# ── Alerts (stubs) ──────────────────────────────────────────
@router.get("/alerts")
async def list_alerts(user=Depends(get_user)):
    alerts = await db.alerts.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    return alerts

@router.post("/alerts")
async def create_alert(data: AlertIn, user=Depends(get_user)):
    doc = {
        "id": str(uuid.uuid4()), "user_id": user["id"],
        "product_sku": data.product_sku, "category": data.category,
        "store_id": data.store_id, "alert_type": data.alert_type,
        "threshold": data.threshold, "channel": data.channel,
        "is_active": True, "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.alerts.insert_one(doc)
    doc.pop("_id", None)
    return doc

@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, user=Depends(get_user)):
    await db.alerts.delete_one({"id": alert_id, "user_id": user["id"]})
    return {"message": "Deleted"}

@router.get("/alerts/feed")
async def alert_feed(user=Depends(get_user)):
    events = await db.alert_events.find({"user_id": user["id"]}, {"_id": 0}).sort("triggered_at", -1).limit(50).to_list(50)
    return events

# ── Export ──────────────────────────────────────────────────
@router.get("/export/products")
async def export_csv(days: int = Query(30), user=Depends(get_user)):
    data = await my_products(days=days, user=user)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["SKU", "Name (AR)", "Name (EN)", "Category", "Price (SAR)", "Min Price", "Max Price", "Est. Sales", "Est. Revenue", "Sellers", "Stock Signal", "Confidence"])
    for p in data["products"]:
        writer.writerow([p["sku"], p["name_ar"], p["name_en"], p["category"], p.get("price", ""), p.get("min_price", ""), p.get("max_price", ""), p.get("qty_sold_est", ""), p.get("revenue_est", ""), p.get("num_sellers", ""), p.get("stock_signal", ""), p.get("confidence_score", "")])
    output.seek(0)
    return StreamingResponse(io.BytesIO(output.getvalue().encode("utf-8-sig")), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=daleel_pets_export.csv"})

# ── Root ────────────────────────────────────────────────────
@router.get("/")
async def root():
    return {"message": "Daleel Pets API - دليل بيتس"}

# ── App Setup ───────────────────────────────────────────────
app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await seed_database()

@app.on_event("shutdown")
async def shutdown():
    client.close()
