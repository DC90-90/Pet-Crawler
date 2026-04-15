from fastapi import FastAPI, APIRouter, Query, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import random
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

# --- Models ---
class Competitor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    platform: str
    website_url: str = ""
    logo_initial: str = ""
    status: str = "active"
    sync_status: str = "synced"
    last_synced: str = ""
    total_products: int = 0
    created_at: str = ""

class CompetitorCreate(BaseModel):
    name: str
    platform: str
    website_url: str = ""

class CompetitorUpdate(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    website_url: Optional[str] = None
    status: Optional[str] = None

class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    competitor_id: str
    competitor_name: str
    name: str
    category: str
    price: float
    original_price: float
    discount_percentage: float = 0
    stock_quantity: int = 0
    stock_status: str = "in_stock"
    rating: float = 0
    reviews_count: int = 0
    sales_count: int = 0
    is_best_seller: bool = False
    shipping_info: str = "Standard"
    image_url: str = ""
    last_updated: str = ""
    created_at: str = ""

class DashboardOverview(BaseModel):
    total_competitors: int = 0
    total_products: int = 0
    avg_price: float = 0
    out_of_stock_count: int = 0
    low_stock_count: int = 0
    best_seller_count: int = 0
    total_categories: int = 0
    avg_rating: float = 0
    avg_discount: float = 0
    categories: list = []
    platform_distribution: list = []
    competitor_product_counts: list = []

# --- Seed Data ---
COMPETITORS_SEED = [
    {"name": "Zarafa", "platform": "Salla", "website_url": "https://zarafa.sa"},
    {"name": "Petsy", "platform": "Shopify", "website_url": "https://petsy.sa"},
    {"name": "Aleef", "platform": "Zid", "website_url": "https://aleef.sa"},
    {"name": "Lanapets", "platform": "Salla", "website_url": "https://lanapets.sa"},
    {"name": "Petshouses", "platform": "Shopify", "website_url": "https://petshouses.sa"},
]

PRODUCTS_SEED = [
    # Dog Food
    {"name": "Royal Canin Maxi Adult 15kg", "category": "Dog Food", "base_price": 289, "img": ""},
    {"name": "Pedigree Adult Chicken & Veg 10kg", "category": "Dog Food", "base_price": 145, "img": ""},
    {"name": "Brit Premium Adult Large 15kg", "category": "Dog Food", "base_price": 219, "img": ""},
    {"name": "Josera SensiPlus 12.5kg", "category": "Dog Food", "base_price": 265, "img": ""},
    {"name": "Acana Prairie Poultry 11.4kg", "category": "Dog Food", "base_price": 349, "img": ""},
    {"name": "Orijen Original Dog 11.4kg", "category": "Dog Food", "base_price": 389, "img": ""},
    # Cat Food
    {"name": "Whiskas Tuna Adult 7kg", "category": "Cat Food", "base_price": 98, "img": ""},
    {"name": "Royal Canin Indoor Cat 4kg", "category": "Cat Food", "base_price": 175, "img": ""},
    {"name": "N&D Pumpkin Lamb Adult Cat 5kg", "category": "Cat Food", "base_price": 245, "img": ""},
    {"name": "Me-O Tuna 7kg", "category": "Cat Food", "base_price": 79, "img": ""},
    {"name": "Purina Pro Plan Adult Cat 3kg", "category": "Cat Food", "base_price": 135, "img": ""},
    {"name": "Hills Science Diet Adult Cat 4kg", "category": "Cat Food", "base_price": 189, "img": ""},
    # Bird Supplies
    {"name": "Versele-Laga Prestige Budgies 4kg", "category": "Bird Supplies", "base_price": 65, "img": ""},
    {"name": "Zupreem FruitBlend Parrot 1.5kg", "category": "Bird Supplies", "base_price": 89, "img": ""},
    {"name": "Vitakraft Menu Canary 1kg", "category": "Bird Supplies", "base_price": 42, "img": ""},
    # Fish Supplies
    {"name": "Tetra Min Tropical Flakes 200g", "category": "Fish Supplies", "base_price": 55, "img": ""},
    {"name": "API Stress Coat 473ml", "category": "Fish Supplies", "base_price": 78, "img": ""},
    {"name": "Fluval FX6 Canister Filter", "category": "Fish Supplies", "base_price": 899, "img": ""},
    # Accessories
    {"name": "Premium Leather Dog Leash", "category": "Accessories", "base_price": 120, "img": ""},
    {"name": "Orthopedic Pet Bed Large", "category": "Accessories", "base_price": 199, "img": ""},
    {"name": "Stainless Steel Pet Bowl Set", "category": "Accessories", "base_price": 45, "img": ""},
    {"name": "Pet Carrier Airline Approved", "category": "Accessories", "base_price": 249, "img": ""},
    {"name": "Automatic Water Fountain 2.4L", "category": "Accessories", "base_price": 135, "img": ""},
    # Toys
    {"name": "Kong Classic Dog Toy Large", "category": "Toys", "base_price": 65, "img": ""},
    {"name": "Chuckit Ultra Ball 2-Pack", "category": "Toys", "base_price": 45, "img": ""},
    {"name": "Cat Tunnel 3-Way Collapsible", "category": "Toys", "base_price": 55, "img": ""},
    {"name": "Interactive Feather Wand Cat Toy", "category": "Toys", "base_price": 29, "img": ""},
    # Grooming
    {"name": "FURminator deShedding Tool Large", "category": "Grooming", "base_price": 149, "img": ""},
    {"name": "TropiClean Berry Clean Shampoo 592ml", "category": "Grooming", "base_price": 68, "img": ""},
    {"name": "Safari Self-Cleaning Slicker Brush", "category": "Grooming", "base_price": 42, "img": ""},
    {"name": "Pet Nail Clipper Professional", "category": "Grooming", "base_price": 35, "img": ""},
    # Healthcare
    {"name": "Frontline Plus Flea Treatment Dog", "category": "Healthcare", "base_price": 125, "img": ""},
    {"name": "NaturVet Glucosamine DS 60 Tabs", "category": "Healthcare", "base_price": 89, "img": ""},
    {"name": "Virbac C.E.T. Dental Chews Medium", "category": "Healthcare", "base_price": 75, "img": ""},
    {"name": "Vetoquinol Omega 3-6 Supplement", "category": "Healthcare", "base_price": 95, "img": ""},
]

async def seed_data():
    existing = await db.competitors.count_documents({})
    if existing > 0:
        return
    
    logger.info("Seeding database with initial data...")
    now = datetime.now(timezone.utc).isoformat()
    
    competitor_ids = []
    for comp_data in COMPETITORS_SEED:
        comp = Competitor(
            name=comp_data["name"],
            platform=comp_data["platform"],
            website_url=comp_data["website_url"],
            logo_initial=comp_data["name"][0].upper(),
            status="active",
            sync_status=random.choice(["synced", "synced", "synced", "syncing"]),
            last_synced=now,
            total_products=0,
            created_at=now,
        )
        doc = comp.model_dump()
        await db.competitors.insert_one(doc)
        competitor_ids.append({"id": comp.id, "name": comp_data["name"]})
    
    product_count_per_comp = {c["id"]: 0 for c in competitor_ids}
    
    for prod_data in PRODUCTS_SEED:
        num_competitors = random.randint(2, min(4, len(competitor_ids)))
        chosen_comps = random.sample(competitor_ids, num_competitors)
        
        for comp in chosen_comps:
            price_var = random.uniform(0.85, 1.18)
            price = round(prod_data["base_price"] * price_var, 2)
            has_discount = random.random() < 0.3
            discount_pct = random.choice([5, 10, 15, 20, 25]) if has_discount else 0
            original_price = round(price / (1 - discount_pct / 100), 2) if has_discount else price
            
            stock_qty = random.choice([0, 0, 2, 5, 8, 15, 25, 50, 100, 200])
            if stock_qty == 0:
                stock_status = "out_of_stock"
            elif stock_qty <= 5:
                stock_status = "low_stock"
            else:
                stock_status = "in_stock"
            
            rating = round(random.uniform(3.0, 5.0), 1)
            reviews = random.randint(0, 350)
            sales = random.randint(10, 2000)
            is_best = sales > 800
            shipping = random.choice(["Free Shipping", "Standard (15 SAR)", "Express (30 SAR)", "Free over 200 SAR"])
            
            product = Product(
                competitor_id=comp["id"],
                competitor_name=comp["name"],
                name=prod_data["name"],
                category=prod_data["category"],
                price=price,
                original_price=original_price,
                discount_percentage=discount_pct,
                stock_quantity=stock_qty,
                stock_status=stock_status,
                rating=rating,
                reviews_count=reviews,
                sales_count=sales,
                is_best_seller=is_best,
                shipping_info=shipping,
                image_url=prod_data["img"],
                last_updated=now,
                created_at=now,
            )
            doc = product.model_dump()
            await db.products.insert_one(doc)
            product_count_per_comp[comp["id"]] += 1
    
    for comp_id, count in product_count_per_comp.items():
        await db.competitors.update_one(
            {"id": comp_id},
            {"$set": {"total_products": count}}
        )
    
    logger.info(f"Seeded {len(COMPETITORS_SEED)} competitors and products.")

@app.on_event("startup")
async def startup():
    await seed_data()

# --- Dashboard ---
@api_router.get("/dashboard/overview", response_model=DashboardOverview)
async def get_dashboard_overview():
    total_comp = await db.competitors.count_documents({"status": "active"})
    total_prod = await db.products.count_documents({})
    
    pipeline_avg = [{"$group": {"_id": None, "avg_price": {"$avg": "$price"}, "avg_rating": {"$avg": "$rating"}, "avg_discount": {"$avg": "$discount_percentage"}}}]
    avg_result = await db.products.aggregate(pipeline_avg).to_list(1)
    avg_price = round(avg_result[0]["avg_price"], 2) if avg_result else 0
    avg_rating = round(avg_result[0]["avg_rating"], 1) if avg_result else 0
    avg_discount = round(avg_result[0]["avg_discount"], 1) if avg_result else 0
    
    oos_count = await db.products.count_documents({"stock_status": "out_of_stock"})
    low_stock = await db.products.count_documents({"stock_status": "low_stock"})
    best_seller_count = await db.products.count_documents({"is_best_seller": True})
    
    cat_pipeline = [{"$group": {"_id": "$category", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    categories = await db.products.aggregate(cat_pipeline).to_list(20)
    categories = [{"name": c["_id"], "count": c["count"]} for c in categories]
    
    platform_pipeline = [{"$group": {"_id": "$platform", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    platforms = await db.competitors.aggregate(platform_pipeline).to_list(10)
    platforms = [{"name": p["_id"], "count": p["count"]} for p in platforms]
    
    comp_pipeline = [{"$match": {"status": "active"}}, {"$project": {"_id": 0, "name": 1, "total_products": 1}}]
    comp_counts = await db.competitors.aggregate(comp_pipeline).to_list(20)
    
    return DashboardOverview(
        total_competitors=total_comp,
        total_products=total_prod,
        avg_price=avg_price,
        out_of_stock_count=oos_count,
        low_stock_count=low_stock,
        best_seller_count=best_seller_count,
        total_categories=len(categories),
        avg_rating=avg_rating,
        avg_discount=avg_discount,
        categories=categories,
        platform_distribution=platforms,
        competitor_product_counts=comp_counts,
    )

# --- Competitors ---
@api_router.get("/competitors")
async def get_competitors():
    comps = await db.competitors.find({}, {"_id": 0}).sort("name", 1).to_list(100)
    return comps

@api_router.post("/competitors")
async def create_competitor(data: CompetitorCreate):
    now = datetime.now(timezone.utc).isoformat()
    comp = Competitor(
        name=data.name,
        platform=data.platform,
        website_url=data.website_url,
        logo_initial=data.name[0].upper() if data.name else "?",
        status="active",
        sync_status="pending",
        last_synced="",
        total_products=0,
        created_at=now,
    )
    doc = comp.model_dump()
    await db.competitors.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api_router.put("/competitors/{competitor_id}")
async def update_competitor(competitor_id: str, data: CompetitorUpdate):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No data to update")
    
    if "name" in update_data:
        update_data["logo_initial"] = update_data["name"][0].upper()
    
    result = await db.competitors.update_one({"id": competitor_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Competitor not found")
    
    updated = await db.competitors.find_one({"id": competitor_id}, {"_id": 0})
    return updated

@api_router.delete("/competitors/{competitor_id}")
async def delete_competitor(competitor_id: str):
    result = await db.competitors.delete_one({"id": competitor_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Competitor not found")
    await db.products.delete_many({"competitor_id": competitor_id})
    return {"message": "Competitor deleted"}

# --- Products ---
@api_router.get("/products")
async def get_products(
    category: Optional[str] = Query(None),
    competitor_id: Optional[str] = Query(None),
    stock_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("name"),
    sort_order: str = Query("asc"),
    limit: int = Query(100),
    skip: int = Query(0),
):
    query = {}
    if category and category != "all":
        query["category"] = category
    if competitor_id and competitor_id != "all":
        query["competitor_id"] = competitor_id
    if stock_status and stock_status != "all":
        query["stock_status"] = stock_status
    if search:
        query["name"] = {"$regex": search, "$options": "i"}
    
    sort_dir = 1 if sort_order == "asc" else -1
    total = await db.products.count_documents(query)
    products = await db.products.find(query, {"_id": 0}).sort(sort_by, sort_dir).skip(skip).limit(limit).to_list(limit)
    
    return {"products": products, "total": total}

@api_router.get("/products/categories")
async def get_product_categories():
    cats = await db.products.distinct("category")
    return cats

@api_router.get("/products/best-sellers")
async def get_best_sellers(
    category: Optional[str] = Query(None),
    limit: int = Query(20),
):
    query = {"is_best_seller": True}
    if category and category != "all":
        query["category"] = category
    
    products = await db.products.find(query, {"_id": 0}).sort("sales_count", -1).to_list(limit)
    return products

@api_router.get("/products/price-comparison")
async def get_price_comparison(
    category: Optional[str] = Query(None),
):
    query = {}
    if category and category != "all":
        query["category"] = category
    
    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$name",
            "category": {"$first": "$category"},
            "prices": {"$push": {
                "competitor_id": "$competitor_id",
                "competitor_name": "$competitor_name",
                "price": "$price",
                "stock_status": "$stock_status",
                "discount_percentage": "$discount_percentage",
            }},
            "avg_price": {"$avg": "$price"},
            "min_price": {"$min": "$price"},
            "max_price": {"$max": "$price"},
        }},
        {"$match": {"$expr": {"$gte": [{"$size": "$prices"}, 2]}}},
        {"$sort": {"_id": 1}},
    ]
    
    results = await db.products.aggregate(pipeline).to_list(100)
    competitors = await db.competitors.find({"status": "active"}, {"_id": 0, "id": 1, "name": 1}).to_list(20)
    
    comparison = []
    for r in results:
        price_map = {}
        for p in r["prices"]:
            price_map[p["competitor_name"]] = {
                "price": p["price"],
                "stock_status": p["stock_status"],
                "discount_percentage": p["discount_percentage"],
            }
        comparison.append({
            "product_name": r["_id"],
            "category": r["category"],
            "avg_price": round(r["avg_price"], 2),
            "min_price": r["min_price"],
            "max_price": r["max_price"],
            "price_spread": round(r["max_price"] - r["min_price"], 2),
            "prices": price_map,
        })
    
    return {"comparison": comparison, "competitors": [c["name"] for c in competitors]}

# --- Sync ---
@api_router.post("/sync/trigger/{competitor_id}")
async def trigger_sync(competitor_id: str):
    comp = await db.competitors.find_one({"id": competitor_id}, {"_id": 0})
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.competitors.update_one(
        {"id": competitor_id},
        {"$set": {"sync_status": "synced", "last_synced": now}}
    )
    
    product_count = await db.products.count_documents({"competitor_id": competitor_id})
    price_change = random.randint(0, 5)
    new_products = random.randint(0, 2)
    
    return {
        "message": f"Sync completed for {comp['name']}",
        "competitor_id": competitor_id,
        "last_synced": now,
        "products_found": product_count,
        "price_changes": price_change,
        "new_products": new_products,
    }

@api_router.post("/sync/trigger-all")
async def trigger_sync_all():
    now = datetime.now(timezone.utc).isoformat()
    await db.competitors.update_many(
        {"status": "active"},
        {"$set": {"sync_status": "synced", "last_synced": now}}
    )
    comp_count = await db.competitors.count_documents({"status": "active"})
    return {"message": f"Sync completed for {comp_count} competitors", "last_synced": now}

@api_router.get("/")
async def root():
    return {"message": "PetTracker API - Competitor Monitoring Tool"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
