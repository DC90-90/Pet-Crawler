from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, Query, HTTPException, Request, Depends, Response, UploadFile, File, BackgroundTasks
from fastapi.encoders import jsonable_encoder
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, random, uuid, bcrypt, jwt as pyjwt, secrets, statistics, csv, io, re, time, shutil, asyncio, math
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from typing import Optional, List
from bson import ObjectId
from pymongo.errors import BulkWriteError
from starlette.responses import StreamingResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from crawlers import (
    crawl_store_waterfall, process_crawled_products,
    extract_brand, guess_category, guess_animal, extract_weight,
    classify_food_subcategory, FOOD_SUBCATEGORIES, FOOD_SUBCATEGORY_PARENTS,
    # iter44 Step-1 validation (read-only VAT-basis audit)
    fetch_own_storefront_catalog_raw, _fetch_zid_api_catalog, _price_amount,
    _storefront_price_index, storefront_price_lookup,
    merchant_index, resolve_own_price, KSA_VAT_RATE,
    sync_own_store_prices,
)
from store_registry import ensure_stores as registry_ensure_stores
from zid_orders import sync_own_store_orders, aggregate_orders, KSA_TZ as ORDERS_KSA_TZ
from cryptography.fernet import Fernet, InvalidToken

# ── Refactored modules (Feb 2026) ───────────────────────────
from models import (
    AuthIn, StoreIn, StoreUpdate, AlertIn, SavedFilterIn,
    Tier4CredentialsIn, OtpSubmitIn, MatchActionIn, IngestPayload,
    AdminCreateUserIn, AdminUpdatePasswordIn, AdminUpdateRoleIn, AdminUpdatePagesIn,
)
from core import (
    PLACEHOLDER_QTY_VALUES, MAX_QTY_DELTA_PER_INTERVAL, MAX_DAILY_SALES_PER_SKU,
    MAX_SOLD_COUNT_DELTA_PER_INTERVAL,
    MIN_AGGREGATION_CONFIDENCE,
    get_stock_signal, _coerce_num, _coerce_int,
    _estimate_sales_from_snapshots, compute_product_metrics,
    compute_market_position,
    ttl_cache, cache_clear,
)

SERVER_START_TIME = time.time()

# iter24: /api/my-products processes the catalogue in chunks of this many
# products per snapshot query — bounds peak memory at production scale so the
# 30D/90D windows no longer OOM the origin (Cloudflare 520). Module-level so
# load tests can vary it and prove chunking-invariance.
MY_PRODUCTS_CHUNK_SIZE = 100

# ── Fernet Encryption (Tier 4 Credential Vault) ────────────
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise RuntimeError("FATAL: ENCRYPTION_KEY environment variable is missing. Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
try:
    fernet = Fernet(ENCRYPTION_KEY.encode())
    _test = fernet.decrypt(fernet.encrypt(b"startup_check"))
    assert _test == b"startup_check"
except Exception as exc:
    raise RuntimeError(f"FATAL: ENCRYPTION_KEY is invalid — Fernet validation failed: {exc}")

def encrypt_value(plaintext: str) -> str:
    if not plaintext:
        return ""
    return fernet.encrypt(plaintext.encode()).decode()

def decrypt_value(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return fernet.decrypt(ciphertext.encode()).decode()

mongo_url = os.environ['MONGO_URL']
# Atlas-friendly timeouts (Jul 2026 production deploy fix).
# Local Mongo answers in <1 ms so preview never hits Motor's default
# serverSelectionTimeoutMS=30_000. Production runs on MongoDB Atlas, which
# occasionally needs 5–10 s on a cold cluster before the first response.
# Without explicit bounds, EVERY startup-handler DB op could hang up to 30 s,
# and the k8s readiness probe (which awaits /api/health, itself a DB call)
# would time out cascade-style until the 4-minute deployment deadline —
# exactly the failure signature we observed. We set:
#   • serverSelectionTimeoutMS=5000 — fail fast if Atlas is unreachable.
#   • connectTimeoutMS=10000       — accommodate a slow TLS/DNS handshake once.
#   • socketTimeoutMS=45000        — long-enough ceiling for legit big reads.
# These bounds don't change any query semantics — they only cap how long a
# stalled network call may block the event loop before raising.
client = AsyncIOMotorClient(
    mongo_url,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,
    socketTimeoutMS=45000,
)
db = client[os.environ['DB_NAME']]
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALG = "HS256"
CRAWLER_TOKEN = "zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO"

# ── RBAC Constants ──────────────────────────────────────────
# Super admin is hardcoded — cannot be deleted, demoted, or have password changed by anyone else.
SUPER_ADMIN_EMAIL = "a.disi@taqueen.sa"
SUPER_ADMIN_PASSWORD = "Ahmaddc90@"
LEGACY_ADMIN_EMAIL = "admin@daleelpets.com"  # to be deleted on startup

VALID_ROLES = ["super_admin", "admin", "user"]
ALL_PAGES = [
    "my_products", "price_intel", "insights", "scanner",
    "discounts", "alerts", "stores", "import", "settings",
]
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Daleel API")
router = APIRouter(prefix="/api")

@router.get("/debug/token")
async def debug_token():
    return {
        "crawler_token_length": len(CRAWLER_TOKEN),
        "first_5_chars": CRAWLER_TOKEN[:5],
        "source": "hardcoded",
    }
scheduler = AsyncIOScheduler()
crawl_paused = False

# ── Rate Limiter ────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many attempts. Wait 60 seconds."},
    )

# ── Security Headers Middleware ─────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data: https:; connect-src 'self' https:; frame-ancestors 'none'"
        return response

# ── Auth Utilities ──────────────────────────────────────────
def hash_pw(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def check_pw(pw, h):
    return bcrypt.checkpw(pw.encode(), h.encode())

def make_token(uid, email):
    return pyjwt.encode(
        {"sub": uid, "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=24), "jti": secrets.token_hex(8)},
        JWT_SECRET, algorithm=JWT_ALG
    )

async def get_user(request: Request):
    # Try httpOnly cookie first, then Bearer token header
    token = request.cookies.get("daleel_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        p = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        u = await db.users.find_one({"_id": ObjectId(p["sub"])})
        if not u:
            raise HTTPException(401, "User not found")
        role = u.get("role", "user")
        # super_admin always has access to every page (implicit)
        allowed = ALL_PAGES if role == "super_admin" else list(u.get("allowed_pages", []) or [])
        return {
            "id": str(u["_id"]),
            "email": u["email"],
            "name": u.get("name", ""),
            "role": role,
            "allowed_pages": allowed,
        }
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid token")


def require_super_admin(user=Depends(get_user)):
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    return user


def is_super_admin_email(email: str) -> bool:
    return (email or "").strip().lower() == SUPER_ADMIN_EMAIL.lower()

# ── Health Endpoint ──────────────────────────────────────────
@router.get("/health")
async def health_check():
    # The k8s readiness probe hits this endpoint. It MUST respond within a
    # couple of seconds even when MongoDB is unreachable, otherwise the pod
    # never becomes Ready and the deploy times out (Jul 2026 production deploy
    # postmortem). Every Motor call below is wrapped in an asyncio timeout, and
    # any failure just degrades the reported status — the probe still gets a
    # fast HTTP 200 with a diagnostic body it can act on.
    async def _timed(coro, timeout: float):
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            return None

    # MongoDB connection state — hard 1.5 s ceiling.
    mongo_ok = False
    ping_result = await _timed(client.admin.command("ping"), timeout=1.5)
    if ping_result is not None:
        mongo_ok = True

    # APScheduler active jobs count
    jobs_count = len(scheduler.get_jobs()) if scheduler.running else 0

    # Playwright availability
    pw_available = False
    pw_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")
    try:
        if Path(pw_path).exists() and any(Path(pw_path).iterdir()):
            pw_available = True
        else:
            pw_available = shutil.which("playwright") is not None
    except Exception:
        pass

    # Last successful crawl timestamp — best-effort, capped at 1.5 s combined.
    last_crawl = None
    if mongo_ok:
        log = await _timed(
            db.crawl_logs.find_one(
                {"tier_used": {"$exists": True}},
                {"_id": 0, "completed_at": 1},
                sort=[("completed_at", -1)],
            ),
            timeout=1.5,
        )
        if log and log.get("completed_at"):
            last_crawl = log["completed_at"] if isinstance(log["completed_at"], str) else log["completed_at"].isoformat()
        else:
            store = await _timed(
                db.stores.find_one(
                    {"last_crawled_at": {"$ne": "", "$exists": True}},
                    {"_id": 0, "last_crawled_at": 1},
                    sort=[("last_crawled_at", -1)],
                ),
                timeout=1.5,
            )
            if store and store.get("last_crawled_at"):
                last_crawl = store["last_crawled_at"]

    # Server uptime
    uptime_secs = round(time.time() - SERVER_START_TIME, 1)

    status = "healthy" if mongo_ok else "degraded"
    return {
        "status": status,
        "mongodb": "connected" if mongo_ok else "disconnected",
        "scheduler_active_jobs": jobs_count,
        "playwright_available": pw_available,
        "last_successful_crawl": last_crawl,
        "uptime_seconds": uptime_secs,
    }

@router.get("/health/detailed")
async def health_detailed(user=Depends(get_user)):
    import httpx

    stores = await db.stores.find({"is_active": True}, {"_id": 0, "id": 1, "name": 1, "domain": 1, "base_url": 1, "last_crawled_at": 1}).sort("name", 1).to_list(50)

    async def probe_store(store):
        url = store.get("base_url") or f"https://{store['domain']}"
        result = {
            "store_name": store["name"],
            "domain": store["domain"],
            "reachable": False,
            "response_time_ms": None,
            "http_status": None,
            "last_successful_crawl": store.get("last_crawled_at"),
        }
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client_http:
                start = time.monotonic()
                resp = await client_http.head(url)
                elapsed_ms = round((time.monotonic() - start) * 1000)
                result["reachable"] = resp.status_code < 500
                result["response_time_ms"] = elapsed_ms
                result["http_status"] = resp.status_code
        except httpx.TimeoutException:
            result["response_time_ms"] = 5000
        except Exception as exc:
            ssl_err = "ssl" in str(type(exc).__name__).lower() or "ssl" in str(exc).lower()
            if ssl_err:
                result["http_status"] = "SSL_ERROR"
            pass
        return result

    results = await asyncio.gather(*[probe_store(s) for s in stores])

    reachable_count = sum(1 for r in results if r["reachable"])
    return {
        "total_stores": len(results),
        "reachable": reachable_count,
        "unreachable": len(results) - reachable_count,
        "stores": list(results),
    }

# ── Models moved to /app/backend/models/schemas.py during Feb 2026 refactor ──

# ── Seed Data ───────────────────────────────────────────────
STORES_SEED = [
    {"name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla", "priority": 1},
    {"name": "Panda Store", "domain": "matjarpanda.com", "platform": "zid", "priority": 1},
    {"name": "Lana Pets", "domain": "lanapets.com", "platform": "salla", "priority": 1},
    {"name": "Cute Pets", "domain": "cutepets.com", "platform": "shopify", "priority": 1},
    {"name": "Hamtaro", "domain": "hamtaro.sa", "platform": "salla", "priority": 2},
    {"name": "Caty Store", "domain": "caty-store.com", "platform": "salla", "priority": 2},
    {"name": "Petsy", "domain": "petsysa.com", "platform": "zid", "priority": 2},
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
    "cat_food": "Cat Food", "cat_food_wet": "Wet Cat Food", "dog_food": "Dog Food",
    "dog_food_wet": "Wet Dog Food", "bird_food": "Bird Food",
    "fish_food": "Fish Food", "equipment": "Equipment", "accessories": "Accessories",
    "litter": "Litter", "toys": "Toys", "grooming": "Grooming",
    "healthcare": "Healthcare", "small_food": "Small Animal Food",
    "reptile": "Reptile", "vet_supplies": "Vet Supplies", "pet_food": "Pet Food",
    # iter36 — food subcategories (additive; parent cat_food/dog_food remain)
    "cat_food_dry": "Dry Cat Food", "cat_treats": "Cat Treats",
    "dog_food_dry": "Dry Dog Food", "dog_treats": "Dog Treats",
}

EXTRA_PRODUCT_TEMPLATES = [
    # (sku_prefix, name_ar, name_en, brand, category, animal, weight, price)
    # Dry Cat Food extras
    ("CF-HS-K2", "هيلز كيتن دجاج 2 كجم", "Hills Kitten Chicken 2kg", "Hills", "cat_food", "cat", 2, 145),
    ("CF-HS-SN3", "هيلز معدة حساسة قطط 3 كجم", "Hills Sensitive Stomach Cat 3kg", "Hills", "cat_food", "cat", 3, 189),
    ("CF-SC-AD4", "شيسير بالغ قطط 4 كجم", "Schesir Adult Cat 4kg", "Schesir", "cat_food", "cat", 4, 210),
    ("CF-JO-IN4", "جوسيرا منزلي قطط 4 كجم", "Josera Indoor Cat 4kg", "Josera", "cat_food", "cat", 4, 165),
    ("CF-BR-ST3", "بريت كير معقم قطط 3 كجم", "Brit Care Sterilised Cat 3kg", "Brit", "cat_food", "cat", 3, 155),
    ("CF-RC-UR2", "رويال كانين عناية بولية 2 كجم", "Royal Canin Urinary Care 2kg", "Royal Canin", "cat_food", "cat", 2, 195),
    ("CF-RC-HB4", "رويال كانين كرات الشعر 4 كجم", "Royal Canin Hairball 4kg", "Royal Canin", "cat_food", "cat", 4, 225),
    ("CF-PO-KT2", "بورينا كيتن 2 كجم", "Purina Kitten 2kg", "Purina", "cat_food", "cat", 2, 110),
    ("CF-GM-SN3", "جيمكات سناك كرانشي 500 جرام", "Gimcat Crunchy Snack 500g", "Gimcat", "cat_food", "cat", 0.5, 35),
    ("CF-ND-CB5", "ان اند دي دجاج رمان 5 كجم", "N&D Chicken Pomegranate 5kg", "N&D", "cat_food", "cat", 5, 265),
    ("CF-RC-PR4", "رويال كانين بيرشن 4 كجم", "Royal Canin Persian 4kg", "Royal Canin", "cat_food", "cat", 4, 235),
    ("CF-RC-BH4", "رويال كانين بريتش 4 كجم", "Royal Canin British Hair 4kg", "Royal Canin", "cat_food", "cat", 4, 235),
    # Wet Cat Food
    ("WC-WH-TN85", "ويسكاس تونا معلب 85 جرام", "Whiskas Tuna Pouch 85g", "Whiskas", "cat_food_wet", "cat", 0.085, 5),
    ("WC-FX-CH85", "فيلكس دجاج معلب 85 جرام", "Felix Chicken Pouch 85g", "Felix", "cat_food_wet", "cat", 0.085, 6),
    ("WC-SC-TN100", "شيسير تونا معلب 100 جرام", "Schesir Tuna Can 100g", "Schesir", "cat_food_wet", "cat", 0.1, 12),
    ("WC-RC-IN85", "رويال كانين منزلي رطب 85 جرام", "Royal Canin Indoor Wet 85g", "Royal Canin", "cat_food_wet", "cat", 0.085, 9),
    ("WC-GM-PA200", "جورميه باتيه 200 جرام", "Gourmet Pate 200g", "Gourmet", "cat_food_wet", "cat", 0.2, 14),
    ("WC-HS-KW85", "هيلز كيتن رطب 85 جرام", "Hills Kitten Wet 85g", "Hills", "cat_food_wet", "cat", 0.085, 11),
    ("WC-WH-CH85", "ويسكاس دجاج معلب 85 جرام", "Whiskas Chicken Pouch 85g", "Whiskas", "cat_food_wet", "cat", 0.085, 5),
    ("WC-FX-SL85", "فيلكس سالمون معلب 85 جرام", "Felix Salmon Pouch 85g", "Felix", "cat_food_wet", "cat", 0.085, 6),
    # Cat Litter
    ("LT-EC-UNS10", "ايفر كلين بدون رائحة 10 لتر", "Ever Clean Unscented 10L", "Ever Clean", "litter", "cat", 10, 89),
    ("LT-EC-LAV6", "ايفر كلين لافندر 6 لتر", "Ever Clean Lavender 6L", "Ever Clean", "litter", "cat", 6, 59),
    ("LT-CT-CLMP10", "كات بيست متكتل 10 لتر", "Cat Best Clumping 10L", "Cat Best", "litter", "cat", 10, 65),
    ("LT-SN-SILC5", "سيليكا رمل كريستال 5 لتر", "Silica Crystal Litter 5L", "Generic", "litter", "cat", 5, 39),
    ("LT-TW-NAT8", "توفو رمل طبيعي 8 لتر", "Tofu Natural Litter 8L", "Generic", "litter", "cat", 8, 45),
    ("LT-PR-BCLP20", "بريما متكتل 20 لتر", "Prima Clumping 20L", "Prima", "litter", "cat", 20, 75),
    ("LT-EC-MS10", "ايفر كلين متعدد القطط 10 لتر", "Ever Clean Multi-Cat 10L", "Ever Clean", "litter", "cat", 10, 95),
    # Cat Accessories
    ("CA-CT-SC60", "عمود خدش للقطط 60 سم", "Cat Scratching Post 60cm", "Trixie", "accessories", "cat", 0, 89),
    ("CA-CT-FN2L", "نافورة مياه للقطط 2 لتر", "Cat Water Fountain 2L", "Catit", "accessories", "cat", 0, 135),
    ("CA-CT-BW2", "طقم اطباق ستانلس للقطط", "Cat Stainless Bowl Set", "Generic", "accessories", "cat", 0, 35),
    ("CA-CT-CL01", "طوق قطط مع جرس", "Cat Collar with Bell", "Generic", "accessories", "cat", 0, 19),
    ("CA-CT-HR01", "فرشاة شعر للقطط ذاتية التنظيف", "Cat Self-Clean Brush", "Trixie", "accessories", "cat", 0, 29),
    ("CA-CT-CR01", "حامل قطط للنوافذ", "Cat Window Perch", "Generic", "accessories", "cat", 0, 79),
    ("CA-CT-BD01", "سرير قطط دائري فاخر", "Round Luxury Cat Bed", "Generic", "accessories", "cat", 0, 119),
    # Dry Dog Food extras
    ("DF-RC-MN8", "رويال كانين ميني بالغ 8 كجم", "Royal Canin Mini Adult 8kg", "Royal Canin", "dog_food", "dog", 8, 225),
    ("DF-RC-MNP2", "رويال كانين ميني جرو 2 كجم", "Royal Canin Mini Puppy 2kg", "Royal Canin", "dog_food", "dog", 2, 105),
    ("DF-HS-AD12", "هيلز بالغ كلاب 12 كجم", "Hills Adult Dog 12kg", "Hills", "dog_food", "dog", 12, 289),
    ("DF-HS-PUP3", "هيلز جرو صغير 3 كجم", "Hills Puppy Small 3kg", "Hills", "dog_food", "dog", 3, 139),
    ("DF-JO-LB15", "جوسيرا لارج بريد 15 كجم", "Josera Large Breed 15kg", "Josera", "dog_food", "dog", 15, 245),
    ("DF-BR-LF15", "بريت لايف كلاب 15 كجم", "Brit Life Dog 15kg", "Brit", "dog_food", "dog", 15, 199),
    ("DF-PD-PUP10", "بيدقري جرو 10 كجم", "Pedigree Puppy 10kg", "Pedigree", "dog_food", "dog", 10, 129),
    ("DF-ND-MN7", "ان اند دي ميني بالغ 7 كجم", "N&D Mini Adult 7kg", "N&D", "dog_food", "dog", 7, 289),
    ("DF-AC-SM6", "اكانا سمول بريد 6 كجم", "Acana Small Breed 6kg", "Acana", "dog_food", "dog", 6, 279),
    ("DF-OR-PUP6", "اوريجن جرو 6 كجم", "Orijen Puppy 6kg", "Orijen", "dog_food", "dog", 6, 299),
    ("DF-RC-GS12", "رويال كانين جيرمن شيبرد 12 كجم", "Royal Canin German Shepherd 12kg", "Royal Canin", "dog_food", "dog", 12, 345),
    ("DF-RC-GR12", "رويال كانين جولدن ريتريفر 12 كجم", "Royal Canin Golden Retriever 12kg", "Royal Canin", "dog_food", "dog", 12, 345),
    # Wet Dog Food
    ("WD-PD-CH400", "بيدقري دجاج معلب 400 جرام", "Pedigree Chicken Can 400g", "Pedigree", "dog_food_wet", "dog", 0.4, 12),
    ("WD-RC-MN85", "رويال كانين ميني رطب 85 جرام", "Royal Canin Mini Wet 85g", "Royal Canin", "dog_food_wet", "dog", 0.085, 9),
    ("WD-HS-AD370", "هيلز بالغ رطب 370 جرام", "Hills Adult Wet 370g", "Hills", "dog_food_wet", "dog", 0.37, 15),
    ("WD-BR-PT400", "بريت باتيه كلاب 400 جرام", "Brit Pate Dog 400g", "Brit", "dog_food_wet", "dog", 0.4, 10),
    ("WD-SC-CH150", "شيسير دجاج كلاب 150 جرام", "Schesir Chicken Dog 150g", "Schesir", "dog_food_wet", "dog", 0.15, 14),
    # Dog Accessories
    ("DA-TX-HR01", "حزام صدر للكلاب مقاس وسط", "Dog Harness Medium", "Trixie", "accessories", "dog", 0, 75),
    ("DA-TX-LS01", "سلسلة كلب قابلة للسحب 5 متر", "Retractable Dog Leash 5m", "Flexi", "accessories", "dog", 0, 95),
    ("DA-PF-BD02", "سرير كلب متوسط", "Medium Dog Bed", "PetFusion", "accessories", "dog", 0, 149),
    ("DA-KN-KG02", "كونغ وابل كبير", "Kong Wobbler Large", "Kong", "accessories", "dog", 0, 85),
    ("DA-TX-BL01", "مشبك كلب معدني", "Metal Dog Clip", "Trixie", "accessories", "dog", 0, 25),
    ("DA-BW-ST2", "طقم اطباق مرتفع للكلاب", "Elevated Dog Bowl Set", "Generic", "accessories", "dog", 0, 65),
    ("DA-CR-FLD01", "قفص قابل للطي للكلاب كبير", "Foldable Dog Crate Large", "Generic", "accessories", "dog", 0, 289),
    ("DA-CL-NY01", "طوق نايلون كلب وسط", "Nylon Dog Collar Medium", "Generic", "accessories", "dog", 0, 25),
    # Bird extras
    ("BD-VL-BDG2", "فيرسيل لاجا بادجي 2 كجم", "Versele-Laga Budgies 2kg", "Versele-Laga", "bird_food", "bird", 2, 45),
    ("BD-VL-FNC1", "فيرسيل لاجا فينش 1 كجم", "Versele-Laga Finch 1kg", "Versele-Laga", "bird_food", "bird", 1, 38),
    ("BD-TX-CG01", "قفص طيور كبير 80 سم", "Large Bird Cage 80cm", "Trixie", "accessories", "bird", 0, 199),
    ("BD-TX-CG02", "قفص طيور صغير 40 سم", "Small Bird Cage 40cm", "Trixie", "accessories", "bird", 0, 89),
    ("BD-TX-SW01", "ارجوحة طيور خشبية", "Wooden Bird Swing", "Generic", "toys", "bird", 0, 19),
    ("BD-TX-BT01", "حمام طيور", "Bird Bath", "Generic", "accessories", "bird", 0, 25),
    ("BD-VT-VIT01", "فيتامينات طيور 50 مل", "Bird Vitamins 50ml", "Vitakraft", "healthcare", "bird", 0, 29),
    # Fish extras
    ("FS-TT-GP100", "تترا جولد فيش 100 جرام", "Tetra Goldfish 100g", "Tetra", "fish_food", "fish", 0.1, 35),
    ("FS-TT-BT200", "تترا بيتا 200 مل", "Tetra Betta 200ml", "Tetra", "fish_food", "fish", 0.2, 25),
    ("FS-AP-WC473", "مكيف مياه API 473 مل", "API Water Conditioner 473ml", "API", "fish_food", "fish", 0.473, 65),
    ("FS-FV-207", "فلتر فلوفال 207", "Fluval 207 Filter", "Fluval", "equipment", "fish", 0, 449),
    ("FS-TT-HT100", "سخان تترا 100 واط", "Tetra Heater 100W", "Tetra", "equipment", "fish", 0, 89),
    ("FS-AQ-LED60", "اضاءة LED للاحواض 60 سم", "LED Aquarium Light 60cm", "Generic", "equipment", "fish", 0, 119),
    ("FS-DEC-PL01", "نباتات اصطناعية للاحواض", "Artificial Aquarium Plants", "Generic", "accessories", "fish", 0, 29),
    ("FS-GRV-5KG", "حصى احواض طبيعي 5 كجم", "Natural Gravel 5kg", "Generic", "accessories", "fish", 5, 25),
    # Reptile
    ("RP-UVB-10", "مصباح UVB للزواحف 10.0", "UVB Reptile Lamp 10.0", "Exo Terra", "reptile", "reptile", 0, 89),
    ("RP-HT-CRM", "مصباح سيراميك حراري 100 واط", "Ceramic Heat Lamp 100W", "Exo Terra", "reptile", "reptile", 0, 65),
    ("RP-TR-60", "حوض زواحف زجاجي 60 سم", "Glass Terrarium 60cm", "Exo Terra", "reptile", "reptile", 0, 349),
    ("RP-TR-45", "حوض زواحف زجاجي 45 سم", "Glass Terrarium 45cm", "Exo Terra", "reptile", "reptile", 0, 249),
    ("RP-FD-CRK", "صراصير مجففة للزواحف 35 جرام", "Dried Crickets 35g", "Exo Terra", "reptile", "reptile", 0.035, 35),
    ("RP-SUB-CB", "تربة جوز الهند للزواحف", "Coconut Substrate", "Exo Terra", "reptile", "reptile", 0, 29),
    ("RP-WB-SM", "وعاء ماء صغير للزواحف", "Small Reptile Water Bowl", "Exo Terra", "reptile", "reptile", 0, 19),
    ("RP-TH-DG", "مقياس حرارة رقمي للزواحف", "Digital Thermometer", "Exo Terra", "reptile", "reptile", 0, 35),
    # Grooming extras
    ("GR-BP-DG01", "شامبو بيفار للكلاب 250 مل", "Beaphar Dog Shampoo 250ml", "Beaphar", "grooming", "dog", 0.25, 45),
    ("GR-BP-CT01", "شامبو بيفار للقطط 250 مل", "Beaphar Cat Shampoo 250ml", "Beaphar", "grooming", "cat", 0.25, 45),
    ("GR-TX-BR02", "فرشاة شعر بين مزدوج", "Double Pin Brush", "Trixie", "grooming", "dog", 0, 39),
    ("GR-FM-SM", "فرمينيتور صغير للقطط", "FURminator Small Cat", "FURminator", "grooming", "cat", 0, 129),
    ("GR-VB-TP01", "معجون اسنان فيرباك كلاب", "Virbac Toothpaste Dog", "Virbac", "grooming", "dog", 0, 55),
    ("GR-VB-TB01", "فرشاة اسنان للحيوانات", "Pet Toothbrush", "Virbac", "grooming", "cat", 0, 25),
    ("GR-TX-CL01", "مقص شعر احترافي", "Pro Grooming Clippers", "Trixie", "grooming", "dog", 0, 195),
    ("GR-SF-EW01", "مناديل تنظيف الاذن", "Ear Cleaning Wipes", "Safari", "grooming", "dog", 0, 35),
    ("GR-SF-EY01", "مناديل تنظيف العيون", "Eye Cleaning Wipes", "Safari", "grooming", "cat", 0, 35),
    ("GR-TC-CON592", "بلسم تروبي كلين 592 مل", "TropiClean Conditioner 592ml", "TropiClean", "grooming", "dog", 0.592, 75),
    # Healthcare / Vet Supplies
    ("VT-FL-CT", "فرونت لاين بلس قطط", "Frontline Plus Cat", "Frontline", "healthcare", "cat", 0, 115),
    ("VT-FL-SP", "فرونت لاين سبراي 250 مل", "Frontline Spray 250ml", "Frontline", "healthcare", "dog", 0.25, 145),
    ("VT-AD-DWM", "ادفانتيج ضد البراغيث كلاب وسط", "Advantage Flea Dog Medium", "Bayer", "healthcare", "dog", 0, 99),
    ("VT-AD-CTS", "ادفانتيج ضد البراغيث قطط صغير", "Advantage Flea Cat Small", "Bayer", "healthcare", "cat", 0, 89),
    ("VT-BP-WM01", "بيفار مضاد ديدان كلاب", "Beaphar Wormer Dog", "Beaphar", "healthcare", "dog", 0, 45),
    ("VT-BP-WM02", "بيفار مضاد ديدان قطط", "Beaphar Wormer Cat", "Beaphar", "healthcare", "cat", 0, 39),
    ("VT-VT-OM01", "اوميغا 3 للكلاب 90 كبسولة", "Omega 3 Dog 90 Caps", "Vetoquinol", "healthcare", "dog", 0, 95),
    ("VT-VT-JT01", "مكمل مفاصل للكلاب", "Joint Supplement Dog", "Vetoquinol", "healthcare", "dog", 0, 115),
    ("VT-VT-PB01", "بروبيوتيك للقطط", "Probiotic Cat", "Purina", "healthcare", "cat", 0, 85),
    ("VT-VT-CR01", "كريم حماية الكفوف", "Paw Protection Cream", "Beaphar", "healthcare", "dog", 0, 39),
    ("VT-BP-MC01", "قطرة عين بيفار", "Beaphar Eye Drops", "Beaphar", "healthcare", "cat", 0, 29),
    ("VT-BP-VT01", "فيتامينات بيفار للقطط", "Beaphar Cat Vitamins", "Beaphar", "healthcare", "cat", 0, 39),
    # Toys extras
    ("TY-KG-PUP", "كونغ جرو صغير", "Kong Puppy Small", "Kong", "toys", "dog", 0, 39),
    ("TY-KG-SQ", "كونغ سكويكر", "Kong Squeaker", "Kong", "toys", "dog", 0, 45),
    ("TY-TX-BALL", "كرة تنس للكلاب 3 قطع", "Tennis Ball Dog 3pk", "Trixie", "toys", "dog", 0, 15),
    ("TY-TX-ROPE", "حبل لعب للكلاب", "Dog Rope Toy", "Trixie", "toys", "dog", 0, 25),
    ("TY-CT-MOUSE", "فأر قطيفة للقطط", "Plush Mouse Cat Toy", "Generic", "toys", "cat", 0, 12),
    ("TY-CT-LASER", "مؤشر ليزر للقطط", "Cat Laser Pointer", "Generic", "toys", "cat", 0, 19),
    ("TY-CT-BALL3", "كرات قطط 3 قطع", "Cat Ball Toys 3pk", "Generic", "toys", "cat", 0, 15),
    ("TY-CT-FISH", "لعبة سمكة متحركة للقطط", "Moving Fish Cat Toy", "Generic", "toys", "cat", 0, 35),
    ("TY-TX-FRSBEE", "فريسبي للكلاب", "Dog Frisbee", "Trixie", "toys", "dog", 0, 29),
    # Small Animals extras
    ("SM-VL-GP2", "فيرسيل لاجا خنزير غيني 2.5 كجم", "Versele-Laga Guinea Pig 2.5kg", "Versele-Laga", "small_food", "small", 2.5, 49),
    ("SM-OX-HAY2", "اوكسبو تيموثي 2 كجم", "Oxbow Timothy 2kg", "Oxbow", "small_food", "small", 2, 69),
    ("SM-VL-HM1", "فيرسيل لاجا هامستر 1 كجم", "Versele-Laga Hamster 1kg", "Versele-Laga", "small_food", "small", 1, 35),
    ("SM-TX-WL01", "عجلة هامستر 18 سم", "Hamster Wheel 18cm", "Trixie", "accessories", "small", 0, 25),
    ("SM-TX-CG01", "قفص ارانب كبير", "Large Rabbit Cage", "Trixie", "accessories", "small", 0, 189),
    ("SM-TX-HH01", "بيت هامستر خشبي", "Wooden Hamster House", "Trixie", "accessories", "small", 0, 35),
    # Additional to reach 200+
    ("CF-RC-SN8", "رويال كانين سنسيبل قطط 8 كجم", "Royal Canin Sensible Cat 8kg", "Royal Canin", "cat_food", "cat", 8, 345),
    ("CF-RC-OD4", "رويال كانين آوتدور قطط 4 كجم", "Royal Canin Outdoor Cat 4kg", "Royal Canin", "cat_food", "cat", 4, 210),
    ("CF-PO-AD7", "بورينا وان بالغ 7 كجم", "Purina ONE Adult Cat 7kg", "Purina", "cat_food", "cat", 7, 175),
    ("CF-SC-KT2", "شيسير كيتن 2 كجم", "Schesir Kitten 2kg", "Schesir", "cat_food", "cat", 2, 125),
    ("CF-MO-SH3", "مي-او عناية الشعر 3 كجم", "Me-O Hairball 3kg", "Me-O", "cat_food", "cat", 3, 85),
    ("WC-SC-SM100", "شيسير سالمون معلب 100 جرام", "Schesir Salmon Can 100g", "Schesir", "cat_food_wet", "cat", 0.1, 13),
    ("WC-RC-KT85", "رويال كانين كيتن رطب 85 جرام", "Royal Canin Kitten Wet 85g", "Royal Canin", "cat_food_wet", "cat", 0.085, 10),
    ("WC-WH-SH85", "ويسكاس جمبري معلب 85 جرام", "Whiskas Shrimp Pouch 85g", "Whiskas", "cat_food_wet", "cat", 0.085, 6),
    ("LT-EC-FRS6", "ايفر كلين منعش 6 لتر", "Ever Clean Fresh 6L", "Ever Clean", "litter", "cat", 6, 62),
    ("LT-CB-PN5", "رمل صنوبر للقطط 5 لتر", "Pine Cat Litter 5L", "Cat Best", "litter", "cat", 5, 42),
    ("LT-TF-LV6", "رمل توفو لافندر 6 لتر", "Tofu Lavender Litter 6L", "Generic", "litter", "cat", 6, 48),
    ("DF-RC-LB15", "رويال كانين لابرادور 12 كجم", "Royal Canin Labrador 12kg", "Royal Canin", "dog_food", "dog", 12, 355),
    ("DF-JO-SN12", "جوسيرا سنسيبلس 12 كجم", "Josera Sensible 12kg", "Josera", "dog_food", "dog", 12, 235),
    ("DF-BR-AD3", "بريت بريميوم بالغ 3 كجم", "Brit Premium Adult 3kg", "Brit", "dog_food", "dog", 3, 89),
    ("DF-PD-SN10", "بيدقري سناك كلاب 500 جرام", "Pedigree Snack Dog 500g", "Pedigree", "dog_food", "dog", 0.5, 22),
    ("WD-PD-BF400", "بيدقري لحم بقر معلب 400 جرام", "Pedigree Beef Can 400g", "Pedigree", "dog_food_wet", "dog", 0.4, 13),
    ("WD-RC-MX85", "رويال كانين ماكسي رطب 140 جرام", "Royal Canin Maxi Wet 140g", "Royal Canin", "dog_food_wet", "dog", 0.14, 12),
    ("WD-HS-PUP370", "هيلز جرو رطب 370 جرام", "Hills Puppy Wet 370g", "Hills", "dog_food_wet", "dog", 0.37, 16),
    ("BD-ZP-PR2", "زوبريم بريميوم كوكتيل 2 كجم", "Zupreem Premium Cockatiel 2kg", "Zupreem", "bird_food", "bird", 2, 79),
    ("BD-VL-AF1", "فيرسيل لاجا افريكان 1 كجم", "Versele-Laga African 1kg", "Versele-Laga", "bird_food", "bird", 1, 55),
    ("BD-VK-SN01", "فيتاكرافت سناك للطيور 100 جرام", "Vitakraft Bird Snack 100g", "Vitakraft", "bird_food", "bird", 0.1, 18),
    ("BD-TX-PH01", "مجثم طيور خشبي طبيعي", "Natural Wood Perch", "Trixie", "accessories", "bird", 0, 15),
    ("BD-TX-NB01", "عش تربية طيور", "Bird Breeding Nest", "Trixie", "accessories", "bird", 0, 29),
    ("FS-TT-CT50", "تترا كاتفيش 50 جرام", "Tetra Catfish 50g", "Tetra", "fish_food", "fish", 0.05, 22),
    ("FS-TT-PL100", "تترا بلانتا مين 100 مل", "Tetra PlantaMin 100ml", "Tetra", "fish_food", "fish", 0.1, 39),
    ("FS-AP-PH237", "اختبار PH من API", "API pH Test Kit", "API", "equipment", "fish", 0, 55),
    ("FS-AQ-GR5", "حصى ملونة احواض 5 كجم", "Colored Aquarium Gravel 5kg", "Generic", "accessories", "fish", 5, 29),
    ("FS-AQ-BG01", "خلفية احواض 60 سم", "Aquarium Background 60cm", "Generic", "accessories", "fish", 0, 19),
    ("RP-EX-HY01", "مرطب للزواحف", "Reptile Humidifier", "Exo Terra", "reptile", "reptile", 0, 119),
    ("RP-EX-FD02", "دود الوجبات المجفف 30 جرام", "Dried Mealworms 30g", "Exo Terra", "reptile", "reptile", 0.03, 29),
    ("RP-EX-HG01", "مخبأ صخري للزواحف كبير", "Rock Hide Large", "Exo Terra", "reptile", "reptile", 0, 49),
    ("GR-BP-PP01", "بخاخ عطري بيفار للكلاب", "Beaphar Dog Perfume Spray", "Beaphar", "grooming", "dog", 0, 35),
    ("GR-TX-DM01", "مزيل عقد شعر للكلاب", "Dog Detangling Spray", "Trixie", "grooming", "dog", 0, 45),
    ("GR-SF-PW01", "بودرة كفوف حماية", "Paw Protection Powder", "Safari", "grooming", "dog", 0, 29),
    ("VT-NX-FL01", "نيكسجارد ضد البراغيث كلاب", "Nexgard Flea Dog", "Merial", "healthcare", "dog", 0, 135),
    ("VT-BP-CL01", "بيفار مضاد حشرات طوق قطط", "Beaphar Flea Collar Cat", "Beaphar", "healthcare", "cat", 0, 35),
    ("VT-BP-CL02", "بيفار مضاد حشرات طوق كلاب", "Beaphar Flea Collar Dog", "Beaphar", "healthcare", "dog", 0, 39),
    ("VT-VT-LV01", "مكمل كبد للكلاب", "Liver Supplement Dog", "Vetoquinol", "healthcare", "dog", 0, 79),
    ("TY-CT-SCR01", "لوح خدش من الكرتون للقطط", "Cardboard Cat Scratcher", "Generic", "toys", "cat", 0, 19),
    ("TY-CT-TNL02", "نفق قطط مع كرة", "Cat Tunnel with Ball", "Generic", "toys", "cat", 0, 39),
    ("TY-TX-CHEW", "عظمة مضغ للكلاب كبير", "Dog Chew Bone Large", "Trixie", "toys", "dog", 0, 19),
    ("TY-KG-DN01", "كونغ دنتل ستيك", "Kong Dental Stick", "Kong", "toys", "dog", 0, 55),
    ("SM-VL-CH2", "فيرسيل لاجا شنشيلا 2 كجم", "Versele-Laga Chinchilla 2kg", "Versele-Laga", "small_food", "small", 2, 55),
    ("SM-OX-PL1", "اوكسبو بيليتس ارانب 1 كجم", "Oxbow Rabbit Pellets 1kg", "Oxbow", "small_food", "small", 1, 45),
    ("SM-TX-BT01", "زجاجة مياه للقوارض 250 مل", "Rodent Water Bottle 250ml", "Trixie", "accessories", "small", 0, 15),
    ("DA-TX-RMP01", "رامب كلاب للسيارة", "Dog Car Ramp", "Trixie", "accessories", "dog", 0, 199),
    ("CA-CT-TR02", "شجرة قطط صغيرة 80 سم", "Small Cat Tree 80cm", "Generic", "accessories", "cat", 0, 159),
    ("CA-CT-CG01", "حقيبة حمل قطط شفافة", "Transparent Cat Carrier", "Generic", "accessories", "cat", 0, 109),
]

# get_stock_signal moved to /app/backend/core/utils.py (Feb 2026 refactor)

async def seed_database():
    if await db.stores.count_documents({}) > 0:
        return
    # Real-data deployments must set SEED_DEMO_DATA=false: the demo seed writes
    # synthetic products/snapshots that would pollute live crawl analytics.
    # Stores are seeded by ensure_stores() (store_registry.py) either way.
    if os.environ.get("SEED_DEMO_DATA", "true").lower() in ("false", "0", "no"):
        logger.info("SEED_DEMO_DATA=false — skipping synthetic demo seed")
        return
    logger.info("Seeding Daleel database...")
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
    all_products_data = PRODUCTS_SEED + EXTRA_PRODUCT_TEMPLATES
    p1_stores = [s for s in store_ids if s["priority"] == 1]
    p2_stores = [s for s in store_ids if s["priority"] == 2]
    all_snapshots = []

    for tup in all_products_data:
        sku, name_ar, name_en, brand, category, animal, weight, base_price = tup
        pid = str(uuid.uuid4())
        await db.products.insert_one({
            "id": pid, "sku": sku, "name_ar": name_ar, "name_en": name_en,
            "brand": brand, "category": category, "animal_type": animal,
            "weight_kg": weight, "image_url": "", "first_seen_at": (now - timedelta(days=45)).isoformat(),
        })

        # Assign to stores: 2-4 P1 stores + 1-3 P2 stores
        n_p1 = random.randint(2, min(4, len(p1_stores)))
        n_p2 = random.randint(1, min(3, len(p2_stores)))
        assigned = random.sample(p1_stores, n_p1) + random.sample(p2_stores, n_p2)

        for store in assigned:
            tier = random.choices([1, 2, 3], weights=[55, 30, 15])[0]
            qty = random.randint(40, 250)
            price = round(base_price * random.uniform(0.90, 1.12), 2)

            day = 90
            while day >= 0:
                crawled_at = now - timedelta(days=day, hours=random.randint(0, 12))
                sold = random.randint(0, min(12, qty))
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

    # Note: admin user seeding moved to seed_super_admin() (always runs, idempotent).
    # The legacy admin@daleelpets.com account is deleted there.

    # Create indexes
    await db.users.create_index("email", unique=True)
    await db.product_snapshots.create_index([("sku", 1), ("crawled_at", -1)])
    await db.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)])
    await db.product_snapshots.create_index("product_id")
    # Perf sprint Feb 2026 — leading-by-date compound indexes for the dashboard aggregations.
    # Insight pipelines all start with `{"$match": {"crawled_at": {"$gte": since}}}` and these
    # let MongoDB satisfy that match + the secondary group key from index alone.
    await db.product_snapshots.create_index([("crawled_at", -1), ("store_id", 1)])
    await db.product_snapshots.create_index([("crawled_at", -1), ("sku", 1)])
    await db.product_snapshots.create_index([("crawled_at", -1), ("confidence_score", 1)])
    await db.proxy_usage.create_index("crawled_at")
    await db.products.create_index("sku", unique=True)
    await db.stores.create_index("domain", unique=True)

    logger.info(f"Seeded {len(STORES_SEED)} stores, {len(all_products_data)} products, {len(all_snapshots)} snapshots")


async def ensure_stores():
    """Ensure all required stores exist and have correct configuration.

    Store registry moved to store_registry.py (single source of truth shared
    with run_market_crawl.py). This wrapper keeps the startup call site stable.
    """
    await registry_ensure_stores(db)

# ── Auth Routes ─────────────────────────────────────────────
@router.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, data: AuthIn, response: Response):
    email = data.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    # Anyone registering via the public endpoint gets ZERO page access until super_admin grants.
    # The super_admin email is reserved — it can never be self-registered.
    if is_super_admin_email(email):
        raise HTTPException(403, "This email is reserved")
    doc = {
        "email": email,
        "password_hash": hash_pw(data.password),
        "name": data.name or email.split("@")[0],
        "role": "user",
        "allowed_pages": [],
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.users.insert_one(doc)
    uid = str(result.inserted_id)
    token = make_token(uid, email)
    response.set_cookie("daleel_token", token, httponly=True, samesite="none", secure=True, max_age=86400, path="/")
    return {"token": token, "user": {"id": uid, "email": email, "name": doc["name"], "role": "user", "allowed_pages": []}}

@router.post("/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, data: AuthIn, response: Response):
    email = data.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not check_pw(data.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    uid = str(user["_id"])
    role = user.get("role", "user")
    allowed = ALL_PAGES if role == "super_admin" else list(user.get("allowed_pages", []) or [])
    token = make_token(uid, email)
    response.set_cookie("daleel_token", token, httponly=True, samesite="none", secure=True, max_age=86400, path="/")
    return {
        "token": token,
        "user": {
            "id": uid,
            "email": email,
            "name": user.get("name", ""),
            "role": role,
            "allowed_pages": allowed,
        },
    }

@router.get("/auth/me")
async def me(user=Depends(get_user)):
    return user

@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("daleel_token", path="/")
    return {"message": "Logged out"}

@router.get("/protected")
async def protected(user=Depends(get_user)):
    return {"message": "Authenticated", "user": user}

# ── Super Admin: User Management ─────────────────────────────
def _serialize_user(u: dict) -> dict:
    """Strip _id and password_hash for safe JSON responses."""
    role = u.get("role", "user")
    return {
        "id": str(u["_id"]),
        "email": u.get("email", ""),
        "name": u.get("name", ""),
        "role": role,
        "allowed_pages": ALL_PAGES if role == "super_admin" else list(u.get("allowed_pages", []) or []),
        "created_at": (u.get("created_at").isoformat() if isinstance(u.get("created_at"), datetime) else u.get("created_at")),
        "is_super_admin": is_super_admin_email(u.get("email", "")),
    }


def _validate_pages(pages: List[str]) -> List[str]:
    return [p for p in (pages or []) if p in ALL_PAGES]


@router.get("/admin/users")
async def admin_list_users(user=Depends(require_super_admin)):
    cursor = db.users.find({}, {"password_hash": 0}).sort("created_at", -1)
    out = []
    async for u in cursor:
        out.append(_serialize_user(u))
    return {"users": out, "all_pages": ALL_PAGES, "valid_roles": VALID_ROLES}


@router.post("/admin/users")
async def admin_create_user(data: AdminCreateUserIn, _=Depends(require_super_admin)):
    email = data.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(400, "Invalid email")
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if data.role not in ("admin", "user"):
        raise HTTPException(400, f"Role must be 'admin' or 'user' (got '{data.role}')")
    if is_super_admin_email(email):
        raise HTTPException(403, "This email is reserved for the super admin")
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    doc = {
        "email": email,
        "password_hash": hash_pw(data.password),
        "name": data.name or email.split("@")[0],
        "role": data.role,
        "allowed_pages": _validate_pages(data.allowed_pages or []),
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_user(doc)


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, _=Depends(require_super_admin)):
    try:
        target = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(400, "Invalid user id")
    if not target:
        raise HTTPException(404, "User not found")
    if is_super_admin_email(target.get("email", "")):
        raise HTTPException(403, "The super admin cannot be deleted")
    await db.users.delete_one({"_id": ObjectId(user_id)})
    return {"deleted": True, "id": user_id}


@router.patch("/admin/users/{user_id}/password")
async def admin_update_password(user_id: str, data: AdminUpdatePasswordIn, current_user=Depends(require_super_admin)):
    try:
        target = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(400, "Invalid user id")
    if not target:
        raise HTTPException(404, "User not found")
    # The super_admin password can only be changed by the super_admin themselves (i.e. when target == current_user)
    if is_super_admin_email(target.get("email", "")) and str(target["_id"]) != current_user["id"]:
        raise HTTPException(403, "Only the super admin can change their own password")
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"password_hash": hash_pw(data.password)}})
    return {"updated": True, "id": user_id}


@router.patch("/admin/users/{user_id}/role")
async def admin_update_role(user_id: str, data: AdminUpdateRoleIn, _=Depends(require_super_admin)):
    if data.role not in ("admin", "user"):
        raise HTTPException(400, "Role must be 'admin' or 'user'")
    try:
        target = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(400, "Invalid user id")
    if not target:
        raise HTTPException(404, "User not found")
    if is_super_admin_email(target.get("email", "")):
        raise HTTPException(403, "The super admin role cannot be changed")
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"role": data.role}})
    updated = await db.users.find_one({"_id": ObjectId(user_id)})
    return _serialize_user(updated)


@router.patch("/admin/users/{user_id}/pages")
async def admin_update_pages(user_id: str, data: AdminUpdatePagesIn, _=Depends(require_super_admin)):
    try:
        target = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(400, "Invalid user id")
    if not target:
        raise HTTPException(404, "User not found")
    if is_super_admin_email(target.get("email", "")):
        raise HTTPException(403, "The super admin always has access to every page")
    pages = _validate_pages(data.allowed_pages)
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"allowed_pages": pages}})
    updated = await db.users.find_one({"_id": ObjectId(user_id)})
    return _serialize_user(updated)


@router.get("/admin/proxy-usage")
async def admin_proxy_usage(user=Depends(get_user)):
    """Webshare residential proxy bandwidth dashboard. Admin/super-admin only."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    pipeline_today = [
        {"$match": {"crawled_at": {"$gte": day_start}}},
        {"$group": {"_id": None, "total": {"$sum": "$bytes_estimate"}}},
    ]
    pipeline_month = [
        {"$match": {"crawled_at": {"$gte": month_start}}},
        {"$group": {"_id": None, "total": {"$sum": "$bytes_estimate"}}},
    ]
    today_rows = await db.proxy_usage.aggregate(pipeline_today).to_list(length=1)
    month_rows = await db.proxy_usage.aggregate(pipeline_month).to_list(length=1)

    bytes_today = int(today_rows[0]["total"]) if today_rows else 0
    bytes_month = int(month_rows[0]["total"]) if month_rows else 0

    monthly_limit_gb = 50
    monthly_limit_bytes = monthly_limit_gb * 1024 * 1024 * 1024
    pct_used = round((bytes_month / monthly_limit_bytes) * 100, 4) if monthly_limit_bytes else 0.0

    proxy_store_cursor = db.stores.find({"use_proxy": True}, {"_id": 0, "domain": 1, "name": 1})
    proxy_stores = []
    async for s in proxy_store_cursor:
        proxy_stores.append(s.get("domain", ""))

    return {
        "proxy_enabled_stores": proxy_stores,
        "estimated_bytes_today": bytes_today,
        "estimated_bytes_this_month": bytes_month,
        "monthly_limit_gb": monthly_limit_gb,
        "pct_used": pct_used,
        "stores_using_proxy_count": len(proxy_stores),
    }


async def seed_super_admin():
    """Idempotent super admin seed.

    - Always force-updates `a.disi@taqueen.sa` to the hardcoded password (so the
      password can never be drifted by anyone).
    - Removes the legacy `admin@daleelpets.com` account if it exists.
    """
    now = datetime.now(timezone.utc)
    existing = await db.users.find_one({"email": SUPER_ADMIN_EMAIL.lower()})
    payload = {
        "email": SUPER_ADMIN_EMAIL.lower(),
        "password_hash": hash_pw(SUPER_ADMIN_PASSWORD),
        "name": "Super Admin",
        "role": "super_admin",
        "allowed_pages": ALL_PAGES,
    }
    if existing is None:
        payload["created_at"] = now
        await db.users.insert_one(payload)
        logger.info(f"[RBAC] Seeded super admin {SUPER_ADMIN_EMAIL}")
    else:
        await db.users.update_one(
            {"_id": existing["_id"]},
            {"$set": payload},
        )
        logger.info(f"[RBAC] Refreshed super admin {SUPER_ADMIN_EMAIL}")

    # Remove legacy admin account per user instruction
    legacy = await db.users.find_one({"email": LEGACY_ADMIN_EMAIL.lower()})
    if legacy:
        await db.users.delete_one({"_id": legacy["_id"]})
        logger.info(f"[RBAC] Removed legacy admin {LEGACY_ADMIN_EMAIL}")

# ── Crawlers imported from crawlers.py ───────────────────────
# crawl_store_waterfall, process_crawled_products, extract_brand,
# guess_category, guess_animal, extract_weight — all imported at top

# ── Scheduler Helpers ────────────────────────────────────────
async def scheduled_crawl_job(store_id: str):
    """Run by APScheduler for automated crawls."""
    global crawl_paused
    if crawl_paused:
        logger.info(f"Scheduler: Skipping {store_id} — crawls paused")
        return
    store = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not store or not store.get("is_active", True):
        return
    platform = store.get("platform", "").lower()
    logger.info(f"[Scheduler] Cron fired: {store.get('domain')} at {datetime.now(timezone.utc).isoformat()}")
    await crawl_store_waterfall(db, store)
    # Perf sprint Feb 2026 — invalidate insights/discounts TTL cache so the new
    # snapshots show up immediately on the dashboard instead of waiting up to 60s.
    cache_clear()
    # iter30 — rebuild THIS store's precomputed metric rollups + coverage from the
    # fresh snapshots, before the page cache recompute reads them. Bounded per-store
    # pass; failure is logged and never blocks the crawl.
    try:
        await _recompute_store_metrics(db, store_id)
    except Exception:
        logger.exception("[Metrics] per-store rebuild failed after crawl of %s", store_id)
    # iter25 — refresh the my-products dashboard cache. Debounced so the daily
    # 44-store staggered crawl burst triggers ~1 recompute, not one per store.
    await maybe_recompute_dashboard_cache(db)
    # iter26 — refresh the Insights / Price-Intel page caches (same debounce).
    await maybe_recompute_page_caches(db)

# ── Daily cron schedule (Feb 2026) ──────────────────────────
# All active stores crawl ONCE per day at 04:00–04:55 KSA time (UTC+3 → 01:00–01:55 UTC),
# staggered in 5-minute slots so the backend, proxy pool, and target servers never see
# concurrent load. Priority field still exists in DB for future use but no longer drives
# scheduling.
DAILY_CRAWL_SCHEDULE = [
    # (domain,            UTC hour, UTC minute) — KSA = UTC + 3
    ("zarafaksa.com",     1,  0),   # 04:00 KSA
    ("petsysa.com",       1,  5),   # 04:05 KSA
    ("lanapets.com",      1, 10),   # 04:10 KSA
    ("matjarpanda.com",   1, 15),   # 04:15 KSA
    ("caty-store.com",    1, 20),   # 04:20 KSA
    ("aleef.com",         1, 25),   # 04:25 KSA
    ("cutecat.com.sa",    1, 30),   # 04:30 KSA
    ("cutepets.com.sa",   1, 35),   # 04:35 KSA
    ("hamtaro.sa",        1, 40),   # 04:40 KSA
    ("hobbapet.com",      1, 45),   # 04:45 KSA
    ("mowkly.com",        1, 50),   # 04:50 KSA
    ("pets-houses.com",   1, 55),   # 04:55 KSA
]
DAILY_CRAWL_BY_DOMAIN = {d: (h, m) for d, h, m in DAILY_CRAWL_SCHEDULE}


def register_crawl_job(store_id, store_name, store_domain):
    """Register a daily cron job at the store's assigned 04:00–04:55 KSA slot.

    Stores not in the hardcoded schedule (e.g. newly added via /api/stores)
    fall back to 02:00 UTC (05:00 KSA) so they still crawl daily without
    colliding with the scheduled window.
    """
    job_id = f"crawl_{store_id}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    hour, minute = DAILY_CRAWL_BY_DOMAIN.get(store_domain, (2, 0))
    scheduler.add_job(
        scheduled_crawl_job,
        CronTrigger(hour=hour, minute=minute, timezone="UTC"),
        id=job_id, args=[store_id],
        replace_existing=True,
    )
    ksa_hh = (hour + 3) % 24
    logger.info(
        f"[Scheduler] Registered {store_name} ({store_domain}) — "
        f"daily at {hour:02d}:{minute:02d} UTC / {ksa_hh:02d}:{minute:02d} KSA"
    )

def unregister_crawl_job(store_id):
    try:
        scheduler.remove_job(f"crawl_{store_id}")
    except Exception:
        pass

def get_next_run(store_id):
    try:
        job = scheduler.get_job(f"crawl_{store_id}")
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    except Exception:
        pass
    return None

# ── Store Routes ────────────────────────────────────────────
@router.get("/stores")
async def list_stores(user=Depends(get_user)):
    stores = await db.stores.find({}, {"_id": 0}).sort("name", 1).to_list(100)
    for s in stores:
        s["product_count"] = await db.product_snapshots.distinct("sku", {"store_id": s["id"]})
        s["product_count"] = len(s["product_count"])
        s["next_crawl_at"] = get_next_run(s["id"])
        # Daily cron schedule (Feb 2026) — every store crawls once per day at
        # its assigned 04:00–04:55 KSA slot. Surface the assigned slot so the
        # frontend can render "Daily at 04:15 KSA" etc.
        slot = DAILY_CRAWL_BY_DOMAIN.get(s.get("domain", ""))
        if slot:
            utc_h, utc_m = slot
            ksa_h = (utc_h + 3) % 24
            s["crawl_frequency_label"] = f"Daily at {ksa_h:02d}:{utc_m:02d} KSA"
            s["crawl_schedule_ksa"] = f"{ksa_h:02d}:{utc_m:02d}"
            s["crawl_schedule_utc"] = f"{utc_h:02d}:{utc_m:02d}"
        else:
            s["crawl_frequency_label"] = "Daily at 05:00 KSA"
            s["crawl_schedule_ksa"] = "05:00"
            s["crawl_schedule_utc"] = "02:00"
        # Strip encrypted credential fields — never send to frontend
        for k in ["tier4_email", "tier4_password", "tier4_phone", "tier4_session_cookies"]:
            s.pop(k, None)
        # Default tier4 status
        if "tier4_session_status" not in s:
            s["tier4_session_status"] = "not_configured"
    s_paused = crawl_paused
    return {"stores": stores, "crawl_paused": s_paused}

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
    register_crawl_job(doc["id"], doc["name"], doc["domain"])
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
    unregister_crawl_job(store_id)
    return {"message": "Deleted"}

@router.post("/stores/{store_id}/crawl")
async def trigger_crawl(store_id: str, user=Depends(get_user)):
    store = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not store:
        raise HTTPException(404, "Store not found")
    result = await crawl_store_waterfall(db, store)
    cache_clear()  # invalidate insight/discount TTL cache after new snapshots land
    return {
        "message": f"Crawl {'completed' if result.get('tier_used') else 'attempted'} for {store['name']}",
        "store_id": store_id,
        "tier_used": result.get("tier_used"),
        "http_status": result.get("http_status"),
        "products_found": result.get("products_found", 0),
        "products_new": result.get("products_new", 0),
        "snapshots_created": result.get("snapshots_created", 0),
        "error": result.get("error"),
        "last_crawled_at": result.get("completed_at"),
        "duration_secs": result.get("duration_secs", 0),
    }

@router.get("/stores/{store_id}/crawl-logs")
async def get_crawl_logs(store_id: str, limit: int = Query(10), user=Depends(get_user)):
    logs = await db.crawl_logs.find({"store_id": store_id}, {"_id": 0}).sort("completed_at", -1).limit(limit).to_list(limit)
    return logs

@router.post("/scheduler/toggle-pause")
async def toggle_pause_crawls(user=Depends(get_user)):
    global crawl_paused
    crawl_paused = not crawl_paused
    return {"crawl_paused": crawl_paused, "message": f"Crawls {'paused' if crawl_paused else 'resumed'}"}

@router.get("/scheduler/status")
async def scheduler_status(user=Depends(get_user)):
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return {"crawl_paused": crawl_paused, "jobs": jobs, "total_jobs": len(jobs)}


@router.get("/data-freshness")
@ttl_cache(60)
async def data_freshness(user=Depends(get_user)):
    """Aggregated crawl-data freshness for the dashboard banner.

    Returns:
      • overall.bucket  → 'today' | 'this_week' | 'this_month' | 'stale' | 'no_data'
      • overall.latest  → most recent COMPETITOR snapshot (excludes own store)
      • overall.oldest  → oldest "latest" among competitor stores (the bottleneck)
      • stores[]        → per-store breakdown (name, last_crawled_at, age_days, bucket, is_own_store)
      • next_run        → next scheduled crawl time (ISO) — null if paused or unscheduled
      • crawl_paused    → bool
    """
    now = datetime.now(timezone.utc)

    # Per-store latest snapshot (one Mongo aggregation)
    pipeline = [
        {"$group": {
            "_id": "$store_id",
            "store_name": {"$first": "$store_name"},
            "latest": {"$max": "$crawled_at"},
            "snapshot_count": {"$sum": 1},
        }},
    ]
    rows = await db.product_snapshots.aggregate(pipeline).to_list(200)
    latest_by_store = {r["_id"]: r for r in rows}

    # Resolve store names + own_store flag from db.stores (authoritative)
    stores_meta = []
    async for s in db.stores.find({"is_active": True}, {"_id": 0, "id": 1, "name": 1, "is_own_store": 1}):
        stores_meta.append(s)

    stores_out = []
    competitor_latests = []
    own_latest = None

    def _to_dt(v):
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if isinstance(v, str):
            try:
                d = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        return None

    def _bucket(latest_dt):
        if latest_dt is None:
            return "no_data", None
        age = now - latest_dt
        age_days = age.total_seconds() / 86400.0
        if age < timedelta(hours=24):
            return "today", age_days
        if age < timedelta(days=7):
            return "this_week", age_days
        if age < timedelta(days=30):
            return "this_month", age_days
        return "stale", age_days

    for s in stores_meta:
        row = latest_by_store.get(s["id"])
        latest_iso = None
        latest_dt = None
        snap_count = 0
        if row:
            latest_dt = _to_dt(row.get("latest"))
            if latest_dt:
                latest_iso = latest_dt.isoformat()
            snap_count = int(row.get("snapshot_count") or 0)
        bucket, age_days = _bucket(latest_dt)
        is_own = bool(s.get("is_own_store"))
        stores_out.append({
            "store_id": s["id"],
            "store_name": s.get("name", ""),
            "is_own_store": is_own,
            "last_crawled_at": latest_iso,
            "age_days": round(age_days, 1) if age_days is not None else None,
            "bucket": bucket,
            "snapshot_count": snap_count,
        })
        if is_own:
            if latest_dt and (own_latest is None or latest_dt > own_latest):
                own_latest = latest_dt
        else:
            if latest_dt:
                competitor_latests.append(latest_dt)

    # Sort: stale first (so the banner highlights the worst offenders) but keep own store on top
    stores_out.sort(key=lambda x: (
        0 if x["is_own_store"] else 1,
        -(x["age_days"] or 0) if x["bucket"] != "no_data" else 9999,
    ))

    # Overall freshness is governed by the most-stale competitor store
    # (the bottleneck — if any competitor is 60d stale, the dashboard is 60d stale).
    competitor_oldest = min(competitor_latests) if competitor_latests else None
    competitor_newest = max(competitor_latests) if competitor_latests else None

    overall_bucket, overall_age_days = _bucket(competitor_oldest)
    overall = {
        "bucket": overall_bucket,
        "age_days": round(overall_age_days, 1) if overall_age_days is not None else None,
        "latest_competitor_crawl": competitor_newest.isoformat() if competitor_newest else None,
        "oldest_competitor_crawl": competitor_oldest.isoformat() if competitor_oldest else None,
        "own_store_last_sync": own_latest.isoformat() if own_latest else None,
        "competitor_store_count": len(competitor_latests),
    }

    # Next scheduled crawl: earliest crawl_* job in APScheduler
    next_run_dt = None
    if not crawl_paused and scheduler.running:
        for job in scheduler.get_jobs():
            if not str(job.id).startswith("crawl_"):
                continue
            if job.next_run_time is None:
                continue
            nr = job.next_run_time
            if nr.tzinfo is None:
                nr = nr.replace(tzinfo=timezone.utc)
            if next_run_dt is None or nr < next_run_dt:
                next_run_dt = nr

    # ── sync_health (Feb 2026 hardening) ──
    # Combines two signals so silent failures become visible:
    #   1. db.sync_runs — exception traces from inside the chain (modes 1 & 2)
    #   2. APScheduler next_run_time + age-of-last-run — catches dead scheduler
    #      or wiped state after a pod restart (modes 3 & 4) even when zero
    #      sync_runs rows exist.
    sync_health = {
        "last_run": None,
        "last_run_age_hours": None,
        "last_sync_status": None,
        "last_match_status": None,
        "last_sync_updated": 0,
        "last_match_added": 0,
        "last_sync_source": None,
        "last_sync_warning": None,
        "next_run_expected": None,
        "scheduler_running": bool(scheduler.running),
        "is_stale": False,  # True if last_run is older than 2× the 6h interval (12h)
        "alarm": None,  # Human-readable reason if banner should flip red
    }
    try:
        last_run = await db.sync_runs.find_one({}, sort=[("started_at", -1)])
    except Exception:
        last_run = None
    if last_run:
        started = last_run.get("started_at")
        if isinstance(started, datetime):
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            sync_health["last_run"] = started.isoformat()
            age_h = (now - started).total_seconds() / 3600
            sync_health["last_run_age_hours"] = round(age_h, 1)
            sync_health["is_stale"] = age_h > 12  # 2× the 6h schedule
        sync_health["last_sync_status"] = last_run.get("sync_status")
        sync_health["last_match_status"] = last_run.get("match_status")
        sync_health["last_sync_updated"] = int(last_run.get("sync_updated") or 0)
        sync_health["last_match_added"] = int(last_run.get("match_added") or 0)
        sync_health["last_sync_source"] = last_run.get("sync_source")
        sync_health["last_sync_warning"] = last_run.get("sync_warning")

    # APScheduler liveness for own_store_sync job
    sync_job = scheduler.get_job("own_store_sync") if scheduler.running else None
    if sync_job and sync_job.next_run_time:
        nr = sync_job.next_run_time
        if nr.tzinfo is None:
            nr = nr.replace(tzinfo=timezone.utc)
        sync_health["next_run_expected"] = nr.isoformat()

    # Compose alarm — banner uses this to flip red
    if not sync_health["scheduler_running"]:
        sync_health["alarm"] = "Scheduler is not running"
    elif sync_job is None:
        sync_health["alarm"] = "own_store_sync job is not registered"
    elif sync_health["last_run"] is None:
        sync_health["alarm"] = "Own-store sync has never run since last deploy"
    elif sync_health["is_stale"]:
        sync_health["alarm"] = f"Last sync was {sync_health['last_run_age_hours']}h ago (expected every 6h)"
    elif sync_health["last_sync_status"] == "error":
        sync_health["alarm"] = "Last sync failed — check sync_runs for traceback"
    elif sync_health["last_sync_status"] == "degraded" or sync_health.get("last_sync_warning"):
        sync_health["alarm"] = sync_health.get("last_sync_warning") or (
            "Own-store sync fell back to public crawl — sold counters are not being "
            "captured and My Revenue / Units Sold KPIs will stall"
        )
    elif sync_health["last_match_status"] == "error":
        sync_health["alarm"] = "Last matcher run failed — check sync_runs for traceback"

    return {
        "overall": overall,
        "stores": stores_out,
        "next_run": next_run_dt.isoformat() if next_run_dt else None,
        "crawl_paused": crawl_paused,
        "sync_health": sync_health,
        "checked_at": now.isoformat(),
    }


# ── Tier 4 Credential Vault ─────────────────────────────────
@router.get("/encryption/verify")
async def verify_encryption(user=Depends(get_user)):
    try:
        test_str = f"verify_{secrets.token_hex(4)}"
        encrypted = encrypt_value(test_str)
        decrypted = decrypt_value(encrypted)
        ok = decrypted == test_str
        return {"status": "active" if ok else "error", "ok": ok}
    except Exception as exc:
        return {"status": "error", "ok": False, "detail": str(exc)}

@router.put("/stores/{store_id}/tier4-credentials")
async def save_tier4_credentials(store_id: str, data: Tier4CredentialsIn, user=Depends(get_user)):
    store = await db.stores.find_one({"id": store_id})
    if not store:
        raise HTTPException(404, "Store not found")
    updates = {}
    if data.email is not None:
        updates["tier4_email"] = encrypt_value(data.email) if data.email else ""
    if data.password is not None:
        updates["tier4_password"] = encrypt_value(data.password) if data.password else ""
    if data.phone is not None:
        updates["tier4_phone"] = encrypt_value(data.phone) if data.phone else ""
    if not updates:
        raise HTTPException(400, "No credentials provided")
    has_any = any(updates.get(k) for k in ["tier4_email", "tier4_password", "tier4_phone"])
    if "tier4_session_status" not in (store or {}):
        updates["tier4_session_status"] = "not_configured"
    if has_any and store.get("tier4_session_status", "not_configured") == "not_configured":
        updates["tier4_session_status"] = "expired"
    await db.stores.update_one({"id": store_id}, {"$set": updates})
    has_email = bool(updates.get("tier4_email") or store.get("tier4_email"))
    has_phone = bool(updates.get("tier4_phone") or store.get("tier4_phone"))
    return {
        "message": "Credentials saved (encrypted)",
        "has_email": has_email,
        "has_phone": has_phone,
        "session_status": updates.get("tier4_session_status", store.get("tier4_session_status", "not_configured")),
    }

@router.get("/stores/{store_id}/tier4-status")
async def get_tier4_status(store_id: str, user=Depends(get_user)):
    store = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not store:
        raise HTTPException(404, "Store not found")
    has_email = bool(store.get("tier4_email"))
    has_phone = bool(store.get("tier4_phone"))
    has_password = bool(store.get("tier4_password"))
    phone_last4 = ""
    if has_phone:
        try:
            phone_plain = decrypt_value(store["tier4_phone"])
            phone_last4 = phone_plain[-4:] if len(phone_plain) >= 4 else "****"
        except Exception:
            phone_last4 = "****"
    email_masked = ""
    if has_email:
        try:
            email_plain = decrypt_value(store["tier4_email"])
            parts = email_plain.split("@")
            email_masked = f"{parts[0][:2]}***@{parts[1]}" if len(parts) == 2 else "***"
        except Exception:
            email_masked = "***"
    session_status = store.get("tier4_session_status", "not_configured")
    session_expiry = store.get("tier4_session_expiry")
    if session_status == "active" and session_expiry:
        exp = session_expiry if isinstance(session_expiry, datetime) else datetime.fromisoformat(session_expiry)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            session_status = "expired"
            await db.stores.update_one({"id": store_id}, {"$set": {"tier4_session_status": "expired"}})
    return {
        "store_id": store_id,
        "store_name": store.get("name"),
        "platform": store.get("platform"),
        "has_email": has_email,
        "email_masked": email_masked,
        "has_password": has_password,
        "has_phone": has_phone,
        "phone_last4": phone_last4,
        "session_status": session_status,
        "session_expiry": session_expiry.isoformat() if isinstance(session_expiry, datetime) else session_expiry,
        "last_auth_crawl": store.get("tier4_last_auth_crawl"),
        "working_login_url": store.get("tier4_working_login_url"),
    }

@router.post("/stores/{store_id}/tier4-test-login")
async def test_tier4_login(store_id: str, user=Depends(get_user)):
    store = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not store:
        raise HTTPException(404, "Store not found")
    if not store.get("tier4_email") and not store.get("tier4_phone"):
        raise HTTPException(400, "No credentials configured for this store")
    await db.otp_requests.update_many(
        {"store_id": store_id, "status": "pending"},
        {"$set": {"status": "expired"}}
    )
    asyncio.create_task(_run_tier4_login(store_id))
    return {
        "message": f"Login attempt started for {store['name']} — check OTP banner if OTP is required",
        "store_id": store_id,
        "session_status": store.get("tier4_session_status", "not_configured"),
    }

@router.post("/stores/{store_id}/tier4-clear-session")
async def clear_tier4_session(store_id: str, user=Depends(get_user)):
    store = await db.stores.find_one({"id": store_id})
    if not store:
        raise HTTPException(404, "Store not found")
    updates = {
        "tier4_session_cookies": "",
        "tier4_session_expiry": None,
        "tier4_session_status": "expired" if (store.get("tier4_email") or store.get("tier4_phone")) else "not_configured",
        "tier4_working_login_url": "",
    }
    await db.stores.update_one({"id": store_id}, {"$set": updates})
    return {"message": "Session cleared", "session_status": updates["tier4_session_status"]}

@router.get("/tier4/summary")
async def tier4_summary(user=Depends(get_user)):
    stores = await db.stores.find({"is_active": True}, {"_id": 0, "id": 1, "name": 1, "platform": 1, "tier4_email": 1, "tier4_phone": 1, "tier4_session_status": 1, "tier4_session_expiry": 1, "tier4_last_auth_crawl": 1}).sort("name", 1).to_list(50)
    result = []
    for s in stores:
        has_email = bool(s.get("tier4_email"))
        has_phone = bool(s.get("tier4_phone"))
        phone_last4 = ""
        if has_phone:
            try:
                phone_plain = decrypt_value(s["tier4_phone"])
                phone_last4 = phone_plain[-4:] if len(phone_plain) >= 4 else "****"
            except Exception:
                phone_last4 = "****"
        email_masked = ""
        if has_email:
            try:
                email_plain = decrypt_value(s["tier4_email"])
                parts = email_plain.split("@")
                email_masked = f"{parts[0][:2]}***@{parts[1]}" if len(parts) == 2 else "***"
            except Exception:
                email_masked = "***"
        session_status = s.get("tier4_session_status", "not_configured")
        result.append({
            "store_id": s["id"],
            "store_name": s["name"],
            "platform": s.get("platform", ""),
            "has_email": has_email,
            "email_masked": email_masked,
            "has_phone": has_phone,
            "phone_last4": phone_last4,
            "session_status": session_status,
            "session_expiry": s.get("tier4_session_expiry"),
            "last_auth_crawl": s.get("tier4_last_auth_crawl"),
        })
    return result


# ── OTP Handling ────────────────────────────────────────────
# In-memory store for OTP codes submitted by user (cleared after use)
_otp_inbox = {}  # {store_id: {"code": "123456", "submitted_at": datetime}}

@router.get("/otp/pending")
async def list_pending_otps(user=Depends(get_user)):
    now = datetime.now(timezone.utc)
    pending = await db.otp_requests.find(
        {"status": "pending", "expires_at": {"$gt": now.isoformat()}},
        {"_id": 0}
    ).sort("requested_at", -1).to_list(20)
    return pending

@router.post("/otp/submit")
@limiter.limit("10/hour")
async def submit_otp(request: Request, data: OtpSubmitIn, user=Depends(get_user)):
    otp_req = await db.otp_requests.find_one(
        {"store_id": data.store_id, "status": "pending"},
        {"_id": 0}
    )
    if not otp_req:
        raise HTTPException(404, "No pending OTP request for this store")
    now = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(otp_req["expires_at"]) if isinstance(otp_req["expires_at"], str) else otp_req["expires_at"]
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        await db.otp_requests.update_one({"id": otp_req["id"]}, {"$set": {"status": "expired"}})
        raise HTTPException(410, "OTP request expired")
    _otp_inbox[data.store_id] = {"code": data.otp_code, "submitted_at": now}
    await db.otp_requests.update_one(
        {"id": otp_req["id"]},
        {"$set": {"status": "completed", "completed_at": now.isoformat()}}
    )
    logger.info(f"[OTP] Code submitted for store {data.store_id}")
    return {"message": "OTP submitted — crawler will proceed", "store_id": data.store_id}

@router.post("/otp/retry/{store_id}")
async def retry_otp(store_id: str, user=Depends(get_user)):
    store = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not store:
        raise HTTPException(404, "Store not found")
    if not store.get("tier4_email") and not store.get("tier4_phone"):
        raise HTTPException(400, "No credentials configured")
    await db.otp_requests.update_many(
        {"store_id": store_id, "status": "pending"},
        {"$set": {"status": "expired"}}
    )
    asyncio.create_task(_run_tier4_login(store_id))
    return {"message": "Login retry triggered", "store_id": store_id}

@router.get("/otp/status/{store_id}")
async def otp_status(store_id: str, user=Depends(get_user)):
    otp_req = await db.otp_requests.find_one(
        {"store_id": store_id}, {"_id": 0}, sort=[("requested_at", -1)]
    )
    if not otp_req:
        return {"store_id": store_id, "status": "none"}
    return otp_req

async def _create_otp_request(store_id: str, store_name: str, phone_last4: str):
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=10)
    doc = {
        "id": str(uuid.uuid4()),
        "store_id": store_id,
        "store_name": store_name,
        "phone_last4": phone_last4,
        "requested_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "status": "pending",
    }
    await db.otp_requests.insert_one(doc)
    doc.pop("_id", None)
    await db.stores.update_one({"id": store_id}, {"$set": {"tier4_session_status": "otp_required"}})
    logger.info(f"[OTP] Request created for {store_name} (****{phone_last4})")
    return doc

async def _wait_for_otp(store_id: str, timeout_secs: int = 600) -> Optional[str]:
    """Poll _otp_inbox for user-submitted OTP code. Returns code or None on timeout."""
    start = time.time()
    while time.time() - start < timeout_secs:
        if store_id in _otp_inbox:
            code = _otp_inbox.pop(store_id)["code"]
            return code
        await asyncio.sleep(2)
    return None


# ── Tier 4 Login Flows ──────────────────────────────────────
async def _run_tier4_login(store_id: str):
    """Background task: attempt Tier 4 authenticated login for a store."""
    store = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not store:
        return
    platform = store.get("platform", "").lower()
    phone_last4 = ""
    try:
        if store.get("tier4_phone"):
            p = decrypt_value(store["tier4_phone"])
            phone_last4 = p[-4:] if len(p) >= 4 else "****"
    except Exception:
        phone_last4 = "****"
    email = ""
    password = ""
    phone = ""
    try:
        if store.get("tier4_email"):
            email = decrypt_value(store["tier4_email"])
        if store.get("tier4_password"):
            password = decrypt_value(store["tier4_password"])
        if store.get("tier4_phone"):
            phone = decrypt_value(store["tier4_phone"])
    except Exception as exc:
        logger.error(f"[T4 Login] Failed to decrypt credentials for {store['name']}: type={type(exc).__name__}")
        await db.stores.update_one({"id": store_id}, {"$set": {"tier4_session_status": "expired"}})
        return
    credentials = {"email": email, "password": password, "phone": phone}
    base_url = store.get("base_url") or f"https://{store['domain']}"
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ar-SA",
            )
            page = await context.new_page()
            result = None
            if platform == "salla":
                result = await _login_salla(page, base_url, store, credentials, phone_last4)
            elif platform == "zid":
                result = await _login_zid(page, base_url, store, credentials, phone_last4)
            elif platform == "shopify":
                result = await _login_shopify(page, base_url, store, credentials, phone_last4)
            else:
                result = await _login_salla(page, base_url, store, credentials, phone_last4)
            if result and result.get("success"):
                cookies = await context.cookies()
                cookies_json = encrypt_value(str(cookies))
                expiry = datetime.now(timezone.utc) + timedelta(days=30)
                await db.stores.update_one({"id": store_id}, {"$set": {
                    "tier4_session_cookies": cookies_json,
                    "tier4_session_expiry": expiry,
                    "tier4_session_status": "active",
                    "tier4_working_login_url": result.get("login_url", ""),
                    "tier4_last_auth_crawl": datetime.now(timezone.utc).isoformat(),
                }})
                logger.info(f"[T4 Login] SUCCESS for {store['name']} via {result.get('method', 'unknown')}")
            else:
                error_msg = result.get("error", "Unknown") if result else "Login handler returned None"
                logger.warning(f"[T4 Login] FAILED for {store['name']}: {error_msg}")
                await db.stores.update_one({"id": store_id}, {"$set": {"tier4_session_status": "expired"}})
            await browser.close()
    except Exception as exc:
        logger.error(f"[T4 Login] Exception for {store['name']}: {type(exc).__name__}: {exc}")
        await db.stores.update_one({"id": store_id}, {"$set": {"tier4_session_status": "expired"}})

async def _login_salla(page, base_url, store, credentials, phone_last4):
    """Salla login handler — phone + OTP flow."""
    store_id = store["id"]
    store_name = store["name"]
    login_urls = [f"{base_url}/login", f"{base_url}/ar/login", f"{base_url}/account/login"]
    login_url = None
    for url in login_urls:
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if resp and resp.status < 400:
                login_url = url
                break
        except Exception:
            continue
    if not login_url:
        return {"success": False, "error": "No login page found"}
    await page.wait_for_timeout(2000)
    phone_selectors = ["input[type=tel]", "input[name=phone]", "input[placeholder*=phone]", "input[placeholder*=جوال]", "input[placeholder*=هاتف]"]
    phone_field = None
    for sel in phone_selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                phone_field = el
                break
        except Exception:
            continue
    if phone_field and credentials.get("phone"):
        try:
            await phone_field.fill(credentials["phone"])
            await page.wait_for_timeout(500)
            submit_selectors = ["button[type=submit]", "button:has-text('إرسال')", "button:has-text('Send')", "button:has-text('تسجيل')", "button:has-text('Login')"]
            for sel in submit_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        break
                except Exception:
                    continue
            await page.wait_for_timeout(3000)
            otp_req = await _create_otp_request(store_id, store_name, phone_last4)
            otp_code = await _wait_for_otp(store_id, timeout_secs=600)
            if not otp_code:
                await db.otp_requests.update_many({"store_id": store_id, "status": "pending"}, {"$set": {"status": "expired"}})
                return {"success": False, "error": "OTP timeout — no code submitted within 10 minutes"}
            otp_selectors = ["input[type=number]", "input[name=otp]", "input[placeholder*=رمز]", "input[placeholder*=code]", "input[inputmode=numeric]"]
            for sel in otp_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.fill(otp_code)
                        break
                except Exception:
                    continue
            await page.wait_for_timeout(500)
            for sel in submit_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        break
                except Exception:
                    continue
            await page.wait_for_timeout(5000)
            success_indicators = ["a[href*=logout]", "button:has-text('خروج')", ".account-menu", "[data-user]"]
            for sel in success_indicators:
                try:
                    if await page.locator(sel).first.count() > 0:
                        return {"success": True, "method": "phone_otp", "login_url": login_url}
                except Exception:
                    continue
            if "/account" in page.url or "/my-account" in page.url:
                return {"success": True, "method": "phone_otp", "login_url": login_url}
            return {"success": False, "error": "OTP submitted but login verification failed"}
        except Exception as exc:
            return {"success": False, "error": f"Phone login failed: {type(exc).__name__}"}
    return {"success": False, "error": "No phone field found on login page"}

async def _login_zid(page, base_url, store, credentials, phone_last4):
    """Zid login handler — email+password first, OTP fallback."""
    store_id = store["id"]
    store_name = store["name"]
    login_urls = [f"{base_url}/login", f"{base_url}/account/login"]
    for url in login_urls:
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if resp and resp.status < 400:
                break
        except Exception:
            continue
    await page.wait_for_timeout(2000)
    email_field = page.locator("input[type=email]").first
    pw_field = page.locator("input[type=password]").first
    if await email_field.count() > 0 and await pw_field.count() > 0 and credentials.get("email") and credentials.get("password"):
        try:
            await email_field.fill(credentials["email"])
            await pw_field.fill(credentials["password"])
            submit = page.locator("button[type=submit]").first
            if await submit.count() > 0:
                await submit.click()
            await page.wait_for_timeout(5000)
            if "/account" in page.url or "/my-account" in page.url:
                return {"success": True, "method": "email_password", "login_url": page.url}
            otp_field = page.locator("input[type=number], input[name=otp], input[inputmode=numeric]").first
            if await otp_field.count() > 0:
                phone_last4_val = phone_last4 or "****"
                await _create_otp_request(store_id, store_name, phone_last4_val)
                otp_code = await _wait_for_otp(store_id, timeout_secs=600)
                if not otp_code:
                    return {"success": False, "error": "OTP timeout"}
                await otp_field.fill(otp_code)
                submit2 = page.locator("button[type=submit]").first
                if await submit2.count() > 0:
                    await submit2.click()
                await page.wait_for_timeout(5000)
                if "/account" in page.url:
                    return {"success": True, "method": "email_otp", "login_url": page.url}
            return {"success": False, "error": "Email+password login failed"}
        except Exception as exc:
            return {"success": False, "error": f"Zid login error: {type(exc).__name__}"}
    return await _login_salla(page, base_url, store, credentials, phone_last4)

async def _login_shopify(page, base_url, store, credentials, phone_last4):
    """Shopify login handler — email+password."""
    store_id = store["id"]
    store_name = store["name"]
    login_url = f"{base_url}/account/login"
    try:
        await page.goto(login_url, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        return {"success": False, "error": "Cannot reach Shopify login page"}
    await page.wait_for_timeout(2000)
    email_field = page.locator("input[type=email], input[name=customer\\[email\\]]").first
    pw_field = page.locator("input[type=password], input[name=customer\\[password\\]]").first
    if await email_field.count() > 0 and await pw_field.count() > 0 and credentials.get("email") and credentials.get("password"):
        try:
            await email_field.fill(credentials["email"])
            await pw_field.fill(credentials["password"])
            submit = page.locator("button[type=submit], input[type=submit]").first
            if await submit.count() > 0:
                await submit.click()
            await page.wait_for_timeout(5000)
            if "/account" in page.url and "/login" not in page.url:
                return {"success": True, "method": "email_password", "login_url": login_url}
            otp_field = page.locator("input[type=number], input[name=otp], input[inputmode=numeric]").first
            if await otp_field.count() > 0:
                phone_last4_val = phone_last4 or "****"
                await _create_otp_request(store_id, store_name, phone_last4_val)
                otp_code = await _wait_for_otp(store_id, timeout_secs=600)
                if not otp_code:
                    return {"success": False, "error": "OTP timeout"}
                await otp_field.fill(otp_code)
                submit2 = page.locator("button[type=submit]").first
                if await submit2.count() > 0:
                    await submit2.click()
                await page.wait_for_timeout(5000)
                if "/account" in page.url and "/login" not in page.url:
                    return {"success": True, "method": "email_otp", "login_url": login_url}
            return {"success": False, "error": "Shopify login failed"}
        except Exception as exc:
            return {"success": False, "error": f"Shopify login error: {type(exc).__name__}"}
    return {"success": False, "error": "No email/password fields found"}


# ── Sales-estimation constants & helpers moved to /app/backend/core/utils.py (Feb 2026 refactor) ──
MIN_SNAPSHOT_PAIRS_FOR_SALES = 2  # need at least 2 valid deltas before any sales credit


# _estimate_sales_from_snapshots and compute_product_metrics moved to core/utils.py

# ── Product Routes ──────────────────────────────────────────
# ── Dashboard cache (iter25, Jul 2026) ──────────────────────────────────────
# /api/my-products recomputes snapshot fetch + sales estimation across ~2,177
# products x window on every request (~40s at 90D on production). The underlying
# data only changes on the daily crawl + 6-hourly own-store sync, so the default
# window views (7/14/30/90D, unfiltered) are precomputed into db.dashboard_cache
# and served instantly. Filtered / on_date / search / own_only=False requests are
# narrower and stay live. Cached values are byte-identical to live computation:
# the cache stores the SAME `_my_products_dataset` output (jsonable-encoded so the
# BSON round-trip can't perturb a value), and the endpoint applies the identical
# sort + pagination on top.
DASHBOARD_CACHE_STD_WINDOWS = (7, 14, 30, 90)
DASHBOARD_CACHE_MAX_AGE_SECS = 24 * 3600  # beyond this, fall back to live compute
_LAST_DASHBOARD_RECOMPUTE = None           # module-level debounce for crawl bursts


def _dashboard_cache_key(days: int) -> str:
    return f"my_products:v1:days={days}"


async def _store_dashboard_cache(db, days, dataset):
    """Persist one window's dataset (jsonable-encoded) with a fresh timestamp."""
    now = datetime.now(timezone.utc)
    await db.dashboard_cache.replace_one(
        {"key": _dashboard_cache_key(days)},
        {"key": _dashboard_cache_key(days), "window_days": days,
         "computed_at": now, "dataset": jsonable_encoder(dataset)},
        upsert=True,
    )
    return now


async def recompute_dashboard_cache(db, windows=DASHBOARD_CACHE_STD_WINDOWS):
    """Recompute + store the default my-products view for each standard window.

    Runs after crawl / own-store sync / matcher completion. Each window is one
    full `_my_products_dataset` pass (bounded memory via iter24 chunking); this
    is the ~40s cost moved off the request path into the background."""
    import time as _t
    global _LAST_DASHBOARD_RECOMPUTE
    stats = {}
    for w in windows:
        t0 = _t.time()
        ds = await _my_products_dataset(db, w, None, None, None, None, None, None, True)
        await _store_dashboard_cache(db, w, ds)
        stats[w] = {"rows": ds["total"], "secs": round(_t.time() - t0, 2)}
    _LAST_DASHBOARD_RECOMPUTE = datetime.now(timezone.utc)
    logger.info(f"[DashboardCache] recomputed {list(windows)}: {stats}")
    return stats


async def maybe_recompute_dashboard_cache(db, min_interval_secs=600, force=False):
    """Debounced recompute — force=True for definitive data changes (manual sync,
    matcher run); debounced for the staggered daily crawl burst so 44 store
    crawls trigger ~1 recompute, not 44. Never raises."""
    global _LAST_DASHBOARD_RECOMPUTE
    now = datetime.now(timezone.utc)
    if (not force and _LAST_DASHBOARD_RECOMPUTE
            and (now - _LAST_DASHBOARD_RECOMPUTE).total_seconds() < min_interval_secs):
        return None
    try:
        return await recompute_dashboard_cache(db)
    except Exception:
        logger.exception("[DashboardCache] recompute failed — cache left stale, endpoint will fall back to live")
        return None


# ── Generic page cache (iter26, Jul 2026) ───────────────────────────────────
# iter25 cached /api/my-products. iter26 extends the SAME db.dashboard_cache
# collection to the Insights and Price-Intel page endpoints. Those return bare
# lists as well as dicts, so a body-level `cache` key (as my_products uses)
# would change the shape / break byte-identicality for list responses. Instead
# the cache metadata rides in RESPONSE HEADERS (X-Cache-*), leaving every body
# byte-identical to live. The stored payload IS the final endpoint body
# (jsonable-encoded), so serving from cache == serving live.
_LAST_PAGE_CACHE_RECOMPUTE = None


def _page_cache_key(base: str, days=None) -> str:
    return f"{base}:v1:days={days}" if days is not None else f"{base}:v1"


async def _store_page_cache(db, base, days, payload):
    now = datetime.now(timezone.utc)
    await db.dashboard_cache.replace_one(
        {"key": _page_cache_key(base, days)},
        {"key": _page_cache_key(base, days), "base": base, "window_days": days,
         "computed_at": now, "payload": jsonable_encoder(payload)},
        upsert=True,
    )
    return now


async def _serve_page_cache(db, base, days, compute, cacheable=True):
    """Serve `base` (optionally per `days`) from db.dashboard_cache.

    `compute` is a zero-arg async callable returning the endpoint body. Returns
    (body, meta) where meta = {source, computed_at, age_seconds, stale}. On
    miss / unparseable / stale-beyond-24h → compute live + best-effort refresh.
    Never raises from the cache layer (only `compute` may)."""
    now = datetime.now(timezone.utc)
    if not cacheable:
        return await compute(), {"source": "live_uncacheable", "computed_at": None, "age_seconds": None, "stale": False}
    doc = None
    try:
        doc = await db.dashboard_cache.find_one({"key": _page_cache_key(base, days)})
    except Exception:
        doc = None
    if doc is not None and doc.get("computed_at") is not None and "payload" in doc:
        ca = doc["computed_at"]
        if not isinstance(ca, datetime):
            try:
                ca = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            except Exception:
                ca = None
        if ca is not None:
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=timezone.utc)
            age = (now - ca).total_seconds()
            if age <= DASHBOARD_CACHE_MAX_AGE_SECS:
                return doc["payload"], {"source": "cache", "computed_at": ca.isoformat(),
                                        "age_seconds": round(age, 1), "stale": False}
    body = await compute()
    stamped = None
    try:
        stamped = await _store_page_cache(db, base, days, body)
    except Exception:
        pass
    return body, {"source": "live_fallback", "computed_at": (stamped or now).isoformat(),
                  "age_seconds": 0.0, "stale": False}


def _apply_cache_headers(response, meta):
    """Attach X-Cache-* headers so the frontend can show 'Metrics as of <time>'
    without altering the (byte-identical) response body."""
    if response is None:
        return
    response.headers["X-Cache-Source"] = str(meta.get("source"))
    if meta.get("computed_at"):
        response.headers["X-Cache-Computed-At"] = str(meta["computed_at"])
    if meta.get("age_seconds") is not None:
        response.headers["X-Cache-Age-Seconds"] = str(meta["age_seconds"])
    response.headers["X-Cache-Stale"] = "true" if meta.get("stale") else "false"
    response.headers["Access-Control-Expose-Headers"] = "X-Cache-Source, X-Cache-Computed-At, X-Cache-Age-Seconds, X-Cache-Stale"


# Registry of (cache_base, per-window?, compute-factory) filled in after the
# compute helpers are defined (see _register_page_caches below the endpoints).
_WINDOW_CACHE_SPECS = []   # list of (base, compute(db, days))
_SINGLE_CACHE_SPECS = []   # list of (base, compute(db))


async def recompute_page_caches(db, windows=DASHBOARD_CACHE_STD_WINDOWS):
    """Recompute + store every Insights / Price-Intel cache entry. Each spec is
    a bounded aggregation (iter26 hardening); a failure in one endpoint is
    logged and skipped so one bad aggregation can't hang the whole recompute."""
    import time as _t
    global _LAST_PAGE_CACHE_RECOMPUTE
    stats = {}
    for base, compute in _WINDOW_CACHE_SPECS:
        for w in windows:
            t0 = _t.time()
            try:
                payload = await compute(db, w)
                await _store_page_cache(db, base, w, payload)
                stats[f"{base}#{w}"] = round(_t.time() - t0, 2)
            except Exception as e:
                stats[f"{base}#{w}"] = f"ERROR: {str(e)[:80]}"
                logger.exception(f"[PageCache] recompute failed for {base} @ {w}d")
    for base, compute in _SINGLE_CACHE_SPECS:
        t0 = _t.time()
        try:
            payload = await compute(db)
            await _store_page_cache(db, base, None, payload)
            stats[base] = round(_t.time() - t0, 2)
        except Exception as e:
            stats[base] = f"ERROR: {str(e)[:80]}"
            logger.exception(f"[PageCache] recompute failed for {base}")
    _LAST_PAGE_CACHE_RECOMPUTE = datetime.now(timezone.utc)
    logger.info(f"[PageCache] recomputed insights/price-intel: {stats}")
    return stats


async def maybe_recompute_page_caches(db, min_interval_secs=600, force=False):
    global _LAST_PAGE_CACHE_RECOMPUTE
    now = datetime.now(timezone.utc)
    if (not force and _LAST_PAGE_CACHE_RECOMPUTE
            and (now - _LAST_PAGE_CACHE_RECOMPUTE).total_seconds() < min_interval_secs):
        return None
    try:
        return await recompute_page_caches(db)
    except Exception:
        logger.exception("[PageCache] recompute failed — caches left stale, endpoints fall back to live")
        return None



async def _own_orders_aggregate(db, o_start, o_end=None):
    """iter40 — THE single source for own-store ledger revenue figures. Both the
    My Products KPI path and the store ranking read this helper, so the same
    metric can never show two different values again. Returns
    aggregate_orders() output, or None when no non-excluded orders fall in the
    window (callers fall back / show 'accumulating')."""
    order_query = {"created_at": {"$gte": o_start, **({"$lt": o_end} if o_end else {})}}
    order_docs = await db.own_store_orders.find(
        order_query, {"_id": 0, "excluded": 1, "total": 1, "units": 1, "items": 1},
    ).to_list(100000)
    if order_docs:
        _agg = aggregate_orders(order_docs)
        if _agg["orders_count"] > 0:
            return _agg
    return None


async def _my_products_dataset(db, days, on_date, date_from, date_to, category, animal_type, search, own_only):
    """Compute the FULL my-products dataset — every enriched row + KPIs +
    categories + total — for the given filters, WITHOUT sort or pagination.

    Shared verbatim by the /my-products endpoint and the dashboard-cache
    recompute so cached and live results are byte-identical: sort and
    pagination are applied by the caller and are pure presentation (they do
    not affect the KPIs, the per-row signals, or the category set)."""
    # Resolve date window
    if on_date:
        start = datetime.fromisoformat(on_date).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        snap_query = {"crawled_at": {"$gte": start, "$lt": end}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}
        effective_days = 1
    elif date_from or date_to:
        df = datetime.fromisoformat(date_from).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc) if date_from else (datetime.now(timezone.utc) - timedelta(days=days))
        dt = (datetime.fromisoformat(date_to).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc) + timedelta(days=1)) if date_to else datetime.now(timezone.utc)
        snap_query = {"crawled_at": {"$gte": df, "$lt": dt}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}
        effective_days = max(1, (dt - df).days)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        snap_query = {"crawled_at": {"$gte": since}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}
        effective_days = days
    # iter24 (Jul 2026) — snapshots are no longer bulk-loaded here. The
    # unbounded/truncated load that lived at this point OOM'd the origin at
    # 30D/90D (Cloudflare 520). by_sku is now built per-chunk inside the
    # product loop below (bounded memory). orders_agg (real Zid revenue) is
    # independent of snapshots and computed next, unchanged.

    # ── Own-store REAL orders (Feb 2026 rework) ─────────────────────────
    # My Revenue / My Units come from the Zid orders ledger when available.
    # The orders window mirrors the snapshot window with one deliberate
    # difference: calendar-day params (on_date / date_from / date_to) are
    # interpreted as KSA (Asia/Riyadh) days, because that is how the
    # merchant's Zid dashboard buckets its daily totals — otherwise a
    # "July 1" query can never reconcile with Zid's July 1 number.
    orders_agg = None
    if own_only:
        if on_date:
            o_start = datetime.fromisoformat(on_date).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=ORDERS_KSA_TZ).astimezone(timezone.utc)
            o_end = o_start + timedelta(days=1)
        elif date_from or date_to:
            o_start = (datetime.fromisoformat(date_from).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=ORDERS_KSA_TZ).astimezone(timezone.utc)
                       if date_from else datetime.now(timezone.utc) - timedelta(days=days))
            o_end = ((datetime.fromisoformat(date_to).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=ORDERS_KSA_TZ) + timedelta(days=1)).astimezone(timezone.utc)
                     if date_to else datetime.now(timezone.utc))
        else:
            o_start = datetime.now(timezone.utc) - timedelta(days=days)
            o_end = None
        # iter40 — shared ledger helper: the store ranking reads the SAME
        # function, so "My Revenue" can never disagree between surfaces again.
        orders_agg = await _own_orders_aggregate(db, o_start, o_end)

    # Get all products
    prod_query = {}
    if category and category != "all":
        # iter36 — subcategory keys filter on the additive `subcategory` field;
        # parent keys (cat_food, …) keep matching every product as before.
        if category in FOOD_SUBCATEGORIES:
            prod_query["subcategory"] = category
        else:
            prod_query["category"] = category
    if animal_type and animal_type != "all":
        prod_query["animal_type"] = animal_type
    if search:
        # Fix (Feb 2026 — flagged by testing agent iteration_15): the search box
        # is used as a daily-workflow tool to look up products by SKU or
        # barcode, not just by Arabic/English name. Add barcode + escape any
        # regex meta-chars so a raw barcode value like "8005852569199" never
        # gets interpreted as a regex.
        safe = re.escape(search)
        prod_query["$or"] = [
            {"name_ar": {"$regex": safe, "$options": "i"}},
            {"name_en": {"$regex": safe, "$options": "i"}},
            {"sku": {"$regex": safe, "$options": "i"}},
            {"barcode": {"$regex": safe, "$options": "i"}},
        ]

    # Pull my_products lookup BEFORE the catalog query so the "stitch missing
    # SKUs" step below has access to the price-lookup map.
    my_products_docs = await db.my_products.find(
        {},
        {"_id": 0, "sku": 1, "barcode": 1, "name_ar": 1, "name_en": 1, "product_url": 1,
         "price": 1, "sale_price": 1, "quantity": 1, "in_stock": 1, "last_synced_at": 1,
         "present_on_store": 1, "last_seen_on_store": 1, "discovered_via": 1},
    ).to_list(20000)
    my_url_by_sku = {p["sku"]: p.get("product_url") for p in my_products_docs if p.get("product_url")}
    my_skus_set = {p["sku"] for p in my_products_docs if p.get("sku")}
    my_price_lookup = {p["sku"]: p for p in my_products_docs}
    my_presence_lookup = {p["sku"]: p for p in my_products_docs}

    # Own-store gate (Feb 2026): when own_only=True, restrict to SKUs that exist
    # in db.my_products AND are currently active on the store (present_on_store
    # is True OR has never been flagged). Soft-archived rows are hidden — they
    # represent products the merchant deleted from pets-houses.com.
    own_skus_list = []
    if own_only:
        own_skus_list = [p["sku"] for p in my_products_docs
                         if p.get("sku") and p.get("present_on_store", True)]
        # Search must also hit db.my_products directly so newly-synced SKUs
        # without a catalog entry are findable by SKU/barcode (Feb 2026 fix).
        if search:
            search_lc = search.lower().strip()
            matching_own = {
                p["sku"] for p in my_products_docs
                if p.get("sku") and p.get("present_on_store", True) and (
                    search_lc in str(p.get("sku", "")).lower()
                    or search_lc in str(p.get("barcode", "")).lower()
                    or search_lc in str(p.get("name_ar", "")).lower()
                    or search_lc in str(p.get("name_en", "")).lower()
                )
            }
            own_skus_list = list(matching_own)
        if own_skus_list:
            prod_query["sku"] = {"$in": own_skus_list}
        else:
            # No own catalog yet — return empty rather than the entire market
            prod_query["sku"] = {"$in": []}
    products = await db.products.find(prod_query, {"_id": 0}).to_list(5000)

    # When own_only=True, also stitch in db.my_products SKUs that don't yet have
    # a db.products catalog row (e.g. just synced from Zid, no scheduled crawl
    # has run yet). They show in the table with zero market metrics — Issue #1.
    if own_only and own_skus_list:
        existing_skus = {p["sku"] for p in products}
        missing_skus = set(own_skus_list) - existing_skus
        for sku in missing_skus:
            mp_doc = my_price_lookup.get(sku)
            if not mp_doc:
                continue
            products.append({
                "sku": mp_doc["sku"],
                "barcode": mp_doc.get("barcode", ""),
                "name_ar": mp_doc.get("name_ar", ""),
                "name_en": mp_doc.get("name_en", ""),
                "category": "",
                "animal_type": "",
                "brand": "",
                "image_url": "",
                "product_url": mp_doc.get("product_url", ""),
            })

    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "domain": 1})
    own_domain = own_store.get("domain") if own_store else None
    store_domains = {s["id"]: s.get("domain") for s in await db.stores.find({}, {"_id": 0, "id": 1, "domain": 1}).to_list(200) if s.get("domain")}

    result = []
    total_sold = 0
    total_rev = 0.0

    # Market position prep (Feb 2026): pre-build helpers used per-product
    # below. Doing this OUTSIDE the loop avoids N+1 queries.
    own_store_doc = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_store_id = own_store_doc.get("id") if own_store_doc else None
    store_name_by_id = {s["id"]: s.get("name", "") for s in await db.stores.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(200)}
    matches_by_my_sku = {}
    if own_store_id:
        async for m in db.product_matches.find({}, {"_id": 0, "my_sku": 1, "competitor_sku": 1, "competitor_store_id": 1, "confidence": 1, "match_method": 1}):
            matches_by_my_sku.setdefault(m["my_sku"], []).append((
                m["competitor_sku"], m["competitor_store_id"], m.get("confidence", 0), m.get("match_method"),
            ))

    # iter24 CHUNKED fetch (bounded memory). Each product only ever reads
    # by_sku for its OWN sku, its matched competitor skus, and its barcode/EAN
    # candidates (the three by_sku.get() sites below), so fetching those
    # sku-clusters per chunk is exactly equivalent to a global fetch while peak
    # memory is bounded by one chunk. Downstream business functions receive
    # identical per-(sku, store) chronological arrays — zero logic/value change.
    # No server-side $sort/$group (iter21 postmortem rule): each chunk query is
    # a plain indexed find on (sku, crawled_at); per-pair sort in Python.
    def _sku_cluster(p):
        cluster = {p["sku"]}
        for tup in matches_by_my_sku.get(p["sku"], ()):
            cluster.add(tup[0])
        _mp_doc = my_price_lookup.get(p["sku"])
        if _mp_doc:
            _bc = str(_mp_doc.get("barcode") or "").strip()
            if _is_valid_barcode(_bc):
                cluster.add(_bc)
        return cluster

    _SNAP_PROJECTION = {
        "_id": 0, "sku": 1, "store_id": 1, "store_name": 1,
        "crawled_at": 1, "price": 1, "original_price": 1, "discount_pct": 1,
        "qty_available": 1, "in_stock": 1, "sold_count": 1,
        "confidence_score": 1, "source_tier": 1, "product_url": 1,
    }

    for _chunk_start in range(0, len(products), MY_PRODUCTS_CHUNK_SIZE):
        _chunk = products[_chunk_start:_chunk_start + MY_PRODUCTS_CHUNK_SIZE]
        _chunk_skus = set()
        for _cp in _chunk:
            if _cp.get("sku"):
                _chunk_skus |= _sku_cluster(_cp)
        by_sku = {}
        if _chunk_skus:
            _chunk_query = dict(snap_query)
            _chunk_query["sku"] = {"$in": list(_chunk_skus)}
            cursor = db.product_snapshots.find(_chunk_query, _SNAP_PROJECTION).batch_size(2000)
            async for s in cursor:
                by_sku.setdefault(s["sku"], {}).setdefault(s["store_id"], []).append(s)
            for _sk in by_sku:
                for _sid in by_sku[_sk]:
                    by_sku[_sk][_sid].sort(key=lambda x: x["crawled_at"])

        for p in _chunk:
            stores_data = by_sku.get(p["sku"], {})
            metrics = compute_product_metrics(stores_data, effective_days)
            if not metrics:
                # Issue #1: keep the row in the table even if no snapshot history
                # exists in the selected window. The user's catalogue size must be
                # constant across time filters; only the metric numbers change.
                if not own_only:
                    continue
                metrics = {
                    "price": 0.0, "min_price": 0.0, "max_price": 0.0, "median_price": 0.0,
                    "vs_lowest_pct": 0, "vs_median_pct": 0,
                    "qty_sold_est": 0, "revenue_est": 0.0,
                    "num_sellers": 0, "latest_qty": 0,
                    "stock_signal": "MEDIUM", "confidence_score": 0, "source_tier": 1,
                }
            row = {**p, **metrics}

            # Resolve product_url with priority:
            # 1. my_products (user's own catalog URL)
            # 2. db.products.product_url (last URL captured by any crawler/ingest)
            # 3. Latest snapshot's product_url (per-store URL from any tracked store)
            # 4. Fallback: own-store search URL by SKU, else first competitor's search URL
            url = my_url_by_sku.get(p["sku"]) or p.get("product_url") or ""
            if not url:
                for snaps in stores_data.values():
                    snap_url = (snaps[-1] if snaps else {}).get("product_url")
                    if snap_url:
                        url = snap_url
                        break
            if not url:
                if own_domain:
                    url = f"https://{own_domain}/search?keyword={p['sku']}"
                elif stores_data:
                    first_sid = next(iter(stores_data.keys()))
                    fd = store_domains.get(first_sid)
                    if fd:
                        url = f"https://{fd}/search?keyword={p['sku']}"
            row["product_url"] = url
            row["is_my_product"] = p["sku"] in my_skus_set
            # Auto-sync presence flags (Feb 2026): exposed so the frontend can render
            # an "ARCHIVED" / "Not on store" badge on rows whose SKU has vanished
            # from pets-houses.com without being deleted from db.my_products.
            _mp = my_presence_lookup.get(p["sku"]) or {}
            row["present_on_store"] = _mp.get("present_on_store") if _mp else None
            row["last_seen_on_store"] = _mp.get("last_seen_on_store")
            row["discovered_via"] = _mp.get("discovered_via")

            # ── My-store-centric fields (Feb 2026) ───────────────────
            # "My Products" page needs the SKU, name, price and stock to reflect the
            # user's Zid store, not the market aggregate. We override the catalog
            # display fields with db.my_products values when this row is mine, and
            # we derive a `vs_my_price_pct` comparing the cheapest *competitor* to
            # my price. Snapshot-derived market fields (qty_sold_est, revenue_est,
            # num_sellers) stay untouched — the frontend labels them as market.
            if p["sku"] in my_skus_set:
                mp_doc = my_price_lookup.get(p["sku"]) or {}
                mp_name_ar = mp_doc.get("name_ar")
                mp_name_en = mp_doc.get("name_en")
                mp_barcode = mp_doc.get("barcode")
                if mp_name_ar:
                    row["name_ar"] = mp_name_ar
                if mp_name_en:
                    row["name_en"] = mp_name_en
                if mp_barcode:
                    row["barcode"] = mp_barcode

                my_price = mp_doc.get("sale_price") or mp_doc.get("price")
                my_qty = mp_doc.get("quantity")
                my_in_stock = mp_doc.get("in_stock")

                # Override the headline Price column to show MY price (the previous
                # value was the market average — misleading on a "my products" page).
                if my_price is not None:
                    row["price"] = round(my_price, 2)
                row["my_price"] = round(my_price, 2) if my_price is not None else None
                row["my_quantity"] = int(my_qty) if my_qty is not None else None
                row["my_in_stock"] = bool(my_in_stock) if my_in_stock is not None else None
                row["my_stock_signal"] = get_stock_signal(
                    row["my_quantity"] if row["my_quantity"] is not None else 0,
                    in_stock=row["my_in_stock"],
                ) if my_price is not None else None

                # Competitor discovery — barcode-safe UNION of two sources:
                #   (A) product_matches link table (matcher's truth — barcode at conf 99,
                #       SKU equality at conf 95). Robust to suffix mismatches because
                #       the matcher already resolved them.
                #   (B) Direct snapshot lookup keyed by my barcode/EAN candidates.
                #       Catches competitors the matcher hasn't linked yet (matcher
                #       coverage gap) but ONLY when the SKU string itself passes the
                #       NUMERIC_BARCODE_RE (^\d{8,14}$). This means a Zid suffix like
                #       "8005852750068-RUDC" can NEVER match my EAN "8005852750068"
                #       via this path (the suffixed string fails the regex). For
                #       non-EAN proprietary SKUs (XYZ-001), the candidate set is
                #       empty and we fall back to source A only.
                # See /app/backend/tests/test_competitor_count_union.py for safety
                # guarantees encoded as regression tests.
                mp_barcode_field = str(mp_doc.get("barcode") or "").strip()
                my_barcode_candidates = set()
                if _is_valid_barcode(mp_barcode_field):
                    my_barcode_candidates.add(mp_barcode_field)
                if _is_valid_barcode(p["sku"]):
                    my_barcode_candidates.add(p["sku"])

                # Per-store "latest snapshot" map: store_id -> latest_snapshot_dict.
                # First seed from matches (authoritative when present), then fill
                # gaps from the barcode union (additive, dedupe by store_id).
                competitor_latest_by_store = {}
                best_match_confidence = 0
                best_match_tier = None
                for tup in matches_by_my_sku.get(p["sku"], []):
                    comp_sku, comp_store_id = tup[0], tup[1]
                    match_conf = tup[2] if len(tup) > 2 else 0
                    comp_snaps = by_sku.get(comp_sku, {}).get(comp_store_id, [])
                    if not comp_snaps:
                        continue
                    latest = comp_snaps[-1]
                    competitor_latest_by_store.setdefault(comp_store_id, latest)
                    if match_conf > best_match_confidence:
                        best_match_confidence = match_conf
                        best_match_tier = latest.get("source_tier")
                for bc in my_barcode_candidates:
                    for sid, snaps in by_sku.get(bc, {}).items():
                        if sid == own_store_id or sid in competitor_latest_by_store:
                            continue
                        if not snaps:
                            continue
                        competitor_latest_by_store[sid] = snaps[-1]

                # num_competitors = ALL stores that carry the product. OOS counts.
                # Stores whose latest snapshot has price=None still count (the user
                # explicitly wants this: stockout shouldn't drop a competitor from
                # the count, only from the price comparison).
                row["num_competitors"] = len(competitor_latest_by_store)

                # Price comparison — only stores with a usable price. OOS competitors
                # WITH a price ARE included (their price is a real market signal).
                comp_latest_prices = [
                    snap["price"] for snap in competitor_latest_by_store.values()
                    if snap.get("price") is not None
                ]
                row["num_priced_competitors"] = len(comp_latest_prices)
                if comp_latest_prices:
                    comp_min = min(comp_latest_prices)
                    row["competitor_min_price"] = round(comp_min, 2)
                    row["competitor_max_price"] = round(max(comp_latest_prices), 2)
                    if my_price and my_price > 0:
                        # Positive  → my_price is BELOW the cheapest competitor (I'm winning)
                        # Negative  → a competitor undercuts me (I'm overpriced)
                        row["vs_my_price_pct"] = round(((comp_min - my_price) / my_price) * 100, 1)
                    else:
                        row["vs_my_price_pct"] = None
                else:
                    row["competitor_min_price"] = None
                    row["competitor_max_price"] = None
                    row["vs_my_price_pct"] = None

                # Override confidence + tier with the matcher's view when we have a
                # linked competitor. This is what the user sees in the Conf. column —
                # the trust level of the price comparison, not the trust of the own-
                # store snapshot (which is always tier 0 / 99 by definition).
                if best_match_confidence > 0:
                    row["confidence_score"] = int(best_match_confidence)
                    if best_match_tier is not None:
                        row["source_tier"] = best_match_tier

                # Own-store sales (Feb 2026, orders rework): REAL numbers from the
                # Zid orders ledger (own_store_orders) whenever the window has
                # order data — exact units and product-attributed revenue, immune
                # to the stock-depletion blind spots. Falls back to the legacy
                # snapshot estimator only when no orders exist in the window
                # (backfill not run yet / Zid creds missing), so the dashboard
                # degrades to the old behavior instead of zeros.
                if orders_agg is not None:
                    sku_orders = orders_agg["by_sku"].get(p["sku"], {})
                    row["my_units_sold"] = int(sku_orders.get("units") or 0)
                    row["my_revenue_est"] = round(float(sku_orders.get("revenue") or 0.0), 2)
                    row["my_sales_source"] = "zid_orders"
                else:
                    own_snaps = stores_data.get(own_store_id, []) if own_store_id else []
                    my_units, _own_rev_from_snaps, _ = _estimate_sales_from_snapshots(own_snaps, effective_days)
                    row["my_units_sold"] = int(my_units or 0)
                    row["my_revenue_est"] = round((row["my_units_sold"] * (my_price or 0.0)), 2) if my_price else 0.0
                    row["my_sales_source"] = "estimated"
            else:
                # Non-own row (only reachable when own_only=False — e.g. /api/insights/sales)
                row["my_units_sold"] = 0
                row["my_revenue_est"] = 0.0

            # Market position (Feb 2026) — own price lives in db.my_products (not in
            # product_snapshots), so we synthesize an entry for the own store using
            # the my_products row directly. Competitors come from matched snapshots.
            if own_store_id and p["sku"] in my_skus_set:
                mp_row = my_price_lookup.get(p["sku"]) or {}
                own_price = mp_row.get("sale_price") or mp_row.get("price")
                if own_price:
                    seller_prices = [{
                        "store_id": own_store_id,
                        "store_name": store_name_by_id.get(own_store_id, "My Store"),
                        "price": own_price,
                        "confidence_score": 99,
                        "crawled_at": mp_row.get("last_synced_at") or datetime.now(timezone.utc),
                    }]
                    for tup in matches_by_my_sku.get(p["sku"], []):
                        comp_sku, comp_store_id = tup[0], tup[1]
                        comp_snaps = by_sku.get(comp_sku, {}).get(comp_store_id, [])
                        if not comp_snaps:
                            continue
                        latest = comp_snaps[-1]
                        seller_prices.append({
                            "store_id": comp_store_id,
                            "store_name": store_name_by_id.get(comp_store_id, ""),
                            "price": latest.get("price"),
                            "confidence_score": latest.get("confidence_score", 0),
                            "crawled_at": latest.get("crawled_at"),
                        })
                    row["market_position"] = compute_market_position(seller_prices, own_store_id)
                else:
                    row["market_position"] = None
            else:
                row["market_position"] = None

            result.append(row)
            total_sold += metrics["qty_sold_est"]
            total_rev += metrics["revenue_est"]


    # Per-row signals (Feb 2026, v5 — barcode-safe union model):
    #   • has_competitor_pricing = num_priced_competitors >= 1
    #     (drives the Market Coverage KPI — "how much of my catalogue has
    #     USABLE competitor pricing data?". OOS competitors with a price still
    #     count; competitors with no price at all do not.)
    #   • num_competitors (the count column) is the WIDER notion: every store
    #     carrying the product, whether their latest snapshot is priced or not.
    #     This is what the user sees in the "Competitors" column.
    #   • has_market_share = num_priced_competitors >= 1 AND market_units > 0
    #     (preserves the iter19 invariant: share_sample_size == Σ has_market_share)
    # The retired fair-share fallback (assigning 100% to unmatched products)
    # caused the production 92.4% inflation; removed entirely — no imputation.
    for r in result:
        market_units_for_sku = r.get("qty_sold_est") or 0
        my_units_for_sku = r.get("my_units_sold") or 0
        n_priced = r.get("num_priced_competitors")
        if n_priced is None:
            # Non-own rows (own_only=False — /api/insights/sales) don't compute
            # the priced subset; fall back to num_sellers - 1 as a coarse proxy.
            n_priced = max(0, (r.get("num_sellers") or 0) - 1)
        r["market_size"] = market_units_for_sku
        r["has_competitor_pricing"] = n_priced >= 1
        if n_priced >= 1 and market_units_for_sku > 0:
            r["market_share_pct"] = round((my_units_for_sku / market_units_for_sku) * 100, 1)
            r["has_market_share"] = True
        else:
            r["market_share_pct"] = None
            r["has_market_share"] = False
        r["my_share_is_estimate"] = False  # fair-share fallback retired

    total_count = len(result)
    # KPI totals — when own_only=True (the My Products page):
    #   • Units Sold (Est.)     — Σ qty_sold_est across all rows (market velocity for YOUR catalogue)
    #   • Mkt. Revenue (Est.)   — Σ revenue_est (market_price × market_units)
    #   • My Revenue (Est.)     — Σ my_price × my_units_sold (what YOU actually earn)
    #   • Avg. Market Share     — Σmy ÷ Σmarket × 100, ONLY across rows with
    #                             has_market_share=True (need both a match AND velocity)
    #   • Market Coverage       — products with has_competitor_pricing / total — answers
    #                             "how much of my catalogue has competitor pricing?"
    #   • Share Sample Size     — N (rows used in avg_market_share denominator) —
    #                             surfaces the denominator transparently so 0% over 49
    #                             products isn't read the same as 0% over 2,081
    pricing_rows = [r for r in result if r.get("has_competitor_pricing")]
    share_rows = [r for r in result if r.get("has_market_share")]
    total_my_units = sum((r.get("my_units_sold") or 0) for r in result)
    total_my_units_share = sum((r.get("my_units_sold") or 0) for r in share_rows)
    total_market_units_share = sum((r.get("qty_sold_est") or 0) for r in share_rows)
    if own_only:
        total_revenue_at_my_prices = sum(
            ((r.get("my_price") or r.get("price") or 0) * (r.get("qty_sold_est") or 0))
            for r in result
        )
        if orders_agg is not None:
            # REAL ledger numbers. my_revenue = Σ order totals — the same
            # figure the Zid dashboard shows (shipping/fees included), NOT the
            # Σ of per-row line revenue (which excludes order-level charges).
            my_revenue = orders_agg["revenue"]
            my_units_kpi = orders_agg["units"]
            my_revenue_source = "zid_orders"
        else:
            my_revenue = sum(
                ((r.get("my_price") or r.get("price") or 0) * (r.get("my_units_sold") or 0))
                for r in result
            )
            my_units_kpi = total_my_units
            my_revenue_source = "estimated"
        avg_market_share_honest = (
            round((total_my_units_share / total_market_units_share) * 100, 1)
            if total_market_units_share > 0 else 0
        )
        kpis = {
            "total_products": total_count,
            "total_units_sold": int(total_sold),
            "market_revenue": round(total_rev, 2),
            "my_revenue": round(my_revenue, 2),
            # "zid_orders" → exact ledger data (frontend drops the "(Est.)"
            # suffix); "estimated" → legacy snapshot-depletion fallback.
            "my_revenue_source": my_revenue_source,
            "my_orders_count": orders_agg["orders_count"] if orders_agg else None,
            "avg_market_share": avg_market_share_honest,
            "my_units_sold": int(my_units_kpi),
            # Market data coverage — answers "do we have competitor pricing on this product?"
            "matched_products": len(pricing_rows),
            "market_coverage_pct": round((len(pricing_rows) / total_count) * 100, 1) if total_count > 0 else 0,
            # Share sample size — N of rows used in the avg_market_share calculation.
            # Lets the UI render "Across 49 of 2,081" so the user understands the denominator.
            "share_sample_size": len(share_rows),
            # Legacy alias — kept so older clients keep working until they migrate.
            "total_revenue": round(total_revenue_at_my_prices, 2),
        }
    else:
        # Legacy market-wide behaviour — keeps /api/insights/sales contract intact
        kpis = {
            "total_products": total_count,
            "total_units_sold": int(total_sold),
            "total_revenue": round(total_rev, 2),
            "market_revenue": round(total_rev, 2),
            "avg_market_share": round(100 / total_count, 1) if total_count else 0,
        }
    # Distinct categories across the FULL filtered set (so the dropdown stays complete after pagination)
    # iter36 — subcategories present in the set appear alongside their parents.
    categories_all = sorted({(r.get("category") or "") for r in result if r.get("category")}
                            | {r["subcategory"] for r in result if r.get("subcategory")})
    # Apply pagination AFTER sort + KPIs so totals remain accurate
    return {"kpis": kpis, "rows": result, "total": total_count, "categories": categories_all}

@router.get("/my-products")
async def my_products(
    days: int = Query(30),
    on_date: Optional[str] = Query(None, description="Filter to a specific calendar day (YYYY-MM-DD); overrides 'days'"),
    date_from: Optional[str] = Query(None, description="Inclusive lower-bound date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Inclusive upper-bound date (YYYY-MM-DD)"),
    category: Optional[str] = Query(None),
    animal_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("revenue_est"),
    sort_order: str = Query("desc"),
    limit: int = Query(100, ge=1, le=500, description="Max products per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    own_only: bool = Query(True, description="Restrict results to SKUs present in db.my_products (your own store). The MyProducts page sets this to True (default); /api/insights/sales calls this function internally with own_only=False to retain market-wide aggregation."),
    user=Depends(get_user)
):
    # iter25 — serve the default window views from db.dashboard_cache; keep
    # filtered / on_date / search / own_only=False requests live (narrow + fast).
    _cacheable = (
        bool(own_only)
        and not on_date and not date_from and not date_to
        and (category in (None, "", "all"))
        and (animal_type in (None, "", "all"))
        and not search
        and days in DASHBOARD_CACHE_STD_WINDOWS
    )

    dataset = None
    cache_meta = {"source": "live_uncacheable", "computed_at": None, "age_seconds": None, "stale": False}

    if _cacheable:
        doc = None
        try:
            doc = await db.dashboard_cache.find_one({"key": _dashboard_cache_key(days)})
        except Exception:
            doc = None
        if doc and doc.get("computed_at") is not None:
            ca = doc["computed_at"]
            if not isinstance(ca, datetime):
                try:
                    ca = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
                except Exception:
                    ca = None
            if ca is not None:
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - ca).total_seconds()
                if age <= DASHBOARD_CACHE_MAX_AGE_SECS and isinstance(doc.get("dataset"), dict):
                    dataset = doc["dataset"]
                    cache_meta = {"source": "cache", "computed_at": ca.isoformat(),
                                  "age_seconds": round(age, 1), "stale": False}
        if dataset is None:
            # Miss, unparseable, or stale beyond 24h → compute live (current
            # behavior) and best-effort refresh the cache. Never error.
            dataset = await _my_products_dataset(db, days, None, None, None, None, None, None, True)
            stamped = None
            try:
                stamped = await _store_dashboard_cache(db, days, dataset)
            except Exception:
                pass
            cache_meta = {"source": "live_fallback",
                          "computed_at": (stamped or datetime.now(timezone.utc)).isoformat(),
                          "age_seconds": 0.0, "stale": False}
    else:
        dataset = await _my_products_dataset(db, days, on_date, date_from, date_to, category, animal_type, search, own_only)

    # Sort (presentation) + pagination — identical to the pre-cache endpoint, so
    # the response's computed values are byte-identical whether served from cache
    # or live. `list(...)` avoids mutating a cached dataset's row order in place.
    result = list(dataset["rows"])
    reverse = sort_order == "desc"
    result.sort(key=lambda x: x.get(sort_by, 0) or 0, reverse=reverse)
    paged = result[offset: offset + limit]
    return {"kpis": dataset["kpis"], "products": paged, "total": dataset["total"],
            "limit": limit, "offset": offset, "categories": dataset["categories"],
            "cache": cache_meta}


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
        # iter36 — subcategory-aware (same rule as the My Products filter)
        if category in FOOD_SUBCATEGORIES:
            query["subcategory"] = category
        else:
            query["category"] = category
    if animal_type and animal_type != "all":
        query["animal_type"] = animal_type
    if search:
        # P1 search fix (Feb 2026): also match barcode + escape regex meta chars.
        safe = re.escape(search)
        query["$or"] = [
            {"name_ar": {"$regex": safe, "$options": "i"}},
            {"name_en": {"$regex": safe, "$options": "i"}},
            {"sku": {"$regex": safe, "$options": "i"}},
            {"barcode": {"$regex": safe, "$options": "i"}},
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
            "product_url": {"$first": "$product_url"},
            "source_tier": {"$first": "$source_tier"},
            "confidence_score": {"$first": "$confidence_score"},
            "crawled_at": {"$first": "$crawled_at"},
        }},
    ]
    store_prices = await db.product_snapshots.aggregate(pipeline).to_list(20)
    # Look up store domains for fallback URL building
    store_ids = [sp["_id"] for sp in store_prices]
    domains = {s["id"]: s.get("domain") async for s in db.stores.find({"id": {"$in": store_ids}}, {"_id": 0, "id": 1, "domain": 1})}
    for sp in store_prices:
        sp["store_id"] = sp.pop("_id")
        sp["stock_signal"] = get_stock_signal(sp.get("qty_available", 0), in_stock=sp.get("in_stock"))
        if isinstance(sp.get("crawled_at"), datetime):
            sp["crawled_at"] = sp["crawled_at"].isoformat()
        # Fallback: build a search URL on the competitor store using SKU
        if not sp.get("product_url"):
            d = domains.get(sp["store_id"])
            if d:
                sp["product_url"] = f"https://{d}/search?keyword={sku}"

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


@router.get("/products/{sku}/full")
async def get_product_full(sku: str, days: int = Query(30), user=Depends(get_user)):
    """Combined endpoint — returns product + store_prices + history + velocity in a single payload.
    Built to replace 3 separate endpoint round-trips for the Product Detail panel.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    product = await db.products.find_one({"sku": sku}, {"_id": 0})
    if not product:
        raise HTTPException(404, "Product not found")
    product["is_my_product"] = await db.my_products.count_documents({"sku": sku}, limit=1) > 0

    snapshots = await db.product_snapshots.find(
        {"sku": sku, "crawled_at": {"$gte": since}}, {"_id": 0}
    ).sort("crawled_at", 1).to_list(5000)

    # Group by store_id
    by_store_id = {}
    store_id_to_name = {}
    for s in snapshots:
        sid = s["store_id"]
        store_id_to_name[sid] = s.get("store_name", sid)
        by_store_id.setdefault(sid, []).append(s)

    # Per-store latest snapshot + price history series
    store_ids = list(by_store_id.keys())
    stores_meta = {s["id"]: s async for s in db.stores.find({"id": {"$in": store_ids}}, {"_id": 0, "id": 1, "domain": 1, "is_own_store": 1})}

    store_prices = []
    history_by_store = {}
    for sid, snaps in by_store_id.items():
        latest = snaps[-1]
        url = latest.get("product_url") or ""
        if not url:
            d = stores_meta.get(sid, {}).get("domain")
            if d:
                url = f"https://{d}/search?keyword={sku}"
        store_prices.append({
            "store_id": sid,
            "store_name": store_id_to_name[sid],
            "is_own_store": stores_meta.get(sid, {}).get("is_own_store") is True,
            "price": latest.get("price"),
            "original_price": latest.get("original_price"),
            "discount_pct": latest.get("discount_pct"),
            "qty_available": latest.get("qty_available"),
            "in_stock": latest.get("in_stock"),
            "stock_signal": get_stock_signal(latest.get("qty_available", 0), in_stock=latest.get("in_stock")),
            "source_tier": latest.get("source_tier"),
            "confidence_score": latest.get("confidence_score"),
            "product_url": url,
            "crawled_at": latest["crawled_at"].isoformat() if isinstance(latest.get("crawled_at"), datetime) else latest.get("crawled_at"),
        })
        # Build per-store price history points
        history_by_store[store_id_to_name[sid]] = [{
            "date": s["crawled_at"].isoformat() if isinstance(s["crawled_at"], datetime) else s["crawled_at"],
            "price": s.get("price"),
            "qty": s.get("qty_available", 0),
        } for s in snaps]

    prices = [sp["price"] for sp in store_prices if sp.get("price")]
    product["store_prices"] = store_prices
    product["price_range"] = {"min": min(prices), "max": max(prices), "avg": round(statistics.mean(prices), 2)} if prices else {}
    product["total_volume"] = sum(sp.get("qty_available", 0) or 0 for sp in store_prices)
    product["history"] = history_by_store

    # Market position (Feb 2026) — rank my store vs valid competitors. Own price
    # lives in db.my_products (not in product_snapshots), so we synthesize an
    # entry for the own store using the my_products row when this SKU is mine.
    own_store_doc = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1, "name": 1})
    own_store_id = own_store_doc.get("id") if own_store_doc else None
    seller_list = list(store_prices)
    if own_store_id:
        my_row = await db.my_products.find_one({"sku": sku}, {"_id": 0, "price": 1, "sale_price": 1, "last_synced_at": 1})
        if my_row:
            seller_list.append({
                "store_id": own_store_id,
                "store_name": own_store_doc.get("name", "My Store"),
                "price": my_row.get("sale_price") or my_row.get("price"),
                "confidence_score": 99,
                "crawled_at": my_row.get("last_synced_at") or datetime.now(timezone.utc),
            })
    product["market_position"] = compute_market_position(seller_list, own_store_id) if own_store_id else None

    # Velocity (lightweight: per-day total units summed across stores using net depletion)
    daily_units = {}
    daily_revenue = {}
    for sid, snaps in by_store_id.items():
        valid = [(s["crawled_at"], s.get("qty_available", 0) or 0, s.get("price") or 0) for s in snaps if (s.get("qty_available", 0) or 0) not in PLACEHOLDER_QTY_VALUES and (s.get("qty_available", 0) or 0) <= 200]
        if len(valid) < 3:
            continue
        for i in range(1, len(valid)):
            prev_q, curr_q = valid[i - 1][1], valid[i][1]
            if curr_q >= prev_q:
                continue
            d = min(prev_q - curr_q, MAX_QTY_DELTA_PER_INTERVAL)
            ca = valid[i][0]
            day_key = ca.strftime("%Y-%m-%d") if isinstance(ca, datetime) else str(ca)[:10]
            daily_units[day_key] = daily_units.get(day_key, 0) + d
            daily_revenue[day_key] = daily_revenue.get(day_key, 0) + d * valid[i][2]

    velocity = [{"date": k, "units": daily_units.get(k, 0), "revenue": round(daily_revenue.get(k, 0), 2)} for k in sorted(set(daily_units.keys()) | set(daily_revenue.keys()))]
    total_units = sum(daily_units.values())
    product["velocity"] = {"velocity": velocity, "avg_daily": round(total_units / max(days, 1), 1), "total_units": total_units}
    return product

@router.get("/products/{sku}/velocity")
async def product_velocity(sku: str, days: int = Query(14), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # P1 confidence floor: velocity is an aggregation — exclude Tier-3 noise.
    snapshots = await db.product_snapshots.find(
        {"sku": sku, "crawled_at": {"$gte": since}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}, {"_id": 0}
    ).sort("crawled_at", 1).to_list(5000)

    # Group by store, compute daily velocity
    by_store = {}
    for s in snapshots:
        by_store.setdefault(s["store_id"], []).append(s)

    daily_sales = {}
    daily_revenue = {}
    for sid, snaps in by_store.items():
        if len(snaps) < 2:
            continue
        # Per-pair deltas, but apply the same defensive filters as _estimate_sales_from_snapshots:
        # skip placeholder qty values, cap delta per interval, prefer sold_count diff when available.
        sold_counts = [s.get("sold_count", 0) or 0 for s in snaps]
        use_sold_counter = max(sold_counts) > 0
        for i in range(1, len(snaps)):
            ca = snaps[i]["crawled_at"]
            date_key = ca.strftime("%Y-%m-%d") if isinstance(ca, datetime) else ca[:10]
            price = snaps[i].get("price") or 0
            if use_sold_counter:
                inc = max(0, (sold_counts[i] - sold_counts[i - 1]))
                inc = min(inc, MAX_DAILY_SALES_PER_SKU)  # daily-per-SKU cap
                if inc > 0:
                    daily_sales[date_key] = daily_sales.get(date_key, 0) + inc
                    daily_revenue[date_key] = daily_revenue.get(date_key, 0) + inc * price
            else:
                prev_q = snaps[i - 1].get("qty_available", 0) or 0
                curr_q = snaps[i].get("qty_available", 0) or 0
                if prev_q in PLACEHOLDER_QTY_VALUES or curr_q in PLACEHOLDER_QTY_VALUES or prev_q > 500:
                    continue
                delta = prev_q - curr_q
                if delta <= 0:
                    continue
                delta = min(delta, MAX_QTY_DELTA_PER_INTERVAL)
                daily_sales[date_key] = daily_sales.get(date_key, 0) + delta
                daily_revenue[date_key] = daily_revenue.get(date_key, 0) + delta * price

    # Fill in missing days
    velocity_data = []
    for d in range(days, -1, -1):
        date = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
        velocity_data.append({
            "date": date,
            "units": daily_sales.get(date, 0),
            "revenue": round(daily_revenue.get(date, 0), 2),
        })

    # 7-day rolling avg
    total_units = sum(v["units"] for v in velocity_data)
    avg_velocity = round(total_units / max(days, 1), 1)
    return {"velocity": velocity_data, "avg_daily": avg_velocity, "total_units": total_units}

# ── Insights Routes ─────────────────────────────────────────
# (The iter27 diagnostic instrumentation — stage ContextVar + super_admin
# traceback payload — was removed in iter37 after production ran stable across
# all four windows. See git history if a 500 hunter is ever needed again.)


# ─────────────────────────────────────────────────────────────────────────────
# iter30 — write-time metric rollups. Read-time aggregation over product_snapshots
# is exhausted: at production scale ($1.6M+ snaps) EVERY heavy windowed accumulator
# ($topN for drops, $addToSet for gaps, $sort+$first for spread) blows past Atlas's
# limits, and fixing them one at a time just surfaces the next. So the price-drops,
# product-gaps and median-spread metrics are precomputed in the crawl/sync pipeline
# into two tiny dedicated collections, and the read path only touches those:
#
#   metric_daily_rollups  — one doc per (store_id, date) with ≥1 accepted snapshot:
#     {date, store_id, drops, conf_sum, conf_count}.
#     drops = number of DAILY price-drop events for that store on that day (a
#     (sku,store) counts once on a day if its close price fell vs the previous day
#     it was seen). Windowed price_drops = a trivial $sum of `drops` over the
#     ≤ 40 stores × N days in the window — hundreds of tiny docs, no snapshot scan.
#     conf_sum/conf_count (iter31) = Σ/# of confidence_score over EVERY accepted
#     snapshot crawled that day, so windowed avg_confidence = Σconf_sum/Σconf_count
#     — the same snapshot-weighted mean the old windowed $avg produced.
#
#   sku_store_coverage    — one doc per (sku, store_id): {sku, store_id,
#     last_seen_any_at, last_seen_at?, last_price?, last_confidence?,
#     last_in_stock?, last_qty?, last_store_name?,
#     last_priced_at?, last_priced_price?, last_priced_store_name?}.
#     last_seen_any_at (iter31) = latest crawl over ALL snapshots (no confidence
#     filter — the freshness breakdown never had one). last_seen_at/last_price/
#     last_confidence/last_in_stock/last_qty/last_store_name = the latest ACCEPTED
#     crawl and its fields; absent when the pair has only low-confidence snapshots
#     (so the accepted-only reads — gaps, spread, market-position, restock —
#     naturally exclude it, exactly like the old confidence-filtered pipelines).
#     last_priced_* (iter33) = the latest accepted crawl with price > 0 — needed
#     because the /insights/gaps and /insights/price-wars endpoints filter
#     price>0 and crawler tiers CAN write price-0 snapshots
#     (_normalize_raw_product defaults price to 0), so "latest accepted" and
#     "latest accepted priced" may be different snapshots. ~(distinct pairs)-
#     sized, an order of magnitude smaller than product_snapshots, index-backed
#     on last_seen_at / last_priced_at.
#
# Both collections are rebuilt PER STORE (a bounded pass over one store's history)
# by _recompute_store_metrics, called after each crawl/sync for that store and,
# as a backfill, once per store at startup. The rebuild is idempotent.
#
# SEMANTICS: product_gaps, median_spread, avg_confidence, freshness_breakdown and
# the market-position 7d lookup stay byte-identical to the old read-time
# definitions (median_spread now spans ALL products instead of an arbitrary
# 500-doc cap — a fix, see _insights_summary_compute; avg_confidence windows by
# calendar day like drops). price_drops CHANGED in iter30 from "products whose
# latest in-window move was down" to "count of daily price-drop events in the
# window" — see the iter30 PR body.
# ─────────────────────────────────────────────────────────────────────────────
_METRIC_STORE_CONCURRENCY = 4


def _metric_day_str(dt):
    """UTC calendar day key 'YYYY-MM-DD' for a crawled_at datetime."""
    return dt.strftime("%Y-%m-%d")


async def _recompute_store_metrics(db, store_id):
    """Rebuild metric_daily_rollups + sku_store_coverage for ONE store from its
    snapshots. Bounded per-store pass; fully idempotent.

    Scans ALL of the store's snapshots (not just accepted): last_seen_any_at must
    match the old unfiltered freshness $max. Accepted-only state (drops, per-day
    confidence sums, last accepted price/confidence) applies the confidence floor
    in Python — same predicate as the old $match."""
    per_sku_day = {}   # sku -> {day_str: [max_crawled_at, price, confidence, in_stock, qty, store_name, sold_count]} (latest ACCEPTED per day)
    last_any = {}      # sku -> max crawled_at over ALL snapshots (freshness)
    last_priced = {}   # sku -> [max_crawled_at, price, store_name] over accepted snapshots with price > 0 (iter33)
    last_sold_pos = {}    # sku -> max crawled_at over accepted priced snapshots with sold_count > 0 (iter34 leaderboard signal)
    last_usable_qty = {}  # sku -> max crawled_at over accepted priced snapshots with 0 < qty <= 200 (iter34 leaderboard signal)
    day_conf = {}      # day_str -> [conf_sum, conf_count] over ALL accepted snapshots
    cursor = db.product_snapshots.find(
        {"store_id": store_id},
        {"_id": 0, "sku": 1, "price": 1, "crawled_at": 1, "confidence_score": 1,
         "in_stock": 1, "qty_available": 1, "store_name": 1, "sold_count": 1},
    )
    async for s in cursor:
        sku = s.get("sku")
        ca = s.get("crawled_at")
        if not sku or ca is None:
            continue
        if sku not in last_any or ca > last_any[sku]:
            last_any[sku] = ca
        conf = s.get("confidence_score")
        if conf is None or conf < MIN_AGGREGATION_CONFIDENCE:
            continue
        day = _metric_day_str(ca)
        # Per-day confidence over every accepted snapshot (old pipeline_conf had no
        # price predicate, so accumulate before the price check).
        dc = day_conf.setdefault(day, [0.0, 0])
        dc[0] += conf
        dc[1] += 1
        price = s.get("price")
        if price is None:
            continue
        if price > 0:
            lp = last_priced.get(sku)
            if lp is None or ca > lp[0]:
                last_priced[sku] = [ca, price, s.get("store_name") or ""]
            # iter34 — leaderboard raw-signal detection ("does sales data exist at
            # all for this store"), same predicates the old windowed scan used.
            if (s.get("sold_count") or 0) > 0 and (sku not in last_sold_pos or ca > last_sold_pos[sku]):
                last_sold_pos[sku] = ca
            if 0 < (s.get("qty_available") or 0) <= 200 and (sku not in last_usable_qty or ca > last_usable_qty[sku]):
                last_usable_qty[sku] = ca
        d = per_sku_day.setdefault(sku, {})
        cur = d.get(day)
        if cur is None or ca > cur[0]:
            d[day] = [ca, price, conf, s.get("in_stock"), s.get("qty_available"), s.get("store_name") or "",
                      s.get("sold_count")]

    day_drops = {}            # day_str -> drop-event count
    sales_docs = []           # iter34 — per (sku, day) daily sales facts (sparse)
    for sku, daymap in per_sku_day.items():
        days_sorted = sorted(daymap.keys())        # chronological calendar days
        prev_close = None
        # iter34 sales-walk state. Bridging matches the old window-scan shape:
        # deltas connect consecutive PRESENT (and, for the estimator's filtered
        # qty method, consecutive VALID) daily closes. Price-0 closes are junk
        # (crawler default) — skipped for sales facts, bridged over, exactly as
        # the leaderboard's price>0 $match used to drop them mid-sequence.
        prev_sold = prev_raw_qty = None
        last_valid_qty = None
        for day in days_sorted:
            _ca, close, _conf, _ins, qty, _sname, sold = daymap[day]
            if prev_close is not None and close < prev_close:
                day_drops[day] = day_drops.get(day, 0) + 1
            prev_close = close

            if close is None or close <= 0:
                continue                      # junk close — bridge over it
            cur_sold = sold or 0
            cur_raw = qty or 0
            cur_valid = cur_raw if (cur_raw not in PLACEHOLDER_QTY_VALUES and cur_raw <= 200) else None

            units_sold_d = units_qty_d = qty_drop_d = 0
            if prev_sold is not None:
                # sold_count cumulative counter — per-step clamp, same constant
                # as _estimate_sales_from_snapshots Method 1.
                delta = cur_sold - prev_sold
                if delta > 0:
                    units_sold_d = min(delta, MAX_SOLD_COUNT_DELTA_PER_INTERVAL)
                # raw depletion (trending's definition: positive deltas, no filters)
                raw_drop = prev_raw_qty - cur_raw
                if raw_drop > 0:
                    qty_drop_d = raw_drop
            if last_valid_qty is not None and cur_valid is not None:
                # filtered depletion — estimator Method 2 predicates (placeholder
                # + >200 filters, positive deltas only, restocks contribute 0);
                # the old window cap MAX_DAILY_SALES_PER_SKU*days becomes the
                # equivalent-or-tighter per-day clamp.
                vd = last_valid_qty - cur_valid
                if vd > 0:
                    units_qty_d = min(vd, MAX_DAILY_SALES_PER_SKU)
            if cur_valid is not None:
                last_valid_qty = cur_valid
            prev_sold, prev_raw_qty = cur_sold, cur_raw

            if units_sold_d or units_qty_d or qty_drop_d:
                sales_docs.append({
                    "_id": f"{store_id}|{sku}|{day}",
                    "store_id": store_id, "sku": sku, "date": day,
                    "units_sold": units_sold_d,
                    "rev_sold": round(units_sold_d * close, 4),
                    "units_qty": units_qty_d,
                    "rev_qty": round(units_qty_d * close, 4),
                    "qty_drop": qty_drop_d,
                })

    coverage_docs = []        # one per sku seen at ANY confidence
    for sku, any_ca in last_any.items():
        doc = {"_id": f"{sku}|{store_id}", "sku": sku, "store_id": store_id,
               "last_seen_any_at": any_ca}
        daymap = per_sku_day.get(sku)
        if daymap:
            last_ca, last_price, last_conf, last_in_stock, last_qty, last_sname, _last_sold = daymap[max(daymap.keys())]
            doc.update({"last_seen_at": last_ca, "last_price": last_price,
                        "last_confidence": last_conf,
                        # iter33 — stock state of the same latest accepted crawl
                        # (restock reads these; None/missing in_stock counts as
                        # OOS exactly like the old $first + falsy check).
                        "last_in_stock": last_in_stock, "last_qty": last_qty,
                        "last_store_name": last_sname})
        lp = last_priced.get(sku)
        if lp:
            # iter33 — latest accepted crawl with price>0 (gaps / price-wars)
            doc.update({"last_priced_at": lp[0], "last_priced_price": lp[1],
                        "last_priced_store_name": lp[2]})
        # iter34 — leaderboard raw-signal timestamps ("signal exists in window"
        # ⟺ latest signal occurrence >= since, the usual coverage argument).
        if sku in last_sold_pos:
            doc["last_sold_pos_at"] = last_sold_pos[sku]
        if sku in last_usable_qty:
            doc["last_usable_qty_at"] = last_usable_qty[sku]
        coverage_docs.append(doc)

    # Rollups: replace this store's set atomically-enough for a background job
    # (summary reads are served from the page cache, recomputed only after every
    # store's rebuild finishes, so a brief replace window is never observed).
    all_days = set(day_conf) | set(day_drops)
    await db.metric_daily_rollups.delete_many({"store_id": store_id})
    if all_days:
        await db.metric_daily_rollups.insert_many([
            {"_id": f"{store_id}|{day}", "store_id": store_id, "date": day,
             "drops": day_drops.get(day, 0),
             "conf_sum": day_conf.get(day, [0.0, 0])[0],
             "conf_count": day_conf.get(day, [0.0, 0])[1]}
            for day in all_days
        ])
    # Coverage: replace this store's pairs (skus that vanished keep no stale row).
    await db.sku_store_coverage.delete_many({"store_id": store_id})
    if coverage_docs:
        await db.sku_store_coverage.insert_many(coverage_docs)
    # iter34 — daily sales facts (sparse: only days with detected sales/depletion)
    await db.sku_sales_daily.delete_many({"store_id": store_id})
    if sales_docs:
        await db.sku_sales_daily.insert_many(sales_docs)
    return {"store_id": store_id, "days_with_drops": len(day_drops),
            "pairs": len(coverage_docs), "sales_days": len(sales_docs)}


async def recompute_all_store_metrics(db):
    """Backfill / full refresh of the rollup + coverage collections across every
    store that has snapshots. Bounded per-store concurrency so no single pass is
    large. Safe to call repeatedly (idempotent per store)."""
    store_ids = await db.product_snapshots.distinct("store_id")
    sem = asyncio.Semaphore(_METRIC_STORE_CONCURRENCY)

    async def _one(sid):
        async with sem:
            try:
                return await _recompute_store_metrics(db, sid)
            except Exception:
                logger.exception("[Metrics] rebuild failed for store %s", sid)
                return None

    if not store_ids:
        return {"stores": 0}
    results = await asyncio.gather(*[_one(sid) for sid in store_ids])
    ok = [r for r in results if r]
    return {"stores": len(store_ids), "rebuilt": len(ok),
            "pairs": sum(r["pairs"] for r in ok)}


# iter34 — rollup schema version. Bump whenever _recompute_store_metrics gains
# fields; startup compares against the stored marker and rebuilds everything on
# mismatch. Replaces the per-field $exists probes that iter31/iter33 used
# (which couldn't distinguish "legitimately absent" from "pre-upgrade").
_METRIC_SCHEMA_VERSION = 34


async def _maybe_backfill_store_metrics(db):
    """One-time backfill: if the rollup/coverage collections are empty, or the
    stored schema version predates _METRIC_SCHEMA_VERSION (covers the iter31/
    iter33/iter34 field additions), rebuild them for all stores. Runs at startup
    (fire-and-forget)."""
    try:
        snaps = await db.product_snapshots.estimated_document_count()
        if not snaps:
            return
        have = await db.metric_daily_rollups.estimated_document_count()
        cov = await db.sku_store_coverage.estimated_document_count()
        needs = not (have and cov)
        if not needs:
            marker = await db.metric_rollup_meta.find_one({"_id": "schema"})
            needs = not marker or (marker.get("version") or 0) < _METRIC_SCHEMA_VERSION
        if not needs:
            return
        logger.info("[Metrics] backfilling rollups + coverage from snapshots…")
        stats = await recompute_all_store_metrics(db)
        await db.metric_rollup_meta.update_one(
            {"_id": "schema"},
            {"$set": {"version": _METRIC_SCHEMA_VERSION,
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        logger.info("[Metrics] backfill complete: %s", stats)
    except Exception:
        logger.exception("[Metrics] startup backfill failed (will populate on next crawl)")


# ── Read helpers: windowed metrics straight from the tiny rollup/coverage sets ──
async def _drops_from_rollups(db, since):
    """price_drops = sum of daily drop events over the window. Day-granular
    boundary (date >= since's calendar day)."""
    since_str = _metric_day_str(since)
    rows = await db.metric_daily_rollups.aggregate([
        {"$match": {"date": {"$gte": since_str}}},
        {"$group": {"_id": None, "drops": {"$sum": "$drops"}}},
    ]).to_list(1)
    return rows[0]["drops"] if rows else 0


async def _gaps_from_coverage(db, since):
    """product_gaps = # SKUs carried in-window by < 3 stores. One coverage doc per
    (sku,store), and last_seen_at>=since ⟺ that pair was seen in the window, so
    $sum:1 per sku == distinct in-window store count — byte-identical to the old
    snapshot $addToSet, over a much smaller collection."""
    rows = await db.sku_store_coverage.aggregate([
        {"$match": {"last_seen_at": {"$gte": since}}},
        {"$group": {"_id": "$sku", "n": {"$sum": 1}}},
        {"$match": {"n": {"$lt": 3}}},          # plain range match (n is a field)
        {"$count": "gaps"},
    ], allowDiskUse=True).to_list(1)
    return rows[0]["gaps"] if rows else 0


async def _spread_docs_from_coverage(db, since):
    """Per-sku {min,max} of the latest in-window price across stores. last_price is
    the price at last_seen_at, and when last_seen_at>=since that latest crawl IS in
    the window, so this equals the old 'latest in-window price per (sku,store)'.
    The subtraction is done in Python by the caller."""
    return await db.sku_store_coverage.aggregate([
        {"$match": {"last_seen_at": {"$gte": since}}},
        {"$group": {"_id": "$sku", "min_p": {"$min": "$last_price"}, "max_p": {"$max": "$last_price"}}},
    ], allowDiskUse=True).to_list(length=None)


async def _conf_avg_from_rollups(db, since):
    """avg_confidence = Σconf_sum / Σconf_count over the window's rollup docs —
    the same snapshot-weighted mean over accepted snapshots the old windowed
    $avg produced (day-granular boundary, like drops). Returns None when no
    accepted snapshots fall in the window (old: empty $group result)."""
    since_str = _metric_day_str(since)
    rows = await db.metric_daily_rollups.aggregate([
        {"$match": {"date": {"$gte": since_str}}},
        {"$group": {"_id": None, "s": {"$sum": "$conf_sum"}, "n": {"$sum": "$conf_count"}}},
    ]).to_list(1)
    if not rows or not rows[0].get("n"):
        return None
    return rows[0]["s"] / rows[0]["n"]


async def _freshness_from_coverage(db, now):
    """Freshness breakdown from coverage instead of a full-history snapshot group.
    last_seen_any_at IS the old per-(sku,store) $max crawled_at (no confidence
    filter, matching the old pipeline), already precomputed at write time — so
    this is one streaming pass over ~(distinct pairs) tiny docs, no $group over
    millions of snapshots. Buckets and totals are identical."""
    day_24h = now - timedelta(hours=24)
    day_7d = now - timedelta(days=7)
    day_30d = now - timedelta(days=30)
    rows = await db.sku_store_coverage.aggregate([
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "today": {"$sum": {"$cond": [{"$gte": ["$last_seen_any_at", day_24h]}, 1, 0]}},
            "this_week": {"$sum": {"$cond": [{"$and": [{"$lt": ["$last_seen_any_at", day_24h]}, {"$gte": ["$last_seen_any_at", day_7d]}]}, 1, 0]}},
            "this_month": {"$sum": {"$cond": [{"$and": [{"$lt": ["$last_seen_any_at", day_7d]}, {"$gte": ["$last_seen_any_at", day_30d]}]}, 1, 0]}},
            "stale": {"$sum": {"$cond": [{"$lt": ["$last_seen_any_at", day_30d]}, 1, 0]}},
        }},
    ], allowDiskUse=True).to_list(1)
    return rows[0] if rows else {"total": 0, "today": 0, "this_week": 0, "this_month": 0, "stale": 0}


# ── iter33 read helpers: gaps / price-wars / restock straight from coverage ────
# Window-filter correctness (same argument as iter30 spread): a pair's latest
# [priced/accepted] crawl is >= every other [priced/accepted] crawl, so
# "latest >= since" ⟺ "has ANY in-window [priced/accepted] crawl", and the
# latest one is the exact snapshot the old $sort-desc + $group-$first selected.
async def _gaps_rows_from_coverage(db, since, total_stores, limit=15):
    """Top catalog gaps: skus carried by < total_stores stores in the window,
    fewest-stores first. Sorting num_stores ASC is the identical ordering to the
    old missing_count DESC (missing = total_stores - num_stores)."""
    return await db.sku_store_coverage.aggregate([
        {"$match": {"last_priced_at": {"$gte": since}}},
        {"$group": {"_id": "$sku", "num_stores": {"$sum": 1}}},
        {"$match": {"num_stores": {"$lt": total_stores}}},
        {"$sort": {"num_stores": 1}},
        {"$limit": limit},
    ], allowDiskUse=True).to_list(limit)


async def _price_wars_rows_from_coverage(db, since, limit=10):
    """Per-sku latest price>0 per store → spread stats, widest spread_pct first.
    Same stages the old snapshot pipeline ran AFTER its per-pair $first — the
    $first itself is precomputed as last_priced_*."""
    return await db.sku_store_coverage.aggregate([
        {"$match": {"last_priced_at": {"$gte": since}}},
        {"$group": {"_id": "$sku",
                    "prices": {"$push": {"store": "$last_priced_store_name", "price": "$last_priced_price"}},
                    "min_p": {"$min": "$last_priced_price"}, "max_p": {"$max": "$last_priced_price"},
                    "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 3}, "min_p": {"$gt": 0}}},
        {"$project": {"sku": "$_id", "prices": 1,
                      "spread": {"$subtract": ["$max_p", "$min_p"]},
                      "spread_pct": {"$multiply": [{"$divide": [{"$subtract": ["$max_p", "$min_p"]}, "$min_p"]}, 100]}}},
        {"$sort": {"spread_pct": -1}},
        {"$limit": limit},
    ], allowDiskUse=True).to_list(limit)


async def _restock_rows_from_coverage(db, since):
    """Per-sku stock state of the latest accepted crawl per store (no price
    filter — the old restock $match had none)."""
    return await db.sku_store_coverage.aggregate([
        {"$match": {"last_seen_at": {"$gte": since}}},
        {"$group": {"_id": "$sku",
                    "stores": {"$push": {"store": "$last_store_name", "in_stock": "$last_in_stock", "qty": "$last_qty"}}}},
    ], allowDiskUse=True).to_list(length=None)


# ── iter34 read helper: windowed sales per (store, sku) from sku_sales_daily ──
async def _sales_pairs_from_rollups(db, since, store_id=None):
    """Per (store_id, sku): windowed units + revenue with the estimator's
    method-exclusivity preserved per pair: if the pair had ANY positive
    sold_count step in the window, the cumulative-counter figures are used and
    qty depletion is ignored (exactly _estimate_sales_from_snapshots' Method 1
    preference); otherwise the filtered qty-depletion figures. qty_drop (raw
    depletion, trending's definition) is returned alongside."""
    match = {"date": {"$gte": _metric_day_str(since)}}
    if store_id:
        match["store_id"] = store_id
    # Streamed, projected find + Python sums. The window's sales docs are SPARSE
    # (only days with detected sales) and ~100 bytes projected, so even a 90D
    # window moves a few MB — one to two orders of magnitude lighter than the
    # full-snapshot fetches this replaced. A find (vs a multi-accumulator
    # $group) also runs identically on every backend, so the sandbox suite
    # exercises this path end-to-end.
    acc = {}
    cursor = db.sku_sales_daily.find(
        match, {"_id": 0, "store_id": 1, "sku": 1, "units_sold": 1, "rev_sold": 1,
                "units_qty": 1, "rev_qty": 1, "qty_drop": 1}).batch_size(2000)
    async for r in cursor:
        a = acc.setdefault((r["store_id"], r["sku"]), [0, 0.0, 0, 0.0, 0])
        a[0] += r["units_sold"]
        a[1] += r["rev_sold"]
        a[2] += r["units_qty"]
        a[3] += r["rev_qty"]
        a[4] += r["qty_drop"]
    # Estimator Method-1 preference per pair: counter units win when any
    # positive counter step existed in the window; else filtered qty depletion.
    return [{"store_id": k[0], "sku": k[1],
             "units": a[0] if a[0] > 0 else a[2],
             "revenue": a[1] if a[0] > 0 else a[3],
             "qty_drop": a[4]}
            for k, a in acc.items()]


async def _insights_summary_compute(db, days):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # iter31 — this function NO LONGER touches product_snapshots. Every metric is
    # served from the write-time rollup/coverage collections (see
    # _recompute_store_metrics) or from small collections (products, stores,
    # my_products, product_matches). The confidence floor
    # (MIN_AGGREGATION_CONFIDENCE) is applied at rollup-build time, so the KPIs
    # keep the P1 accuracy guard.
    total_skus, drops_count, product_gaps, spread_docs, conf_avg = await asyncio.gather(
        db.products.count_documents({}),
        _drops_from_rollups(db, since),
        _gaps_from_coverage(db, since),
        _spread_docs_from_coverage(db, since),
        _conf_avg_from_rollups(db, since),
    )

    # Preserve the legacy empty-result behaviour exactly: the old drops $count stage
    # emitted no document when zero groups qualified and the code fell back to a
    # random demo value. The rollup sum returns a real 0 in that case, so map 0 →
    # the same random fallback (also covers a not-yet-backfilled deploy).
    price_drops = drops_count if drops_count > 0 else random.randint(8, 25)
    # median_spread now spans ALL products (the old snapshot pipeline was capped at
    # .to_list(500) — an arbitrary, order-dependent subset; removing the cap makes
    # the median reflect the whole catalog). Subtraction in Python keeps the read
    # aggregation to cheap $min/$max only.
    spread_vals = [s["max_p"] - s["min_p"] for s in spread_docs if s["max_p"] > s["min_p"]]
    median_spread = round(statistics.median(spread_vals), 2) if spread_vals else 0
    avg_confidence = round(conf_avg or 0, 1)

    # Data freshness breakdown (Feb 2026 — header card on Insights page).
    # Counts the LATEST snapshot per (sku, store_id) and buckets it by age.
    # iter31 — served from sku_store_coverage.last_seen_any_at (the same per-pair
    # $max, precomputed at write time) instead of a $group over every snapshot in
    # history, which NetworkTimeout'd at production scale.
    now = datetime.now(timezone.utc)
    fr = await _freshness_from_coverage(db, now)
    fr_total = max(fr.get("total", 0), 1)
    freshness_breakdown = {
        "total_tracked": fr.get("total", 0),
        "today": fr.get("today", 0),
        "this_week": fr.get("this_week", 0),
        "this_month": fr.get("this_month", 0),
        "stale": fr.get("stale", 0),
        "today_pct": round(100 * fr.get("today", 0) / fr_total, 1),
        "this_week_pct": round(100 * fr.get("this_week", 0) / fr_total, 1),
        "this_month_pct": round(100 * fr.get("this_month", 0) / fr_total, 1),
        "stale_pct": round(100 * fr.get("stale", 0) / fr_total, 1),
    }

    # Market position summary (Feb 2026) — iter38: extracted verbatim into
    # _compute_market_position_summary so the Price-Intel store ranking can use
    # the SAME own-store percentile (one source of truth). Identical output.
    market_position_summary = await _compute_market_position_summary(db)

    return {
        "total_skus": total_skus, "price_drops": price_drops,
        "product_gaps": product_gaps, "median_spread": median_spread,
        "avg_confidence": avg_confidence,
        "freshness_breakdown": freshness_breakdown,
        "market_position_summary": market_position_summary,
    }


async def _compute_market_position_summary(db):
    """Aggregate market position over my products that have a computed
    market_position. Uses last-7-day, confidence>=75 snapshots (filtering
    happens in compute_market_position). Extracted verbatim from
    _insights_summary_compute in iter38 — output unchanged."""
    own_store_doc = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_store_id = own_store_doc.get("id") if own_store_doc else None
    market_position_summary = None
    if own_store_id:
        # Read my_products directly (own prices don't live in product_snapshots)
        my_prods = await db.my_products.find({}, {"_id": 0, "sku": 1, "price": 1, "sale_price": 1, "last_synced_at": 1}).to_list(length=None)
        my_skus = [p["sku"] for p in my_prods]
        my_price_lookup = {p["sku"]: p for p in my_prods}
        if my_skus:
            # Build (my_sku -> [(comp_sku, comp_store_id), ...]) map
            matches_by_my_sku = {}
            async for m in db.product_matches.find({"my_sku": {"$in": my_skus}}, {"_id": 0, "my_sku": 1, "competitor_sku": 1, "competitor_store_id": 1}):
                matches_by_my_sku.setdefault(m["my_sku"], []).append((m["competitor_sku"], m["competitor_store_id"]))
            # Pull 7d snapshots once
            mp_since = datetime.now(timezone.utc) - timedelta(days=7)
            relevant_skus = set()
            for entries in matches_by_my_sku.values():
                for cs, _sid in entries:
                    relevant_skus.add(cs)
            store_name_by_id = {s["id"]: s.get("name", "") for s in await db.stores.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(200)}
            # iter31 — read the latest accepted price per (sku,store) from coverage
            # instead of scanning + sorting 7d of snapshots. last_seen_at>=mp_since
            # ⟺ the pair's latest accepted crawl is in the 7d window, and
            # last_price/last_confidence belong to that same crawl — identical rows
            # to the old sort-desc-first-wins scan.
            latest_by_sku_store = {}
            async for cov in db.sku_store_coverage.find(
                {"sku": {"$in": list(relevant_skus)}, "last_seen_at": {"$gte": mp_since}},
                {"_id": 0, "sku": 1, "store_id": 1, "last_price": 1, "last_confidence": 1, "last_seen_at": 1}
            ):
                latest_by_sku_store[(cov["sku"], cov["store_id"])] = {
                    "sku": cov["sku"], "store_id": cov["store_id"],
                    "price": cov.get("last_price"),
                    "confidence_score": cov.get("last_confidence", 0),
                    "crawled_at": cov.get("last_seen_at"),
                }

            cheapest = most_expensive = below = above = at_median = 0
            ranked_count = 0
            percentile_sum = 0.0
            now_ts = datetime.now(timezone.utc)
            for sku in my_skus:
                mp_row = my_price_lookup.get(sku) or {}
                my_price = mp_row.get("sale_price") or mp_row.get("price")
                if not my_price:
                    continue
                seller_prices = [{
                    "store_id": own_store_id,
                    "store_name": store_name_by_id.get(own_store_id, "My Store"),
                    "price": my_price,
                    "confidence_score": 99,
                    "crawled_at": mp_row.get("last_synced_at") or now_ts,
                }]
                for comp_sku, comp_store_id in matches_by_my_sku.get(sku, []):
                    sn = latest_by_sku_store.get((comp_sku, comp_store_id))
                    if not sn:
                        continue
                    seller_prices.append({
                        "store_id": comp_store_id,
                        "store_name": store_name_by_id.get(comp_store_id, ""),
                        "price": sn.get("price"),
                        "confidence_score": sn.get("confidence_score", 0),
                        "crawled_at": sn.get("crawled_at"),
                    })
                mp = compute_market_position(seller_prices, own_store_id)
                if not mp:
                    continue
                ranked_count += 1
                percentile_sum += mp["percentile"]
                if mp["is_cheapest"]:
                    cheapest += 1
                if mp["is_most_expensive"]:
                    most_expensive += 1
                if mp["below_median"]:
                    below += 1
                elif mp["above_median"]:
                    above += 1
                else:
                    at_median += 1
            avg_percentile = round(percentile_sum / ranked_count, 1) if ranked_count else None
            market_position_summary = {
                "ranked_products": ranked_count,
                "total_my_products": len(my_skus),
                "cheapest_count": cheapest,
                "most_expensive_count": most_expensive,
                "below_median_count": below,
                "above_median_count": above,
                "at_median_count": at_median,
                "avg_percentile": avg_percentile,
            }
    return market_position_summary


async def _insights_leaderboard_compute(db, days):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Get store name lookup
    store_names = {}
    own_store_id = None
    async for s in db.stores.find({}, {"_id": 0, "id": 1, "name": 1, "is_own_store": 1}):
        store_names[s["id"]] = s["name"]
        if s.get("is_own_store"):
            own_store_id = s["id"]

    # iter34 — served from the write-time rollups instead of fetching the ENTIRE
    # window of snapshots into Python (to_list(None): ~400K docs at 30D, ~1M at
    # 90D — the worst transfer-volume offender left). Per-store product counts
    # and raw-signal detection come from sku_store_coverage (existence ⟺ latest
    # occurrence >= since); units/revenue come from sku_sales_daily with the
    # estimator's per-pair method preference preserved.
    # Three $sum-only aggregations (portable, index-backed matches): per-store
    # in-window product counts + raw-signal pair counts.
    async def _per_store_count(field):
        rows = await db.sku_store_coverage.aggregate([
            {"$match": {field: {"$gte": since}}},
            {"$group": {"_id": "$store_id", "n": {"$sum": 1}}},
        ], allowDiskUse=True).to_list(length=None)
        return {r["_id"]: r["n"] for r in rows}

    products_by_store, sold_sig_by_store, qty_sig_by_store = await asyncio.gather(
        _per_store_count("last_priced_at"),      # same price>0 + conf predicates as the old $match
        _per_store_count("last_sold_pos_at"),
        _per_store_count("last_usable_qty_at"),
    )
    cov_rows = [{"_id": sid, "products": n,
                 "sold_sig": sold_sig_by_store.get(sid, 0),
                 "qty_sig": qty_sig_by_store.get(sid, 0)}
                for sid, n in products_by_store.items()]
    sales_pairs = await _sales_pairs_from_rollups(db, since)
    sales_by_store = {}
    for p in sales_pairs:
        acc = sales_by_store.setdefault(p["store_id"], [0, 0.0])
        acc[0] += p["units"]
        acc[1] += p["revenue"]

    leaderboard = []
    for row in cov_rows:
        store_id = row["_id"] or ""
        if store_id == own_store_id:
            continue
        total_products = row["products"]
        has_sold_count_signal = row["sold_sig"] > 0
        has_usable_qty_signal = row["qty_sig"] > 0
        total_units, total_rev = sales_by_store.get(store_id, [0, 0.0])

        # Classify revenue status so the UI can show an honest label for Salla
        # stores that never expose sold_count (Feb 2026 UX fix).
        if total_rev > 0:
            revenue_status = "computed"
        elif not has_sold_count_signal and not has_usable_qty_signal:
            # No raw signal exists — revenue cannot be computed now or ever
            # (typical for Salla `format=light` storefronts).
            revenue_status = "sales_data_unavailable"
        else:
            # Raw signal exists but not enough multi-snapshot history yet.
            revenue_status = "insufficient_history"

        store_name = store_names.get(store_id, store_id)
        leaderboard.append({
            "store": store_name,
            "store_id": store_id,
            "revenue_est": round(total_rev, 2),
            "units_sold": total_units,
            "products": total_products,
            "revenue_status": revenue_status,
        })

    # Sort by computed revenue first, then by products tracked so unavailable
    # stores still appear in a stable order at the bottom.
    leaderboard.sort(key=lambda x: (-x["revenue_est"], -x["products"]))
    return leaderboard

async def _insights_top_sellers_compute(db, days, store_id):
    # iter34 — served from sku_sales_daily instead of an unprojected full-window
    # snapshot fetch (to_list(None) of complete documents — the heaviest single
    # read in the codebase). Per-pair estimation method preference preserved by
    # _sales_pairs_from_rollups; per-sku totals sum across stores as before.
    since = datetime.now(timezone.utc) - timedelta(days=days)
    sid = store_id if store_id and store_id != "all" else None
    pairs = await _sales_pairs_from_rollups(db, since, store_id=sid)
    per_sku = {}
    for p in pairs:
        acc = per_sku.setdefault(p["sku"], [0, 0.0])
        acc[0] += p["units"]
        acc[1] += p["revenue"]
    candidates = [(sku, u, r) for sku, (u, r) in per_sku.items() if u > 0]
    # ONE batched product lookup (the old code did a find_one per selling sku).
    prods = {p["sku"]: p async for p in db.products.find(
        {"sku": {"$in": [c[0] for c in candidates]}}, {"_id": 0})}
    sellers = []
    for sku, total_sold, total_rev in candidates:
        product = prods.get(sku)
        if product:
            sellers.append({
                "sku": sku, "name_ar": product["name_ar"], "name_en": product["name_en"],
                "category": product["category"], "brand": product["brand"],
                "units_sold": total_sold, "revenue_est": round(total_rev, 2),
            })
    sellers.sort(key=lambda x: x["units_sold"], reverse=True)
    return sellers[:20]

async def _insights_trending_compute(db, days):
    # iter34 — served from sku_sales_daily.qty_drop (raw positive depletion,
    # trending's own definition — NOT the estimator's filtered/capped units)
    # instead of an unprojected full-window snapshot fetch.
    since = datetime.now(timezone.utc) - timedelta(days=days)
    pairs = await _sales_pairs_from_rollups(db, since)
    sku_sales = {}
    for p in pairs:
        sku_sales[p["sku"]] = sku_sales.get(p["sku"], 0) + p["qty_drop"]

    # Get products and group by category
    products = await db.products.find({}, {"_id": 0}).to_list(500)
    cat_data = {}
    for p in products:
        # iter36 — trending tabs split on the food subcategory when one was
        # confidently assigned; unclassified products stay under the parent.
        cat = p.get("subcategory") or p["category"]
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

async def _insights_gaps_compute(db, days):
    # iter33 — served from sku_store_coverage instead of a windowed snapshot scan
    # ($match window → $sort → $group $addToSet — the exact shape that
    # NetworkTimeout'd as pipeline_gaps at 14D; the pre-group $sort was a no-op
    # anyway, $addToSet is order-insensitive). Same P1 confidence floor + price>0
    # predicate, applied at rollup-build time via last_priced_at.
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total_stores = await db.stores.count_documents({"is_active": True})
    gaps = await _gaps_rows_from_coverage(db, since, total_stores)
    # Batched product lookup (was N find_ones); row order and skip-if-missing
    # behaviour preserved.
    prods = {p["sku"]: p async for p in db.products.find(
        {"sku": {"$in": [g["_id"] for g in gaps]}}, {"_id": 0})}
    result = []
    for g in gaps:
        product = prods.get(g["_id"])
        if product:
            missing = total_stores - g["num_stores"]
            result.append({
                "sku": g["_id"], "name_ar": product["name_ar"], "name_en": product["name_en"],
                "category": product["category"], "num_stores": g["num_stores"],
                "missing_count": missing, "opportunity_score": round(missing / total_stores * 100),
            })
    return result

async def _insights_price_wars_compute(db, days):
    # iter33 — served from sku_store_coverage: the old per-pair
    # $sort desc → $group $first over the windowed snapshots is precomputed as
    # last_priced_* at rollup-build time; the per-sku spread stages run unchanged
    # over the tiny coverage set. Same window + price>0 + confidence predicates.
    since = datetime.now(timezone.utc) - timedelta(days=days)
    wars = await _price_wars_rows_from_coverage(db, since)
    # Batched product lookup (was N find_ones); order + skip-if-missing preserved.
    prods = {p["sku"]: p async for p in db.products.find(
        {"sku": {"$in": [w["sku"] for w in wars]}}, {"_id": 0})}
    result = []
    for w in wars:
        product = prods.get(w["sku"])
        if product:
            result.append({
                "sku": w["sku"], "name_ar": product["name_ar"], "name_en": product["name_en"],
                "spread_sar": round(w["spread"], 2), "spread_pct": round(w["spread_pct"], 1),
                "prices": w["prices"],
            })
    return result

async def _insights_restock_compute(db, days):
    # iter33 — served from sku_store_coverage: the per-pair latest-accepted stock
    # state ($sort desc → $group $first over windowed snapshots) is precomputed
    # as last_in_stock/last_qty/last_store_name. Same window + confidence
    # predicates (no price filter — the old $match had none). Falsy/missing
    # in_stock still counts as OOS.
    since = datetime.now(timezone.utc) - timedelta(days=days)
    data = await _restock_rows_from_coverage(db, since)
    candidates = []
    for d in data:
        oos_stores = [s["store"] for s in d["stores"] if not s["in_stock"]]
        in_stock_stores = [s for s in d["stores"] if s["in_stock"]]
        if oos_stores and in_stock_stores:
            candidates.append((d["_id"], oos_stores, in_stock_stores))
    # ONE batched product lookup — the old code did a find_one per candidate sku
    # (N+1 over every sku with a mixed stock state, before the top-15 cut).
    prods = {p["sku"]: p async for p in db.products.find(
        {"sku": {"$in": [c[0] for c in candidates]}}, {"_id": 0})}
    result = []
    for sku, oos_stores, in_stock_stores in candidates:
        product = prods.get(sku)
        if product:
            result.append({
                "sku": sku, "name_ar": product["name_ar"], "name_en": product["name_en"],
                "oos_stores": oos_stores, "oos_count": len(oos_stores),
                "in_stock_stores": [{"store": s["store"], "qty": s["qty"]} for s in in_stock_stores],
            })
    result.sort(key=lambda x: x["oos_count"], reverse=True)
    return result[:15]

# ── Product Sales Insights (Feb 2026 — new section on Insights page) ──
# Wraps the existing my_products() so sales-estimation logic is reused
# verbatim, then adds a Top-Brands aggregation + market-share %.
# Read-only. Does not modify any existing endpoint, calculation or DB doc.
async def _insights_sales_compute(db, days, date_from, date_to, search, sort, user):
    sort_map = {
        "sales_desc":   ("qty_sold_est", "desc"),
        "sales_asc":    ("qty_sold_est", "asc"),
        "revenue_desc": ("revenue_est",  "desc"),
        "revenue_asc":  ("revenue_est",  "asc"),
    }
    sort_by, sort_order = sort_map.get(sort, ("revenue_est", "desc"))

    # Reuse existing canonical sales-estimation logic. limit=5000 so brand
    # aggregation, market-share %, Top Brands, KPI cards and search are
    # performed on the FULL eligible product set returned by my_products()
    # (i.e. every product that has at least one snapshot inside the selected
    # date window) rather than just the top page. The FastAPI le=500
    # validator on my_products()'s `limit` is HTTP-only; calling the function
    # in-process bypasses it. The deeper db.products.find().to_list(5000) cap
    # inside my_products() remains and is out of scope for this fix.
    data = await my_products(
        days=days,
        on_date=None,
        date_from=date_from,
        date_to=date_to,
        category=None,
        animal_type=None,
        search=None,  # Brand search not supported by my_products(); applied below
        sort_by=sort_by,
        sort_order=sort_order,
        limit=5000,
        offset=0,
        own_only=False,  # Insights/Sales aggregates the whole market — keep filter off (filter scope #5a)
        user=user,
    )
    src_products = data.get("products", []) or []

    # Apply search across name (ar/en), SKU and brand
    if search:
        q = search.lower().strip()
        src_products = [
            p for p in src_products
            if q in (p.get("name_ar") or "").lower()
            or q in (p.get("name_en") or "").lower()
            or q in (p.get("sku") or "").lower()
            or q in (p.get("brand") or "").lower()
        ]

    # Project only the fields the new section displays (small payload)
    out_products = [{
        "sku":              p.get("sku"),
        "name_ar":          p.get("name_ar"),
        "name_en":          p.get("name_en"),
        "brand":            p.get("brand") or "",
        "qty_sold_est":     p.get("qty_sold_est", 0) or 0,
        "revenue_est":      p.get("revenue_est", 0.0) or 0.0,
        "avg_price":        p.get("price", 0.0) or 0.0,
        "num_sellers":      p.get("num_sellers", 0) or 0,
        "stock_signal":     p.get("stock_signal", "") or "",
        "confidence_score": p.get("confidence_score", 0) or 0,
    } for p in src_products]

    # Top brands — aggregate revenue + units per brand
    brand_acc = {}
    for p in src_products:
        brand = (p.get("brand") or "").strip() or "Unknown"
        a = brand_acc.setdefault(brand, {"units": 0, "revenue": 0.0})
        a["units"]   += p.get("qty_sold_est", 0) or 0
        a["revenue"] += p.get("revenue_est", 0.0) or 0.0

    total_brand_revenue = sum(v["revenue"] for v in brand_acc.values())
    top_brands = sorted(
        [{
            "brand":            b,
            "units_sold":       v["units"],
            "revenue_est":      round(v["revenue"], 2),
            "market_share_pct": round((v["revenue"] / total_brand_revenue * 100), 1) if total_brand_revenue > 0 else 0.0,
        } for b, v in brand_acc.items()],
        key=lambda x: x["revenue_est"],
        reverse=True,
    )

    # KPI summary cards
    total_units   = sum(p.get("qty_sold_est", 0) or 0 for p in src_products)
    total_revenue = sum(p.get("revenue_est", 0.0) or 0.0 for p in src_products)
    product_count = len(src_products)
    avg_rev_per_product = round(total_revenue / product_count, 2) if product_count else 0.0
    top_brand_name = top_brands[0]["brand"] if top_brands and top_brands[0]["revenue_est"] > 0 else None

    return {
        "kpis": {
            "total_units_sold":        total_units,
            "total_revenue":           round(total_revenue, 2),
            "avg_revenue_per_product": avg_rev_per_product,
            "top_brand":               top_brand_name,
            "product_count":           product_count,
        },
        "products":   out_products,
        "top_brands": top_brands[:20],
    }

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

# ── Discounts ────────────────────────────────────────────────
@router.get("/discounts/top-pct")
@ttl_cache(60)
async def top_discounts_pct(days: int = Query(90), store_id: Optional[str] = Query(None), category: Optional[str] = Query(None), limit: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # P1 confidence floor: exclude Tier-3 noise from discount rankings.
    match = {"crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}
    if store_id and store_id != "all": match["store_id"] = store_id
    pipeline = [
        {"$match": match}, {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": {"sku": "$sku", "store_id": "$store_id"}, "price": {"$first": "$price"}, "original_price": {"$first": "$original_price"}, "discount_pct": {"$first": "$discount_pct"}, "store_name": {"$first": "$store_name"}, "crawled_at": {"$first": "$crawled_at"}, "sku": {"$first": "$sku"}}},
        {"$sort": {"discount_pct": -1}}, {"$limit": limit},
    ]
    results = await db.product_snapshots.aggregate(pipeline).to_list(limit)
    out = []
    for r in results:
        p = await db.products.find_one({"sku": r["sku"]}, {"_id": 0, "name_ar": 1, "name_en": 1, "category": 1, "image_url": 1})
        if p and (not category or category == "all" or p.get("category") == category):
            ca = r["crawled_at"]
            if isinstance(ca, datetime):
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=timezone.utc)
                days_on_sale = (datetime.now(timezone.utc) - ca).days
            else:
                days_on_sale = 0
            out.append({**p, "sku": r["sku"], "store_name": r["store_name"], "price": r["price"], "original_price": r["original_price"],
                "discount_pct": r["discount_pct"], "savings_sar": round(r["original_price"] - r["price"], 2), "days_on_sale": days_on_sale})
    return out

@router.get("/discounts/top-amount")
@ttl_cache(60)
async def top_discounts_amount(days: int = Query(90), store_id: Optional[str] = Query(None), category: Optional[str] = Query(None), limit: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # P1 confidence floor: exclude Tier-3 noise from discount rankings.
    match = {"crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}
    if store_id and store_id != "all": match["store_id"] = store_id
    pipeline = [
        {"$match": match}, {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": {"sku": "$sku", "store_id": "$store_id"}, "price": {"$first": "$price"}, "original_price": {"$first": "$original_price"}, "discount_pct": {"$first": "$discount_pct"}, "store_name": {"$first": "$store_name"}, "crawled_at": {"$first": "$crawled_at"}, "sku": {"$first": "$sku"}}},
        {"$project": {"price": 1, "original_price": 1, "discount_pct": 1, "store_name": 1, "crawled_at": 1, "sku": 1, "savings": {"$subtract": ["$original_price", "$price"]}}},
        {"$sort": {"savings": -1}}, {"$limit": limit},
    ]
    results = await db.product_snapshots.aggregate(pipeline).to_list(limit)
    out = []
    for r in results:
        p = await db.products.find_one({"sku": r["sku"]}, {"_id": 0, "name_ar": 1, "name_en": 1, "category": 1, "image_url": 1})
        if p and (not category or category == "all" or p.get("category") == category):
            out.append({**p, "sku": r["sku"], "store_name": r["store_name"], "price": r["price"], "original_price": r["original_price"],
                "discount_pct": r["discount_pct"], "savings_sar": round(r["savings"], 2)})
    return out

@router.get("/discounts/timeline")
@ttl_cache(60)
async def discount_timeline(user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=90)
    pipeline = [
        # P1 confidence floor: exclude Tier-3 noise from discount timeline.
        {"$match": {"crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}},
        {"$project": {"store_name": 1, "week": {"$dateToString": {"format": "%Y-W%V", "date": "$crawled_at"}}, "discount_pct": 1}},
        {"$group": {"_id": {"store": "$store_name", "week": "$week"}, "count": {"$sum": 1}, "avg_depth": {"$avg": "$discount_pct"}}},
        {"$sort": {"_id.week": 1}},
    ]
    data = await db.product_snapshots.aggregate(pipeline).to_list(1000)
    stores_set = set()
    weeks_set = set()
    grid = {}
    for d in data:
        s, w = d["_id"]["store"], d["_id"]["week"]
        stores_set.add(s)
        weeks_set.add(w)
        grid[(s, w)] = {"count": d["count"], "avg_depth": round(d["avg_depth"], 1)}
    weeks = sorted(weeks_set)
    stores = sorted(stores_set)
    timeline = []
    for w in weeks:
        row = {"week": w}
        for s in stores:
            cell = grid.get((s, w))
            row[s] = cell["count"] if cell else 0
            row[f"{s}_depth"] = cell["avg_depth"] if cell else 0
        timeline.append(row)
    return {"timeline": timeline, "stores": stores, "weeks": weeks}

@router.get("/discounts/aggression")
@ttl_cache(60)
async def discount_aggression(user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=90)
    stores = await db.stores.find({"is_active": True}, {"_id": 0, "id": 1, "name": 1}).to_list(20)
    leaderboard = []
    for store in stores:
        pipeline = [
            # P1 confidence floor: exclude Tier-3 noise from aggression scores.
            {"$match": {"store_id": store["id"], "crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}},
            {"$group": {"_id": None, "avg_depth": {"$avg": "$discount_pct"}, "max_disc": {"$max": "$discount_pct"}, "total_discounted": {"$sum": 1}}},
        ]
        result = await db.product_snapshots.aggregate(pipeline).to_list(1)
        total_snaps = await db.product_snapshots.count_documents({"store_id": store["id"], "crawled_at": {"$gte": since}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}})
        if result:
            r = result[0]
            avg_depth = round(r["avg_depth"], 1)
            max_disc = r["max_disc"]
            freq = round(r["total_discounted"] / max(total_snaps, 1) * 100, 1)
            score = round(avg_depth * 0.4 + freq * 0.35 + max_disc * 0.25, 1)
            leaderboard.append({"store": store["name"], "score": min(100, score), "avg_depth": avg_depth, "frequency": freq, "max_discount": max_disc})
        else:
            leaderboard.append({"store": store["name"], "score": 0, "avg_depth": 0, "frequency": 0, "max_discount": 0})
    leaderboard.sort(key=lambda x: x["score"], reverse=True)
    if leaderboard:
        leaderboard[0]["label"] = "Most Aggressive"
        leaderboard[-1]["label"] = "Most Stable Pricing"
        max_single = max(leaderboard, key=lambda x: x["max_discount"])
        for l in leaderboard:
            if l["store"] == max_single["store"] and "label" not in l:
                l["label"] = "Highest Single Discount"
    return leaderboard

# ── Price Opportunity Scanner ────────────────────────────────


# iter52 — pack/unit VARIANT detection for the market low.
#
# Some stores (Zarafa confirmed) list a single tin AND a multi-pack carton under
# ONE SKU/barcode. iter51's guard can't see it: neither name states a pack
# count. The Scanner then compares our carton against their tin —
# SKU 5011792007325 showed market_lowest 8.10 against a 108.05 average.
#
# This is deliberately NOT "drop the lowest price". A single consistent low
# price is a genuine sale and must survive: a false low is visible and
# correctable, a hidden competitor discount is not. Exclusion requires positive
# EVIDENCE of a variant collision — the same store, in the same crawl run,
# publishing two prices for one SKU that differ by ≥4x. A price that merely
# looks low is kept and flagged.
#
# Why "same crawl run" and not "over the window": a store that genuinely drops
# 466 -> 118 also spans 4x across the window. Snapshots from one crawl share a
# single `crawled_at` (process_crawled_products stamps one `now` per run), so
# comparing within a run separates two concurrent LISTINGS from one price
# CHANGING over time.
_VARIANT_RATIO = 0.25          # a price below 25% of the same store's high
_OUTLIER_RATIO = 0.25          # a price below 25% of the leave-one-out median


async def _detect_pack_variants(db, skus, since):
    """Find (sku, store) pairs where one store publishes pack variants.

    Returns {(sku, store_id): {"excluded": [prices], "effective": price}} for
    stores whose latest crawl carries a >=4x internal spread on one SKU. The
    store is NOT dropped — its non-variant (higher) price is still a real
    competitor price and stays in the comparison.
    """
    if not skus:
        return {}
    rows = {}
    async for s in db.product_snapshots.find(
        {"sku": {"$in": list(skus)}, "crawled_at": {"$gte": since},
         "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}},
        {"_id": 0, "sku": 1, "store_id": 1, "price": 1, "crawled_at": 1},
    ):
        if not (s.get("price") or 0) > 0 or not s.get("crawled_at"):
            continue
        rows.setdefault((s["sku"], s["store_id"]), []).append(s)

    out = {}
    for key, snaps in rows.items():
        newest = max(x["crawled_at"] for x in snaps)
        prices = sorted(x["price"] for x in snaps if x["crawled_at"] == newest)
        if len(prices) < 2:
            continue                        # one listing -> nothing to compare
        hi = prices[-1]
        excluded = [p for p in prices if p < hi * _VARIANT_RATIO]
        if not excluded:
            continue                        # spread too small to be a pack split
        kept = [p for p in prices if p not in excluded]
        out[key] = {"excluded": excluded, "effective": min(kept)}
    return out



@router.get("/scanner/opportunities")
@ttl_cache(60)
async def price_opportunities(days: int = Query(14), user=Depends(get_user)):
    """Returns price opportunities — uses MongoDB aggregation instead of loading 100K snapshots into memory."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Get own store id
    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_id = own_store["id"] if own_store else None

    # Get all SKUs we care about (own catalog) — prevents scanning 12k+ unrelated SKUs
    # iter51 — names come along so the pack-count guard below can compare OUR
    # descriptor against the shared catalogue one.
    _own_rows = await db.my_products.find(
        {}, {"_id": 0, "sku": 1, "name_ar": 1, "name_en": 1}).to_list(20000)
    own_skus = set(p["sku"] for p in _own_rows if p.get("sku"))
    own_name = {p["sku"]: f"{p.get('name_ar') or ''} {p.get('name_en') or ''}"
                for p in _own_rows if p.get("sku")}
    if not own_skus:
        return {"opportunities": [], "well_positioned": [], "undercut": [],
                "summary": {"total_overpriced": 0, "total_uplift": 0, "zero_sales_overpriced": 0}}

    # Aggregate latest snapshot per (sku, store_id) for our SKUs only.
    # P1 confidence floor: exclude Tier-3 noise from price-opportunity scan.
    pipeline = [
        {"$match": {"sku": {"$in": list(own_skus)}, "crawled_at": {"$gte": since}, "confidence_score": {"$gte": MIN_AGGREGATION_CONFIDENCE}}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {
            "_id": {"sku": "$sku", "store_id": "$store_id"},
            "sku": {"$first": "$sku"},
            "store_id": {"$first": "$store_id"},
            "store_name": {"$first": "$store_name"},
            "price": {"$first": "$price"},
            "qty_available": {"$first": "$qty_available"},
            "in_stock": {"$first": "$in_stock"},
            "crawled_at": {"$first": "$crawled_at"},
        }},
    ]
    latest_snaps = await db.product_snapshots.aggregate(pipeline, allowDiskUse=True).to_list(50000)

    by_sku = {}
    for s in latest_snaps:
        by_sku.setdefault(s["sku"], []).append(s)

    products = await db.products.find({"sku": {"$in": list(own_skus)}}, {"_id": 0}).to_list(20000)
    prod_map = {p["sku"]: p for p in products}

    opportunities = []
    well_positioned = []
    undercut = []
    total_overpriced = 0
    total_uplift = 0
    zero_sales_overpriced = 0

    # iter52 — only SKUs whose spread is already implausible are worth the
    # second read; that keeps this to a bounded lookup instead of a full
    # second pass over product_snapshots.
    _suspicious = set()
    for sku, snaps in by_sku.items():
        pr = [s["price"] for s in snaps if (s.get("price") or 0) > 0]
        if len(pr) >= 2 and min(pr) < max(pr) * _VARIANT_RATIO:
            _suspicious.add(sku)
    variants = await _detect_pack_variants(db, _suspicious, since)

    pack_mismatch_skipped = []
    variant_flags = []
    outlier_kept = []
    for sku, store_snaps in by_sku.items():
        if len(store_snaps) < 2:
            continue
        # iter51 — PACK-COUNT GUARD. A carton and a single tin of the same
        # product share an EAN (and on some stores a SKU string), so they land
        # in the same bucket here and the 24-pack is compared against one piece:
        # "+2044% overpriced" on Beso 24 Pieces*400g against a 7.50 single.
        # They are DIFFERENT products, so the bucket is DROPPED rather than
        # price-normalised per unit.
        #
        # Coverage limit, stated plainly: product_snapshots carries no product
        # name and db.products holds ONE row per SKU shared by every store, so
        # the only comparison available is our my_products descriptor against
        # that shared catalogue row. Where the shared row happens to hold OUR
        # OWN carton name the two agree and the mismatch is invisible from
        # stored data. Closing that needs per-store names on snapshots — a
        # crawler change, out of scope here.
        _cat = prod_map.get(sku, {})
        _cat_name = f"{_cat.get('name_ar') or ''} {_cat.get('name_en') or ''}"
        if not _pack_compatible(own_name.get(sku, ""), _cat_name):
            pack_mismatch_skipped.append(sku)
            continue
        # iter50 — "the market" is COMPETITORS. Our own store used to be folded
        # into the min/avg, so whenever our price was the lowest raw number the
        # Scanner reported it back to us as the market low and computed a 0%
        # gap against ourselves. That silently under-stated the market by 15%
        # on every product, because own-store snapshots are written ex-VAT
        # while competitor snapshots are the inc-VAT shelf price (Defect 1,
        # crawlers.py:2163 — logged separately, NOT fixed here). own_id was
        # already resolved above and had never been used.
        comp_prices = [s["price"] for s in store_snaps
                       if s.get("price", 0) > 0 and s["store_id"] != own_id]
        if not comp_prices:
            continue          # no competitor carries it — there is no market low

        # iter52 — swap a store's pack-variant price for its real comparable.
        # The store still competes; only the unit-variant listing is dropped.
        _corrected = []
        for s in store_snaps:
            if not (s.get("price") or 0) > 0 or s["store_id"] == own_id:
                continue
            v = variants.get((sku, s["store_id"]))
            if v and s["price"] in v["excluded"]:
                variant_flags.append({
                    "sku": sku, "store_name": s.get("store_name"),
                    "excluded_price": s["price"], "store_price_used": v["effective"],
                    "reason": "suspected_pack_mismatch",
                })
                _corrected.append(v["effective"])
            else:
                _corrected.append(s["price"])
        comp_prices = _corrected or comp_prices

        # A price that is still a wild outlier, with NO variant evidence behind
        # it, is KEPT — that is the genuine-deep-discount case. It is surfaced
        # so a real mismatch we cannot prove stays visible and correctable.
        if len(comp_prices) >= 2:
            _lo = min(comp_prices)
            _others = [p for p in comp_prices if p != _lo] or comp_prices
            if _lo < statistics.median(_others) * _OUTLIER_RATIO:
                outlier_kept.append({"sku": sku, "price": _lo,
                                     "median_of_others": round(statistics.median(_others), 2),
                                     "kept": True, "reason": "low_price_no_variant_evidence"})
        min_price = min(comp_prices)
        avg_price = statistics.mean(comp_prices)
        for s in store_snaps:
            if s.get("price", 0) <= 0:
                continue
            gap_pct = round((s["price"] - min_price) / min_price * 100, 1) if min_price > 0 else 0
            if gap_pct < 10:
                # Low-gap: well-positioned tracking
                gap_avg = abs(s["price"] - avg_price) / avg_price * 100 if avg_price > 0 else 0
                if gap_avg <= 5:
                    p = prod_map.get(sku, {})
                    well_positioned.append({"sku": sku, "name_ar": p.get("name_ar", ""), "price": s["price"], "market_avg": round(avg_price, 2), "store_name": s["store_name"]})
                # `<=` not `==`: min_price is now the COMPETITOR low, so our own
                # store undercutting the market sits strictly below it and would
                # otherwise drop out of this list entirely.
                if s["price"] <= min_price and s["price"] < avg_price * 0.95:
                    p = prod_map.get(sku, {})
                    undercut.append({"sku": sku, "name_ar": p.get("name_ar", ""), "price": s["price"], "market_avg": round(avg_price, 2), "store_name": s["store_name"]})
                continue
            uplift = round((s["price"] - min_price) * len(store_snaps), 2)
            p = prod_map.get(sku, {})
            badge = "overpriced_risk" if gap_pct >= 25 else "quick_win" if uplift >= 500 and s.get("qty_available", 0) > 0 else "overpriced"
            if badge == "overpriced_risk":
                zero_sales_overpriced += 1
            total_overpriced += 1
            total_uplift += uplift
            opportunities.append({
                "sku": sku, "name_ar": p.get("name_ar", sku), "name_en": p.get("name_en", ""), "category": p.get("category", ""),
                "image_url": p.get("image_url", ""), "store_name": s["store_name"], "store_id": s["store_id"],
                "my_price": s["price"], "market_lowest": min_price, "market_avg": round(avg_price, 2),
                "gap_pct": gap_pct, "units_sold": 0, "market_sold": 0,
                "revenue_uplift": uplift, "badge": badge, "num_sellers": len(store_snaps),
                "in_stock": s.get("in_stock", False), "qty": s.get("qty_available", 0),
            })

    opportunities.sort(key=lambda x: x["revenue_uplift"], reverse=True)
    return {
        "opportunities": opportunities[:200],
        "well_positioned": well_positioned[:50],
        "undercut": undercut[:50],
        "summary": {
            "total_overpriced": total_overpriced,
            "total_uplift": round(total_uplift, 2),
            "zero_sales_overpriced": zero_sales_overpriced,
            "overpriced_count": total_overpriced,
            "total_uplift_sar": round(total_uplift, 2),
            # iter51 — SKUs withheld because our pack count disagrees with the
            # catalogue's. Reported rather than silently dropped.
            "pack_mismatch_skipped": len(pack_mismatch_skipped),
            "pack_mismatch_sample": pack_mismatch_skipped[:20],
            # iter52 — prices excluded from the market low on VARIANT evidence,
            # and wild lows KEPT because no such evidence exists.
            "suspected_pack_mismatch": len(variant_flags),
            "suspected_pack_mismatch_sample": variant_flags[:20],
            "low_outliers_kept": len(outlier_kept),
            "low_outliers_kept_sample": outlier_kept[:20],
        },
    }

# ── Alerts ───────────────────────────────────────────────────
ALERT_TYPES = ["price_drop", "price_increase", "out_of_stock", "back_in_stock", "low_stock"]

def send_alert_notification(alert, event, channel="console"):
    """Send alert notification. Currently logs to console. Swap for Resend with one-line change."""
    msg = f"[ALERT] {event.get('alert_type','')}: SKU={event.get('sku','')} at {event.get('store_name','')}: {event.get('old_value','')} -> {event.get('new_value','')} (threshold: {alert.get('threshold','')})"
    logger.info(msg)  # Replace with: await resend.emails.send(...) for real email

@router.get("/alerts")
async def list_alerts(user=Depends(get_user)):
    alerts = await db.alerts.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
    # Enrich with product info
    for a in alerts:
        if a.get("product_sku"):
            p = await db.products.find_one({"sku": a["product_sku"]}, {"_id": 0, "name_ar": 1, "name_en": 1})
            if p:
                a["product_name_ar"] = p["name_ar"]
                a["product_name_en"] = p["name_en"]
    return alerts

@router.post("/alerts")
async def create_alert(data: AlertIn, user=Depends(get_user)):
    if data.alert_type not in ALERT_TYPES:
        raise HTTPException(400, f"Invalid alert type. Valid: {ALERT_TYPES}")
    doc = {
        "id": str(uuid.uuid4()), "user_id": user["id"],
        "product_sku": data.product_sku, "category": data.category,
        "store_id": data.store_id, "alert_type": data.alert_type,
        "threshold": data.threshold, "channel": data.channel or "in_app",
        "is_active": True, "created_at": datetime.now(timezone.utc).isoformat(),
        "triggered_count": 0, "last_triggered_at": None,
    }
    await db.alerts.insert_one(doc)
    doc.pop("_id", None)
    return doc

@router.put("/alerts/{alert_id}/toggle")
async def toggle_alert(alert_id: str, user=Depends(get_user)):
    alert = await db.alerts.find_one({"id": alert_id, "user_id": user["id"]})
    if not alert:
        raise HTTPException(404, "Alert not found")
    new_state = not alert.get("is_active", True)
    await db.alerts.update_one({"id": alert_id}, {"$set": {"is_active": new_state}})
    return {"id": alert_id, "is_active": new_state}

@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, user=Depends(get_user)):
    r = await db.alerts.delete_one({"id": alert_id, "user_id": user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Alert not found")
    return {"message": "Deleted"}

@router.get("/alerts/feed")
async def alert_feed(days: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = await db.alert_events.find(
        {"user_id": user["id"], "triggered_at": {"$gte": since.isoformat()}},
        {"_id": 0}
    ).sort("triggered_at", -1).limit(100).to_list(100)
    return events

@router.post("/alerts/check")
async def check_alerts_now(user=Depends(get_user)):
    """Manually trigger alert checking against latest snapshots."""
    alerts = await db.alerts.find({"user_id": user["id"], "is_active": True}, {"_id": 0}).to_list(100)
    events_created = 0
    now = datetime.now(timezone.utc)

    for alert in alerts:
        sku = alert.get("product_sku")
        if not sku:
            continue
        # Get latest two snapshots for this SKU
        snaps = await db.product_snapshots.find({"sku": sku}, {"_id": 0}).sort("crawled_at", -1).limit(2).to_list(2)
        if len(snaps) < 2:
            continue
        latest, prev = snaps[0], snaps[1]
        event = None
        at = alert.get("alert_type")
        threshold = alert.get("threshold") or 0

        if at == "price_drop" and latest["price"] < prev["price"]:
            drop_pct = round((1 - latest["price"] / prev["price"]) * 100, 1) if prev["price"] > 0 else 0
            if drop_pct >= threshold:
                event = {"old_value": f"{prev['price']} SAR", "new_value": f"{latest['price']} SAR ({-drop_pct}%)"}
        elif at == "price_increase" and latest["price"] > prev["price"]:
            inc_pct = round((latest["price"] / prev["price"] - 1) * 100, 1) if prev["price"] > 0 else 0
            if inc_pct >= threshold:
                event = {"old_value": f"{prev['price']} SAR", "new_value": f"{latest['price']} SAR (+{inc_pct}%)"}
        elif at == "out_of_stock" and not latest["in_stock"] and prev["in_stock"]:
            event = {"old_value": "In Stock", "new_value": "Out of Stock"}
        elif at == "back_in_stock" and latest["in_stock"] and not prev["in_stock"]:
            event = {"old_value": "Out of Stock", "new_value": "Back in Stock"}
        elif at == "low_stock" and latest.get("qty_available", 0) <= (threshold or 10) and prev.get("qty_available", 0) > (threshold or 10):
            event = {"old_value": f"{prev.get('qty_available', 0)} units", "new_value": f"{latest.get('qty_available', 0)} units"}

        if event:
            ev_doc = {
                "id": str(uuid.uuid4()), "alert_id": alert["id"], "user_id": user["id"],
                "product_sku": sku, "store_name": latest.get("store_name", ""),
                "alert_type": at, "sku": sku,
                "old_value": event["old_value"], "new_value": event["new_value"],
                "triggered_at": now.isoformat(),
            }
            await db.alert_events.insert_one(ev_doc)
            await db.alerts.update_one({"id": alert["id"]}, {"$set": {"last_triggered_at": now.isoformat()}, "$inc": {"triggered_count": 1}})
            send_alert_notification(alert, ev_doc, alert.get("channel", "console"))
            events_created += 1

    return {"message": f"Checked {len(alerts)} alerts, created {events_created} events"}


@router.post("/alerts/auto-generate")
async def auto_generate_alerts(user=Depends(get_user)):
    """Auto-generate alerts from Price Intel data."""
    now = datetime.now(timezone.utc)
    created = {"price_drop": 0, "out_of_stock": 0, "catalog_gap": 0}

    # Delete previously auto-generated alerts to avoid duplicates
    await db.alerts.delete_many({"user_id": user["id"], "auto_generated": True})

    # 1) Price drop alerts for RED overpriced products (>15%)
    matches = await db.product_matches.find({"confidence": {"$gte": 75}}, {"_id": 0}).to_list(50000)
    my_products = {p["sku"]: p async for p in db.my_products.find({}, {"_id": 0})}
    by_sku = {}
    for m in matches:
        by_sku.setdefault(m["my_sku"], []).append(m)

    for my_sku, ms in by_sku.items():
        mp = my_products.get(my_sku)
        if not mp:
            continue
        my_price = float(mp.get("sale_price") or mp.get("price") or 0)
        if my_price <= 0:
            continue
        cheapest = min(ms, key=lambda x: x["competitor_price"])
        diff_pct = round(((my_price - cheapest["competitor_price"]) / cheapest["competitor_price"]) * 100, 1) if cheapest["competitor_price"] > 0 else 0
        if diff_pct > 15:
            await db.alerts.insert_one({
                "id": str(uuid.uuid4()), "user_id": user["id"],
                "product_sku": my_sku, "category": "",
                "store_id": cheapest["competitor_store_id"],
                "alert_type": "price_drop", "threshold": 5,
                "channel": "in_app", "is_active": True,
                "auto_generated": True,
                "description": f"Competitor {cheapest['competitor_store_name']} is {diff_pct}% cheaper. Alert if they drop further.",
                "created_at": now.isoformat(), "triggered_count": 0, "last_triggered_at": None,
            })
            created["price_drop"] += 1

    # 2) OOS alerts for products I carry
    for my_sku, ms in by_sku.items():
        mp = my_products.get(my_sku)
        if not mp or (mp.get("quantity", 0) <= 0):
            continue
        for m in ms:
            if m["competitor_in_stock"]:
                await db.alerts.insert_one({
                    "id": str(uuid.uuid4()), "user_id": user["id"],
                    "product_sku": my_sku, "category": "",
                    "store_id": m["competitor_store_id"],
                    "alert_type": "out_of_stock", "threshold": 0,
                    "channel": "in_app", "is_active": True,
                    "auto_generated": True,
                    "description": f"Alert if {m['competitor_store_name']} goes OOS — sales opportunity for you.",
                    "created_at": now.isoformat(), "triggered_count": 0, "last_triggered_at": None,
                })
                created["out_of_stock"] += 1
                break  # One OOS alert per my_sku is enough

    # 3) Catalog gap alerts (revenue >10K SAR)
    gaps = await db.market_opportunities.find({"est_revenue_sar": {"$gte": 10000}}, {"_id": 0}).to_list(20)
    for g in gaps:
        await db.alerts.insert_one({
            "id": str(uuid.uuid4()), "user_id": user["id"],
            "product_sku": g.get("barcode", ""), "category": "catalog_gap",
            "store_id": "", "alert_type": "back_in_stock",
            "threshold": 0, "channel": "in_app", "is_active": True,
            "auto_generated": True,
            "description": f"Catalog Gap: {g['product_name'][:50]} — est. {g['est_revenue_sar']:,.0f} SAR/14d revenue. Source this product!",
            "created_at": now.isoformat(), "triggered_count": 0, "last_triggered_at": None,
        })
        created["catalog_gap"] += 1

    total = sum(created.values())
    return {"message": f"Auto-generated {total} alerts", "created": created}


@router.get("/notifications")
async def list_notifications(user=Depends(get_user)):
    """Get notification bell data — unread alerts + recent events."""
    alerts = await db.alerts.find({"user_id": user["id"], "is_active": True}, {"_id": 0}).to_list(500)
    events = await db.alert_events.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("triggered_at", -1).limit(20).to_list(20)

    # Count unread (events from last 24h)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    unread = sum(1 for e in events if e.get("triggered_at", "") > cutoff)

    # Build notification items from auto-generated alerts (for immediate display)
    auto_alerts = [a for a in alerts if a.get("auto_generated")]
    notifications = []
    for a in auto_alerts[:30]:
        mp = await db.my_products.find_one({"sku": a.get("product_sku", "")}, {"_id": 0, "name_ar": 1, "name_en": 1})
        notifications.append({
            "id": a["id"],
            "type": a["alert_type"],
            "description": a.get("description", ""),
            "product_name": (mp or {}).get("name_en", "") or (mp or {}).get("name_ar", a.get("product_sku", "")),
            "created_at": a.get("created_at", ""),
            "is_active": a.get("is_active", True),
        })

    return {
        "total_alerts": len(alerts),
        "auto_generated": len(auto_alerts),
        "unread_events": unread,
        "recent_events": events[:10],
        "notifications": notifications,
    }


# ── Competitor Profile Routes ────────────────────────────────
@router.get("/stores/{store_id}/profile")
async def store_profile(store_id: str, user=Depends(get_user)):
    store = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not store:
        raise HTTPException(404, "Store not found")

    now = datetime.now(timezone.utc)
    since_90d = now - timedelta(days=90)
    since_7d = now - timedelta(days=7)

    # Catalog stats
    skus = await db.product_snapshots.distinct("sku", {"store_id": store_id})
    active_skus = await db.product_snapshots.distinct("sku", {"store_id": store_id, "in_stock": True, "crawled_at": {"$gte": since_7d}})

    # Latest snapshots per sku for this store
    pipeline_latest = [
        {"$match": {"store_id": store_id}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": "$sku", "price": {"$first": "$price"}, "discount_pct": {"$first": "$discount_pct"}, "qty": {"$first": "$qty_available"}, "in_stock": {"$first": "$in_stock"}, "crawled_at": {"$first": "$crawled_at"}, "product_id": {"$first": "$product_id"}}},
    ]
    latest = await db.product_snapshots.aggregate(pipeline_latest).to_list(500)

    avg_disc = round(statistics.mean([l["discount_pct"] for l in latest if l["discount_pct"] > 0]) if any(l["discount_pct"] > 0 for l in latest) else 0, 1)

    # Revenue estimation over 90 days — use defensive sales algorithm
    snaps_90d = await db.product_snapshots.find({"store_id": store_id, "crawled_at": {"$gte": since_90d}}, {"_id": 0}).sort("crawled_at", 1).to_list(50000)
    by_sku = {}
    for s in snaps_90d:
        by_sku.setdefault(s["sku"], []).append(s)

    total_rev = 0.0
    total_sold = 0
    weekly_rev = {}
    daily_rev = {}
    sku_sales = {}

    for sku, slist in by_sku.items():
        if len(slist) < 2:
            continue
        # Estimate aggregate sales (units + revenue) for this SKU over the window using the defensible method
        units_total, rev_total, _ = _estimate_sales_from_snapshots(slist, days=90)
        if units_total <= 0:
            continue
        total_sold += units_total
        total_rev += rev_total
        sku_sales[sku] = sku_sales.get(sku, 0) + units_total

        # For trend distribution, attribute deltas to their snapshot date — same algorithm, per-pair, with same caps
        sold_counts = [s.get("sold_count", 0) or 0 for s in slist]
        use_sold_counter = max(sold_counts) > 0
        for i in range(1, len(slist)):
            ca = slist[i]["crawled_at"]
            week_key = ca.strftime("%Y-W%W") if isinstance(ca, datetime) else ca[:10]
            day_key = ca.strftime("%Y-%m-%d") if isinstance(ca, datetime) else ca[:10]
            price = slist[i].get("price") or 0
            inc = 0
            if use_sold_counter:
                inc = max(0, (sold_counts[i] - sold_counts[i - 1]))
                inc = min(inc, MAX_DAILY_SALES_PER_SKU)
            else:
                prev_q = slist[i - 1].get("qty_available", 0) or 0
                curr_q = slist[i].get("qty_available", 0) or 0
                if prev_q in PLACEHOLDER_QTY_VALUES or curr_q in PLACEHOLDER_QTY_VALUES or prev_q > 500:
                    continue
                d = prev_q - curr_q
                if d <= 0:
                    continue
                inc = min(d, MAX_QTY_DELTA_PER_INTERVAL)
            if inc <= 0:
                continue
            rev = inc * price
            weekly_rev[week_key] = weekly_rev.get(week_key, 0) + rev
            daily_rev[day_key] = daily_rev.get(day_key, 0) + rev

    # Compute the actual time span of data for accurate monthly normalization
    if snaps_90d:
        first_ca = snaps_90d[0]["crawled_at"]
        last_ca = snaps_90d[-1]["crawled_at"]
        if isinstance(first_ca, str):
            first_ca = datetime.fromisoformat(first_ca.replace("Z", "+00:00"))
        if isinstance(last_ca, str):
            last_ca = datetime.fromisoformat(last_ca.replace("Z", "+00:00"))
        span_days = max(1, (last_ca - first_ca).days)
    else:
        span_days = 1

    # Revenue trend (weekly)
    revenue_trend = [{"week": k, "revenue": round(v, 2)} for k, v in sorted(weekly_rev.items())]
    daily_trend = [{"date": k, "revenue": round(v, 2)} for k, v in sorted(daily_rev.items())]

    # Top 10 products by sales
    top_10 = sorted(sku_sales.items(), key=lambda x: x[1], reverse=True)[:10]
    top_products = []
    for sku, sales in top_10:
        p = await db.products.find_one({"sku": sku}, {"_id": 0, "name_ar": 1, "name_en": 1, "category": 1, "brand": 1})
        if p:
            top_products.append({**p, "sku": sku, "units_sold": sales})

    # Category distribution
    cat_count = {}
    for l in latest:
        p = await db.products.find_one({"sku": l["_id"]}, {"_id": 0, "category": 1})
        if p:
            cat_count[p["category"]] = cat_count.get(p["category"], 0) + 1
    category_dist = [{"category": k, "count": v} for k, v in sorted(cat_count.items(), key=lambda x: x[1], reverse=True)]

    # New arrivals last 7 days
    new_products = await db.products.find(
        {"first_seen_at": {"$gte": since_7d.isoformat()}, "sku": {"$in": skus}},
        {"_id": 0, "sku": 1, "name_ar": 1, "name_en": 1, "category": 1}
    ).to_list(20)

    # Recently OOS
    oos_latest = [l for l in latest if not l["in_stock"]]
    recently_oos = []
    for l in oos_latest[:10]:
        p = await db.products.find_one({"sku": l["_id"]}, {"_id": 0, "name_ar": 1, "name_en": 1})
        if p:
            recently_oos.append({**p, "sku": l["_id"], "last_qty": l["qty"]})

    # Estimated monthly revenue: scale total_rev (over span_days) to a 30-day month
    # Avoid the old `/3` hack — that assumed exactly 90 days of perfect data
    est_monthly_revenue = round(total_rev * 30 / max(span_days, 1), 2) if total_rev > 0 else 0
    est_daily_revenue = round(total_rev / max(span_days, 1), 2) if total_rev > 0 else 0
    est_daily_units = round(total_sold / max(span_days, 1), 1) if total_sold > 0 else 0

    return {
        "store": store,
        "kpis": {
            "catalog_size": len(skus), "active_skus": len(active_skus),
            "est_monthly_revenue": est_monthly_revenue,
            "est_daily_revenue": est_daily_revenue,
            "est_daily_sales": est_daily_units,
            "data_span_days": span_days,
            "avg_discount_rate": avg_disc, "last_crawled": store.get("last_crawled_at"),
        },
        "revenue_trend_weekly": revenue_trend,
        "revenue_trend_daily": daily_trend,
        "top_products": top_products,
        "category_distribution": category_dist,
        "new_arrivals": new_products,
        "recently_oos": recently_oos,
    }

# ── Export ──────────────────────────────────────────────────
@router.get("/export/products")
async def export_csv(days: int = Query(30), user=Depends(get_user)):
    # Explicit None for the date params — when my_products() is called as a plain
    # function (not via HTTP) the unset Query(None) defaults are FieldInfo objects
    # (truthy), which would wrongly trigger the on_date branch. (Pre-existing;
    # surfaced during the iter25 refactor.)
    data = await my_products(days=days, on_date=None, date_from=None, date_to=None, category=None, animal_type=None, search=None, sort_by="revenue_est", sort_order="desc", limit=10_000_000, offset=0, own_only=True, user=user)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["SKU", "Name (AR)", "Name (EN)", "Category", "Price (SAR)", "Min Price", "Max Price", "Est. Sales", "Est. Revenue", "Sellers", "Stock Signal", "Confidence"])
    for p in data["products"]:
        writer.writerow([p["sku"], p["name_ar"], p["name_en"], p["category"], p.get("price", ""), p.get("min_price", ""), p.get("max_price", ""), p.get("qty_sold_est", ""), p.get("revenue_est", ""), p.get("num_sellers", ""), p.get("stock_signal", ""), p.get("confidence_score", "")])
    output.seek(0)
    return StreamingResponse(io.BytesIO(output.getvalue().encode("utf-8-sig")), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=daleel_pets_export.csv"})

# ── Weekly Market Digest ─────────────────────────────────────
async def generate_market_digest():
    """Generate the weekly market intelligence digest."""
    now = datetime.now(timezone.utc)
    week_end = now.date()
    week_start = week_end - timedelta(days=7)
    since = now - timedelta(days=7)
    prev_start = since - timedelta(days=7)

    # Section 1: Top 5 Price Drops
    snaps_week = await db.product_snapshots.find({"crawled_at": {"$gte": since}}, {"_id": 0}).sort("crawled_at", 1).to_list(100000)
    by_sku_store = {}
    for s in snaps_week:
        by_sku_store.setdefault((s["sku"], s["store_id"]), []).append(s)
    price_drops = []
    for (sku, sid), slist in by_sku_store.items():
        if len(slist) < 2:
            continue
        first_p, last_p = slist[0]["price"], slist[-1]["price"]
        if last_p < first_p:
            drop_pct = round((1 - last_p / first_p) * 100, 1) if first_p > 0 else 0
            if drop_pct >= 5:
                p = await db.products.find_one({"sku": sku}, {"_id": 0, "name_ar": 1})
                price_drops.append({"sku": sku, "name_ar": p.get("name_ar", sku) if p else sku, "store_name": slist[-1].get("store_name", ""), "old_price": first_p, "new_price": last_p, "drop_pct": drop_pct})
    price_drops.sort(key=lambda x: x["drop_pct"], reverse=True)

    # Section 2: New Products
    new_prods = await db.products.find({"first_seen_at": {"$gte": since.isoformat()}}, {"_id": 0, "name_ar": 1, "sku": 1, "category": 1, "animal_type": 1}).sort("first_seen_at", -1).limit(10).to_list(10)

    # Section 3: OOS Events
    oos_events = []
    for (sku, sid), slist in by_sku_store.items():
        if len(slist) < 2:
            continue
        for i in range(1, len(slist)):
            if slist[i-1].get("in_stock") and not slist[i].get("in_stock"):
                p = await db.products.find_one({"sku": sku}, {"_id": 0, "name_ar": 1})
                oos_events.append({"sku": sku, "name_ar": p.get("name_ar", sku) if p else sku, "store_name": slist[i].get("store_name", ""), "price": slist[i]["price"]})
                break

    # Section 4: Quick Wins (reuse scanner)
    quick_wins = []
    try:
        from starlette.testclient import TestClient
    except Exception:
        pass

    # Section 5: Market Summary
    total_skus = await db.products.count_documents({})
    total_rev_week = sum(s.get("price", 0) * max(0, by_sku_store.get((s["sku"], s["store_id"]), [{}])[0].get("qty_available", 0) - s.get("qty_available", 0)) for s in snaps_week[-100:] if s.get("qty_available", 0) >= 0)
    prev_snaps = await db.product_snapshots.count_documents({"crawled_at": {"$gte": prev_start, "$lt": since}})

    # Most active store
    store_changes = {}
    for (sku, sid), slist in by_sku_store.items():
        if len(slist) >= 2:
            sname = slist[-1].get("store_name", "")
            store_changes[sname] = store_changes.get(sname, 0) + 1
    most_active = max(store_changes, key=store_changes.get) if store_changes else "N/A"

    digest = {
        "id": str(uuid.uuid4()),
        "generated_at": now.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "delivery_status": "logged",
        "delivered_at": now.isoformat(),
        "content": {
            "top_price_drops": price_drops[:5],
            "new_products": new_prods[:3],
            "oos_events": oos_events[:5],
            "quick_wins": quick_wins[:3],
            "market_summary": {
                "total_skus": total_skus,
                "total_price_drops": len(price_drops),
                "total_new_products": len(new_prods),
                "total_oos_events": len(oos_events),
                "most_active_store": most_active,
                "snapshots_this_week": len(snaps_week),
            },
        },
    }
    await db.market_digests.insert_one(digest)
    digest.pop("_id", None)
    logger.info(f"[DIGEST] Week {week_start} - {week_end}: {len(price_drops)} drops, {len(new_prods)} new, {len(oos_events)} OOS")
    return digest

def deliver_digest(digest):
    """Deliver digest. Currently logs to console. Swap to Resend for real email."""
    logger.info(f"[DIGEST EMAIL] Generated: {digest['generated_at']}, Week: {digest['week_start']} to {digest['week_end']}")
    c = digest["content"]
    logger.info(f"  Price Drops: {len(c['top_price_drops'])}, New: {len(c['new_products'])}, OOS: {len(c['oos_events'])}")

@router.get("/digests")
async def list_digests(user=Depends(get_user)):
    digests = await db.market_digests.find({}, {"_id": 0}).sort("generated_at", -1).limit(12).to_list(12)
    return digests

@router.get("/digests/latest")
async def latest_digest(user=Depends(get_user)):
    digest = await db.market_digests.find_one({}, {"_id": 0}, sort=[("generated_at", -1)])
    return digest or {}

@router.post("/digests/generate")
async def trigger_digest(user=Depends(get_user)):
    digest = await generate_market_digest()
    deliver_digest(digest)
    return digest

# ── My Products Import & Price Intelligence ─────────────────
from matcher import (match_my_product, run_matching_for_all, _is_valid_barcode,
                     _pack_compatible)

# MatchActionIn moved to /app/backend/models/schemas.py (Feb 2026 refactor)

@router.post("/import/products")
async def import_products(file: UploadFile = File(...), user=Depends(get_user)):
    """Import Zid Excel export as My Products."""
    import openpyxl
    content = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception as exc:
        raise HTTPException(400, f"Cannot parse Excel file: {exc}")

    if len(rows) < 2:
        raise HTTPException(400, "File has no data rows")

    headers = [str(h or "").strip().lower() for h in rows[0]]
    col_map = {h: i for i, h in enumerate(headers)}
    required = ["sku", "name_ar", "price"]
    for r in required:
        if r not in col_map:
            raise HTTPException(400, f"Missing required column: {r}")

    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1, "name": 1, "domain": 1})
    store_id = own_store["id"] if own_store else "own"
    now = datetime.now(timezone.utc)
    imported = 0
    skipped = 0

    for row in rows[1:]:
        def g(col):
            idx = col_map.get(col)
            return row[idx] if idx is not None and idx < len(row) else None

        sku = str(g("sku") or "").strip()
        if not sku:
            skipped += 1
            continue

        price = float(g("price") or 0)
        if price <= 0:
            skipped += 1
            continue

        sale_price = float(g("sale_price") or 0) if g("sale_price") else None
        barcode = str(g("barcode") or "").strip() if g("barcode") else ""
        name_ar = str(g("name_ar") or "").strip()
        name_en = str(g("name_en") or "").strip()
        desc_ar = str(g("description_ar") or "").strip() if g("description_ar") else ""
        desc_en = str(g("description_en") or "").strip() if g("description_en") else ""
        qty_raw = g("quantity")
        try:
            qty = int(float(str(qty_raw or 0)))
        except (ValueError, TypeError):
            qty = 0
        cats_ar = str(g("categories_ar") or "")
        cats_en = str(g("categories_en") or "")
        weight_raw = g("weight")
        try:
            weight_val = float(weight_raw) if weight_raw else None
        except (ValueError, TypeError):
            weight_val = None
        weight_unit = str(g("weight_unit") or "").strip()
        cost_raw = g("cost")
        try:
            cost = round(float(cost_raw), 2) if cost_raw else None
        except (ValueError, TypeError):
            cost = None
        images = str(g("images") or "")
        img_url = images.split(",")[0].strip() if images else ""

        page_url = str(g("product_page_url") or "").strip()
        product_url = ""
        if page_url:
            if page_url.startswith("http://") or page_url.startswith("https://"):
                product_url = page_url
            elif own_store and own_store.get("domain"):
                domain = own_store["domain"]
                if page_url.startswith("/"):
                    product_url = f"https://{domain}{page_url}"
                else:
                    product_url = f"https://{domain}/products/{page_url}"

        doc = {
            "sku": sku, "barcode": barcode, "name_ar": name_ar, "name_en": name_en,
            "description_ar": desc_ar, "description_en": desc_en,
            "price": round(price, 2), "sale_price": round(sale_price, 2) if sale_price else None,
            "cost": round(cost, 2) if cost else None,
            "quantity": max(0, qty), "categories_ar": cats_ar, "categories_en": cats_en,
            "weight": weight_val, "weight_unit": weight_unit,
            "image_url": img_url,
            "product_url": product_url,
            "is_own_store": True, "store_id": store_id,
            "imported_at": now.isoformat(),
        }
        await db.my_products.update_one({"sku": sku}, {"$set": doc}, upsert=True)
        imported += 1

    # Create indexes
    await db.my_products.create_index("sku", unique=True)
    await db.my_products.create_index("barcode")
    await db.product_matches.create_index([("my_sku", 1), ("competitor_sku", 1), ("competitor_store_id", 1)])
    await db.match_blacklist.create_index([("my_sku", 1), ("competitor_sku", 1)])

    return {"imported": imported, "skipped": skipped, "total_rows": len(rows) - 1}


@router.post("/import/run-matching")
async def trigger_matching(background: BackgroundTasks, user=Depends(get_user)):
    """Run the matching engine for all imported my_products (background).

    Feb 2026: now goes through the unified sync_runs logging pipeline so the
    /api/data-freshness sync_health endpoint can surface match-only failures
    the same way it surfaces sync failures.
    """
    count = await db.my_products.count_documents({})
    if count == 0:
        raise HTTPException(400, "No products imported yet")
    background.add_task(_run_sync_and_match, "manual_match_only")
    return {"message": f"Matching started for {count} products", "status": "running"}

async def _background_matching():
    try:
        stats = await run_matching_for_all(db)
        await db.matching_jobs.update_one(
            {"job": "latest"},
            {"$set": {"status": "complete", "stats": stats, "completed_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        logger.info(f"[Matching] Complete: {stats}")
    except Exception as exc:
        logger.error(f"[Matching] Error: {exc}")
        await db.matching_jobs.update_one(
            {"job": "latest"},
            {"$set": {"status": "error", "error": str(exc), "completed_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )


@router.get("/import/status")
async def import_status(user=Depends(get_user)):
    my_count = await db.my_products.count_documents({})
    match_count = await db.product_matches.count_documents({})
    confirmed_count = await db.product_matches.count_documents({"manually_confirmed": True})
    blacklist_count = await db.match_blacklist.count_documents({})
    job = await db.matching_jobs.find_one({"job": "latest"}, {"_id": 0})
    own = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "name": 1, "domain": 1, "last_own_store_sync": 1, "own_store_sync_updated": 1, "own_store_sync_not_found": 1, "own_store_sync_crawled": 1, "own_store_sync_source": 1, "own_store_sync_warning": 1, "last_orders_sync": 1, "orders_sync_status": 1})
    # Live stats straight from the ledger collection (authoritative regardless
    # of whether the scheduled or the manual path ingested them).
    orders_total = await db.own_store_orders.count_documents({})
    orders_excluded = await db.own_store_orders.count_documents({"excluded": True})
    oldest_order = await db.own_store_orders.find_one({}, {"_id": 0, "created_at": 1}, sort=[("created_at", 1)])
    newest_order = await db.own_store_orders.find_one({}, {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
    orders_info = {
        "total": orders_total,
        "excluded": orders_excluded,
        "oldest": (oldest_order or {}).get("created_at").isoformat() if (oldest_order or {}).get("created_at") else None,
        "newest": (newest_order or {}).get("created_at").isoformat() if (newest_order or {}).get("created_at") else None,
        "last_sync": (own or {}).get("last_orders_sync"),
        "last_sync_status": (own or {}).get("orders_sync_status"),
    }
    return {
        "my_products": my_count,
        "orders": orders_info,
        "total_matches": match_count,
        "confirmed_matches": confirmed_count,
        "blacklisted": blacklist_count,
        "matching_job": job,
        "own_store": (
            {
                "name": own.get("name"),
                "domain": own.get("domain"),
                "last_own_store_sync": own.get("last_own_store_sync"),
                "own_store_sync_updated": own.get("own_store_sync_updated", 0),
                "own_store_sync_not_found": own.get("own_store_sync_not_found", 0),
                "own_store_sync_crawled": own.get("own_store_sync_crawled", 0),
                # zid_api | public_crawl — public_crawl with creds configured means
                # sold counters aren't captured and own-sales KPIs are stalling.
                "own_store_sync_source": own.get("own_store_sync_source"),
                "own_store_sync_warning": own.get("own_store_sync_warning") or None,
            }
            if own else None
        ),
    }


@router.post("/import/sync-own-store")
async def trigger_own_store_sync(background: BackgroundTasks, user=Depends(get_user)):
    """Manually trigger a price sync from the user's own Zid store into my_products."""
    own = await db.stores.find_one({"is_own_store": True}, {"_id": 0})
    if not own:
        raise HTTPException(400, "No store flagged is_own_store=True. Set the flag on your store first.")

    background.add_task(_run_sync_and_match, "manual")
    return {"message": "Sync started", "status": "running", "store": own.get("name"), "domain": own.get("domain")}


@router.post("/import/sync-orders")
async def trigger_orders_sync(background: BackgroundTasks, full: bool = Query(False, description="Full backfill: walk ALL order pages the Zid API will serve, not just the recent refresh window"), user=Depends(get_user)):
    """Pull real orders from the Zid Merchant Orders API into own_store_orders.

    Run once with ?full=true after deploying this feature so historical
    windows (7D/14D/30D/90D) show real revenue; afterwards the 6-hourly
    scheduled sync keeps it fresh incrementally.
    """
    own = await db.stores.find_one({"is_own_store": True}, {"_id": 0})
    if not own:
        raise HTTPException(400, "No store flagged is_own_store=True. Set the flag on your store first.")

    async def _run_orders(full_backfill: bool):
        try:
            res = await sync_own_store_orders(db, full_backfill=full_backfill)
            await db.stores.update_one(
                {"is_own_store": True},
                {"$set": {
                    "last_orders_sync": datetime.now(timezone.utc).isoformat(),
                    "orders_sync_status": res.get("status"),
                    "orders_sync_upserted": int(res.get("upserted") or 0),
                    "orders_sync_oldest": res.get("oldest_seen"),
                }},
            )
        except Exception:
            logger.exception("[Orders] manual sync failed")
            await db.stores.update_one(
                {"is_own_store": True},
                {"$set": {"orders_sync_status": "error",
                          "last_orders_sync": datetime.now(timezone.utc).isoformat()}},
            )

    background.add_task(_run_orders, full)
    return {"message": f"Orders sync started (full_backfill={full})", "status": "running",
            "store": own.get("name"), "domain": own.get("domain")}


async def _run_sync_and_match(kind: str):
    """Run own-store sync and matcher with decoupled error handling + persistent logging.

    Feb 2026 hardening (P1, addresses silent-failure drift):
      • Each invocation writes ONE row to db.sync_runs with the full timeline.
      • Sync and matcher have INDEPENDENT try/except blocks — a sync failure
        no longer skips the matcher (it can still run against existing data),
        and a matcher failure doesn't erase the record of a successful sync.
      • Stored fields drive the `/api/data-freshness` sync_health banner so
        silent failures become visible without grepping supervisor logs.

    `kind` is "scheduled" (6h cron), "manual" (user pressed Sync from Store),
    or "manual_match_only" (user pressed Run Matching without resyncing).
    """
    started = datetime.now(timezone.utc)
    run = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "started_at": started,
        "finished_at": None,
        "sync_status": "skipped",
        "sync_updated": 0,
        "sync_discovered": 0,
        "sync_archived": 0,
        "sync_error": None,
        "match_status": "skipped",
        "match_added": 0,
        "match_error": None,
        "orders_status": "skipped",
        "orders_upserted": 0,
        "orders_error": None,
        "duration_secs": 0.0,
    }

    # ── SYNC step — independent try/except so a failure here doesn't skip the matcher ──
    if kind != "manual_match_only":
        try:
            res = await sync_own_store_prices(db)
            run["sync_status"] = "ok"
            run["sync_updated"] = int(res.get("updated") or 0)
            run["sync_discovered"] = int(res.get("discovered") or 0)
            run["sync_archived"] = int(res.get("archived") or 0)
            run["sync_source"] = res.get("source")
            run["sync_warning"] = res.get("warning")
            if run["sync_warning"]:
                # Degraded, not ok: the sync "worked" but via public crawl while
                # Zid creds are configured — own sales KPIs are stalling.
                run["sync_status"] = "degraded"
            logger.info(f"[SyncMatch/{kind}] sync OK: updated={run['sync_updated']} discovered={run['sync_discovered']} archived={run['sync_archived']} source={run['sync_source']}")
        except Exception as e:
            run["sync_status"] = "error"
            run["sync_error"] = str(e)[:500]
            logger.exception(f"[SyncMatch/{kind}] sync FAILED")

    # ── ORDERS step (Feb 2026) — real Zid orders ledger for My Revenue.
    # Independent try/except: an orders failure must not block the matcher,
    # and vice versa. Incremental mode re-pulls the last 14 days so late
    # cancellations/refunds correct history on every run.
    if kind != "manual_match_only":
        try:
            ores = await sync_own_store_orders(db)
            run["orders_status"] = ores.get("status", "unknown")
            run["orders_upserted"] = int(ores.get("upserted") or 0)
            logger.info(f"[SyncMatch/{kind}] orders {run['orders_status']}: upserted={run['orders_upserted']}")
        except Exception as e:
            run["orders_status"] = "error"
            run["orders_error"] = str(e)[:500]
            logger.exception(f"[SyncMatch/{kind}] orders sync FAILED")

    # ── MATCH step — runs even if sync failed; matcher can re-link existing data ──
    try:
        stats = await run_matching_for_all(db)
        run["match_status"] = "ok"
        run["match_added"] = int(stats.get("matched") or stats.get("added") or 0)
        logger.info(f"[SyncMatch/{kind}] match OK: added={run['match_added']}")
    except Exception as e:
        run["match_status"] = "error"
        run["match_error"] = str(e)[:500]
        logger.exception(f"[SyncMatch/{kind}] match FAILED")

    finished = datetime.now(timezone.utc)
    run["finished_at"] = finished
    run["duration_secs"] = round((finished - started).total_seconds(), 2)

    try:
        await db.sync_runs.insert_one(run)
    except Exception as e:
        logger.error(f"[SyncMatch/{kind}] failed to persist sync_runs row: {e}")

    # iter25 — own-store sync / matcher run is a definitive data change (incl. the
    # manual "Sync from Store" and "Run Matching" buttons, which route through
    # here). Force a dashboard-cache recompute so My Products reflects it at once.
    run["dashboard_cache"] = "recomputed" if await maybe_recompute_dashboard_cache(db, force=True) else "skipped"
    # iter26 — Insights / Price-Intel caches also reflect the sync/matcher change.
    run["page_caches"] = "recomputed" if await maybe_recompute_page_caches(db, force=True) else "skipped"

    return run


# ─────────────────────────────────────────────────────────────────────────────
# iter38 — live store ranking ("Market Strength Score"), replacing the static
# April MySkuWatch leaderboard on Price Intel. Fixed 30d window. Score is
# computed from signals available for EVERY store regardless of platform:
#   0.25·breadth + 0.35·price + 0.25·stock + 0.15·freshness   (client-approved)
# Revenue is a separate column — SAR where measurable (Zid ledger signals),
# an explicit "not measurable (Salla)" status where not. Reads only the small
# collections (coverage, matches, my_products, sales rollups, stores); cached
# via _SINGLE_CACHE_SPECS, so it recomputes on the existing post-crawl hooks.
# ─────────────────────────────────────────────────────────────────────────────
_RANKING_WEIGHTS = {"breadth": 0.25, "price": 0.35, "stock": 0.25, "freshness": 0.15}
_RANKING_WINDOW_DAYS = 30
_RANKING_FRESH_HOURS = 48
_RANKING_STALE_BELOW = 0.3     # freshness under this ⇒ "stale data" badge


async def _store_ranking_compute(db):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=_RANKING_WINDOW_DAYS)
    fresh_floor = now - timedelta(hours=_RANKING_FRESH_HOURS)

    stores_meta = {s["id"]: s async for s in db.stores.find(
        {}, {"_id": 0, "id": 1, "name": 1, "platform": 1, "is_own_store": 1, "domain": 1})}
    own_store_id = next((sid for sid, s in stores_meta.items() if s.get("is_own_store")), None)

    # ── one pass over in-window coverage: breadth / stock / freshness / prices ──
    per_store = {}            # sid -> {products, in_stock, fresh, sold_sig, qty_sig}
    prices_by_sku = {}        # sku -> [(price, sid)] for the percentile pass
    cursor = db.sku_store_coverage.find(
        {"last_priced_at": {"$gte": since}},
        {"_id": 0, "sku": 1, "store_id": 1, "last_priced_price": 1, "last_in_stock": 1,
         "last_seen_any_at": 1, "last_sold_pos_at": 1, "last_usable_qty_at": 1},
    ).batch_size(2000)
    def _aware(dt):
        # PyMongo returns tz-naive UTC datetimes by default — normalize before
        # comparing with our aware timestamps (server-side $gte is unaffected).
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    async for c in cursor:
        sid = c["store_id"]
        st = per_store.setdefault(sid, {"products": 0, "in_stock": 0, "fresh": 0,
                                        "sold_sig": False, "qty_sig": False})
        st["products"] += 1
        if c.get("last_in_stock"):
            st["in_stock"] += 1
        lsa = _aware(c.get("last_seen_any_at"))
        if lsa is not None and lsa >= fresh_floor:
            st["fresh"] += 1
        sold_at = _aware(c.get("last_sold_pos_at"))
        if sold_at is not None and sold_at >= since:
            st["sold_sig"] = True
        qty_at = _aware(c.get("last_usable_qty_at"))
        if qty_at is not None and qty_at >= since:
            st["qty_sig"] = True
        prices_by_sku.setdefault(c["sku"], []).append((c["last_priced_price"], sid))

    # price percentile per competitor store — head-to-head on SHARED skus only:
    # percentile = share of co-sellers strictly cheaper (ties share position)
    pct_sum = {}
    pct_n = {}
    cheapest_hits = {}
    shared_counts = {}
    for sku, sellers in prices_by_sku.items():
        if len(sellers) < 2:
            continue
        prices = sorted(p for p, _sid in sellers)
        n = len(sellers)
        min_p = prices[0]
        for p, sid in sellers:
            below = sum(1 for q in prices if q < p)
            pct_sum[sid] = pct_sum.get(sid, 0.0) + below / (n - 1)
            pct_n[sid] = pct_n.get(sid, 0) + 1
            shared_counts[sid] = shared_counts.get(sid, 0) + 1
            if p == min_p:
                cheapest_hits[sid] = cheapest_hits.get(sid, 0) + 1

    # ── own store components come from own sources (own prices are not crawled
    # into snapshots/coverage): my_products + the SAME market-position percentile
    # the Insights card shows + the real Zid orders ledger ──
    my_prods = await db.my_products.find(
        {}, {"_id": 0, "price": 1, "sale_price": 1, "in_stock": 1, "quantity": 1, "last_synced_at": 1}).to_list(length=None)
    own_products = sum(1 for p in my_prods if (p.get("sale_price") or p.get("price") or 0) > 0)
    own_in_stock = sum(1 for p in my_prods if p.get("in_stock") or (p.get("quantity") or 0) > 0)

    def _synced_recent(p):
        ts = p.get("last_synced_at")
        if not ts:
            return False
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts >= fresh_floor
    own_fresh = sum(1 for p in my_prods if _synced_recent(p))

    mp_summary = await _compute_market_position_summary(db)
    own_pct = (mp_summary or {}).get("avg_percentile")

    # own revenue — iter40: the SAME shared ledger helper the My Products KPI
    # uses (single source; the two surfaces can no longer disagree).
    own_agg = await _own_orders_aggregate(db, since)
    own_revenue = round(own_agg["revenue"], 2) if own_agg else None

    # competitor revenue from the sales rollups (leaderboard's source)
    sales_pairs = await _sales_pairs_from_rollups(db, since)
    revenue_by_store = {}
    for p in sales_pairs:
        revenue_by_store[p["store_id"]] = revenue_by_store.get(p["store_id"], 0.0) + p["revenue"]

    # overlap with the user's catalog (distinct matched my_skus per store)
    overlap = {}
    async for m in db.product_matches.find({}, {"_id": 0, "my_sku": 1, "competitor_store_id": 1}):
        overlap.setdefault(m["competitor_store_id"], set()).add(m["my_sku"])

    # ── assemble rows ──
    if own_store_id:
        per_store.setdefault(own_store_id, {"products": 0, "in_stock": 0, "fresh": 0,
                                            "sold_sig": True, "qty_sig": True})
        per_store[own_store_id].update({"products": own_products, "in_stock": own_in_stock,
                                        "fresh": own_fresh})
    max_products = max((st["products"] for st in per_store.values()), default=0)
    rows = []
    for sid, st in per_store.items():
        meta = stores_meta.get(sid, {})
        n = st["products"]
        if n <= 0:
            continue
        is_own = sid == own_store_id
        breadth = math.log1p(n) / math.log1p(max_products) if max_products else 0.0
        if is_own:
            price_score = round(1 - own_pct / 100, 4) if own_pct is not None else 0.5
            avg_pctile = own_pct if own_pct is not None else None
            cheapest_rate = None
            shared = (mp_summary or {}).get("ranked_products") or 0
            if shared and mp_summary:
                cheapest_rate = round(mp_summary["cheapest_count"] / shared, 4)
        else:
            if pct_n.get(sid):
                avg_frac = pct_sum[sid] / pct_n[sid]
                price_score = round(1 - avg_frac, 4)
                avg_pctile = round(avg_frac * 100, 1)
            else:
                price_score, avg_pctile = 0.5, None    # no shared skus → neutral
            shared = shared_counts.get(sid, 0)
            cheapest_rate = round(cheapest_hits.get(sid, 0) / shared, 4) if shared else None
        stock_score = round(st["in_stock"] / n, 4)
        fresh_score = round(st["fresh"] / n, 4)
        score = round(100 * (_RANKING_WEIGHTS["breadth"] * breadth
                             + _RANKING_WEIGHTS["price"] * price_score
                             + _RANKING_WEIGHTS["stock"] * stock_score
                             + _RANKING_WEIGHTS["freshness"] * fresh_score), 1)
        # revenue column — value where measurable, explicit status where not
        if is_own:
            revenue, rev_status = own_revenue, ("ledger" if own_revenue is not None else "accumulating")
        else:
            rev = round(revenue_by_store.get(sid, 0.0), 2)
            if rev > 0:
                revenue, rev_status = rev, "computed"
            elif not st["sold_sig"] and not st["qty_sig"]:
                revenue, rev_status = None, "not_measurable"
            else:
                revenue, rev_status = None, "accumulating"
        rows.append({
            "store_id": sid,
            "name": meta.get("name") or sid,
            "platform": (meta.get("platform") or "").lower(),
            "is_own_store": is_own,
            "score": score,
            "components": {
                "breadth": {"score": round(breadth, 4), "products": n},
                "price": {"score": price_score, "avg_percentile": avg_pctile,
                          "cheapest_rate": cheapest_rate, "shared_products": shared},
                "stock": {"score": stock_score, "in_stock": st["in_stock"]},
                "freshness": {"score": fresh_score, "fresh_products": st["fresh"]},
            },
            "revenue_30d": revenue,
            "revenue_status": rev_status,
            "overlap": len(overlap.get(sid, ())) if not is_own else None,
            "stale": fresh_score < _RANKING_STALE_BELOW,
        })
    rows.sort(key=lambda r: (-r["score"], -r["components"]["breadth"]["products"], r["name"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    own_rank = next((r["rank"] for r in rows if r["is_own_store"]), None)
    return {"window_days": _RANKING_WINDOW_DAYS, "weights": _RANKING_WEIGHTS,
            "total_stores": len(rows), "own_rank": own_rank, "stores": rows}


async def _price_intel_dashboard_compute(db):
    """Price Intelligence Dashboard — all sections."""
    now = datetime.now(timezone.utc)
    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_store_id = own_store["id"] if own_store else None

    # Defensive: only consider documents flagged as belonging to the user's own store
    # (Feb 2026 hardening — prevents accidental "MY PRODUCT" leakage if the my_products
    # collection ever ingests competitor data via a wrong import).
    my_products_query = {"is_own_store": True}
    if own_store_id:
        my_products_query["store_id"] = own_store_id

    # Strictly exclude any matches that point back at our own store as the competitor
    matches_query = {"competitor_store_id": {"$ne": own_store_id}} if own_store_id else {}
    matches = await db.product_matches.find(matches_query, {"_id": 0}).to_list(50000)
    my_products = {p["sku"]: p async for p in db.my_products.find(my_products_query, {"_id": 0})}

    # Latest snapshot crawled_at per (competitor_sku, competitor_store_id) — used
    # for the market_position freshness check (Feb 2026). product_matches.crawled_at
    # is set at match time and grows stale even when snapshots are fresh.
    comp_keys = list({(m["competitor_sku"], m["competitor_store_id"]) for m in matches})
    latest_comp_crawl = {}
    if comp_keys:
        snap_since = now - timedelta(days=7)
        async for sn in db.product_snapshots.find(
            {"sku": {"$in": [k[0] for k in comp_keys]}, "crawled_at": {"$gte": snap_since}},
            {"_id": 0, "sku": 1, "store_id": 1, "crawled_at": 1}
        ).sort("crawled_at", -1):
            key = (sn["sku"], sn["store_id"])
            if key not in latest_comp_crawl:
                latest_comp_crawl[key] = sn["crawled_at"]

    # Fix 5: Separate high-confidence (>=75) from unverified (<75)
    high_conf_matches = [m for m in matches if m.get("confidence", 0) >= 75]
    low_conf_matches = [m for m in matches if 0 < m.get("confidence", 0) < 75]

    # Group high-confidence matches by my_sku
    by_sku = {}
    for m in high_conf_matches:
        by_sku.setdefault(m["my_sku"], []).append(m)

    # Group low-confidence matches separately
    unverified_by_sku = {}
    for m in low_conf_matches:
        unverified_by_sku.setdefault(m["my_sku"], []).append(m)

    action_required = []  # Section A
    my_advantages = []    # Section B
    full_table = []       # Section C
    unverified = []       # Separate tab

    now = datetime.now(timezone.utc)

    for my_sku, ms in by_sku.items():
        mp = my_products.get(my_sku)
        if not mp:
            continue
        my_price = float(mp.get("sale_price") or mp.get("price") or 0)
        my_qty = int(mp.get("quantity", 0))
        if my_price <= 0:
            continue

        cheapest = min(ms, key=lambda x: x["competitor_price"]) if ms else None
        if not cheapest:
            continue

        cheapest_price = cheapest["competitor_price"]
        diff_pct = round(((my_price - cheapest_price) / cheapest_price) * 100, 1) if cheapest_price > 0 else 0
        sellers = len(set(m["competitor_store_id"] for m in ms))
        any_oos = any(not m["competitor_in_stock"] for m in ms)
        all_oos = all(not m["competitor_in_stock"] for m in ms)

        row = {
            "my_sku": my_sku,
            "my_barcode": mp.get("barcode", ""),
            "my_name_ar": mp.get("name_ar", ""),
            "my_name_en": mp.get("name_en", ""),
            "my_price": my_price,
            "my_qty": my_qty,
            "cheapest_competitor": cheapest["competitor_store_name"],
            "cheapest_price": cheapest_price,
            "diff_pct": diff_pct,
            "sellers": sellers,
            "confidence": cheapest["confidence"],
            "match_method": cheapest["match_method"],
            "flags": cheapest.get("flags", []),
            "image_url": mp.get("image_url", ""),
        }

        # Market position (Feb 2026) — own price always counts; competitors use
        # the freshest available crawled_at from product_snapshots (not match.crawled_at,
        # which goes stale).
        seller_list = [{
            "store_id": own_store_id or "own",
            "store_name": "My Store",
            "price": my_price,
            "confidence_score": 99,
            "crawled_at": mp.get("last_synced_at") or now,
        }]
        for cm in ms:
            seller_list.append({
                "store_id": cm.get("competitor_store_id"),
                "store_name": cm.get("competitor_store_name", ""),
                "price": cm.get("competitor_price"),
                "confidence_score": cm.get("confidence", 0),
                "crawled_at": latest_comp_crawl.get((cm.get("competitor_sku"), cm.get("competitor_store_id"))) or cm.get("crawled_at"),
            })
        row["market_position"] = compute_market_position(seller_list, own_store_id or "own")

        # Section A: Action Required
        if diff_pct > 15:
            action_required.append({**row, "severity": "red", "reason": f"Overpriced by {diff_pct}%"})
        elif diff_pct > 5:
            action_required.append({**row, "severity": "yellow", "reason": f"Overpriced by {diff_pct}%"})

        # Section B: My Advantages
        is_cheapest = my_price <= cheapest_price
        if is_cheapest:
            saving = round(cheapest_price - my_price, 2)
            my_advantages.append({**row, "advantage": "cheapest", "saving_sar": saving})
        if all_oos and my_qty > 0:
            my_advantages.append({**row, "advantage": "competitor_oos", "my_stock": my_qty})

        full_table.append(row)

    # Build unverified matches list
    for my_sku, ms in unverified_by_sku.items():
        mp = my_products.get(my_sku)
        if not mp:
            continue
        my_price = float(mp.get("sale_price") or mp.get("price") or 0)
        if my_price <= 0:
            continue
        cheapest = min(ms, key=lambda x: x["competitor_price"]) if ms else None
        if not cheapest:
            continue
        unverified.append({
            "my_sku": my_sku,
            "my_name_ar": mp.get("name_ar", ""),
            "my_name_en": mp.get("name_en", ""),
            "my_price": my_price,
            "cheapest_competitor": cheapest["competitor_store_name"],
            "cheapest_price": cheapest["competitor_price"],
            "diff_pct": round(((my_price - cheapest["competitor_price"]) / cheapest["competitor_price"]) * 100, 1) if cheapest["competitor_price"] > 0 else 0,
            "confidence": cheapest["confidence"],
            "match_method": cheapest["match_method"],
            "flags": cheapest.get("flags", []),
        })

    # Sort
    action_required.sort(key=lambda x: -x["diff_pct"])
    my_advantages.sort(key=lambda x: -(x.get("saving_sar", 0)))
    full_table.sort(key=lambda x: -abs(x["diff_pct"]))
    unverified.sort(key=lambda x: -abs(x.get("diff_pct", 0)))

    # Confidence distribution across all matches
    conf_dist = {"barcode_99": 0, "sku_95": 0, "name_85": 0, "name_80": 0, "name_70": 0, "baseline_80": 0, "confirmed_100": 0}
    for m in matches:
        c = m.get("confidence", 0)
        method = m.get("match_method", "")
        if m.get("manually_confirmed"):
            conf_dist["confirmed_100"] += 1
        elif c == 99 and "barcode" in method:
            conf_dist["barcode_99"] += 1
        elif c == 95 and "sku" in method:
            conf_dist["sku_95"] += 1
        elif c == 85:
            conf_dist["name_85"] += 1
        elif c == 80 and "name" in method:
            conf_dist["name_80"] += 1
        elif c == 80 and m.get("data_source") == "myskuwatch_baseline":
            conf_dist["baseline_80"] += 1
        elif c == 70:
            conf_dist["name_70"] += 1

    return {
        "action_required": action_required,
        "my_advantages": my_advantages,
        "full_table": full_table,
        "unverified": unverified,
        "summary": {
            "total_products": len(my_products),
            "matched_products": len(by_sku),
            "unverified_products": len(unverified_by_sku),
            "overpriced_red": len([a for a in action_required if a["severity"] == "red"]),
            "overpriced_yellow": len([a for a in action_required if a["severity"] == "yellow"]),
            "cheapest_count": len([a for a in my_advantages if a.get("advantage") == "cheapest"]),
            "oos_opportunities": len([a for a in my_advantages if a.get("advantage") == "competitor_oos"]),
        },
        "confidence_distribution": conf_dist,
    }


@router.get("/price-intel/product/{sku}")
async def price_intel_product_detail(sku: str, user=Depends(get_user)):
    """Section D — drill-down for a single product. Strictly own-store sourced."""
    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1, "name": 1, "domain": 1})
    own_store_id = own_store["id"] if own_store else None

    # Hardening (Feb 2026): only return a my_product that is verified own-store.
    mp_query = {"sku": sku, "is_own_store": True}
    if own_store_id:
        mp_query["store_id"] = own_store_id
    mp = await db.my_products.find_one(mp_query, {"_id": 0})
    if not mp:
        # Fall back to the legacy (no flag) lookup so old data still works,
        # but never if the SKU only lives in the shared `products` catalog.
        legacy = await db.my_products.find_one({"sku": sku}, {"_id": 0})
        if not legacy:
            raise HTTPException(404, "Product not found in your catalog")
        mp = legacy

    # Strictly exclude any matches whose competitor is actually our own store
    matches_query = {"my_sku": sku}
    if own_store_id:
        matches_query["competitor_store_id"] = {"$ne": own_store_id}
    matches = await db.product_matches.find(matches_query, {"_id": 0}).to_list(100)

    # Look up competitor barcodes from /products to enrich the cards (Feb 2026: SKU/EAN display)
    comp_skus = list({m["competitor_sku"] for m in matches})
    comp_barcodes_by_sku = {
        p["sku"]: p.get("barcode", "")
        async for p in db.products.find({"sku": {"$in": comp_skus}}, {"_id": 0, "sku": 1, "barcode": 1})
    } if comp_skus else {}

    # Get price history for each matched competitor (last 90 days)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=90)
    competitors = []
    for m in matches:
        history = await db.product_snapshots.find(
            {"sku": m["competitor_sku"], "store_id": m["competitor_store_id"], "crawled_at": {"$gte": cutoff}},
            {"_id": 0, "price": 1, "in_stock": 1, "qty_available": 1, "crawled_at": 1},
        ).sort("crawled_at", 1).to_list(500)

        # Compute price trend
        prices = [h["price"] for h in history if h.get("price")]
        trend = "stable"
        if len(prices) >= 2:
            recent = prices[-3:] if len(prices) >= 3 else prices
            older = prices[:3]
            avg_recent = sum(recent) / len(recent)
            avg_older = sum(older) / len(older)
            if avg_recent > avg_older * 1.03:
                trend = "rising"
            elif avg_recent < avg_older * 0.97:
                trend = "falling"

        competitors.append({
            **m,
            "competitor_barcode": comp_barcodes_by_sku.get(m["competitor_sku"], ""),
            "price_history": [{"price": h["price"], "in_stock": h.get("in_stock"), "date": h["crawled_at"].isoformat() if hasattr(h["crawled_at"], 'isoformat') else str(h["crawled_at"])} for h in history[-60:]],
            "price_trend": trend,
            # Freshness badge (Feb 2026) — latest crawl time for this competitor row.
            # Used by frontend to render Today/X-days-ago/Stale chips.
            "last_crawled_at": (
                history[-1]["crawled_at"].isoformat() if history and hasattr(history[-1]["crawled_at"], "isoformat")
                else (history[-1]["crawled_at"] if history else None)
            ),
        })

    all_prices = [c["competitor_price"] for c in competitors if c["competitor_price"] > 0]
    return {
        "my_product": {**mp, "is_own_store": True},
        "own_store_id": own_store_id,
        "competitors": competitors,
        "market_summary": {
            "lowest_price": min(all_prices) if all_prices else 0,
            "highest_price": max(all_prices) if all_prices else 0,
            "sellers_count": len(competitors),
            "my_price": float(mp.get("sale_price") or mp.get("price") or 0),
        },
    }


@router.post("/price-intel/confirm-match")
async def confirm_match(data: MatchActionIn, user=Depends(get_user)):
    result = await db.product_matches.update_one(
        {"my_sku": data.my_sku, "competitor_sku": data.competitor_sku, "competitor_store_id": data.competitor_store_id},
        {"$set": {"manually_confirmed": True, "confidence": 100, "confirmed_at": datetime.now(timezone.utc).isoformat(), "confirmed_by": user.get("email", "")}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Match not found")
    return {"message": "Match confirmed with confidence 100"}


@router.post("/price-intel/reject-match")
async def reject_match(data: MatchActionIn, user=Depends(get_user)):
    await db.product_matches.delete_one(
        {"my_sku": data.my_sku, "competitor_sku": data.competitor_sku, "competitor_store_id": data.competitor_store_id}
    )
    await db.match_blacklist.update_one(
        {"my_sku": data.my_sku, "competitor_sku": data.competitor_sku},
        {"$set": {
            "my_sku": data.my_sku, "competitor_sku": data.competitor_sku,
            "competitor_store_id": data.competitor_store_id,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "rejected_by": user.get("email", ""),
        }},
        upsert=True,
    )
    return {"message": "Match rejected and blacklisted permanently"}


@router.get("/my-products-list")
async def list_my_products(page: int = 1, limit: int = 50, search: str = "", user=Depends(get_user)):
    query = {}
    if search:
        # P1 search fix (Feb 2026): also match barcode + escape regex meta chars.
        safe = re.escape(search)
        query["$or"] = [
            {"name_ar": {"$regex": safe, "$options": "i"}},
            {"name_en": {"$regex": safe, "$options": "i"}},
            {"sku": {"$regex": safe, "$options": "i"}},
            {"barcode": {"$regex": safe, "$options": "i"}},
        ]
    total = await db.my_products.count_documents(query)
    items = await db.my_products.find(query, {"_id": 0}).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"items": items, "total": total, "page": page, "pages": (total + limit - 1) // limit}


@router.get("/my-skus")
async def get_my_skus(user=Depends(get_user)):
    """Lightweight set of SKUs in the user's own catalog.

    Used by the frontend to highlight "my products" across all pages without
    having to load the heavy `/api/my-products-list` payload.
    """
    skus = [p["sku"] for p in await db.my_products.find({}, {"_id": 0, "sku": 1}).to_list(20000) if p.get("sku")]
    return {"skus": skus, "count": len(skus)}


# ── External Crawler Ingest API ──────────────────────────────
# IngestPayload, _coerce_num, _coerce_int moved to models/schemas.py and core/utils.py (Feb 2026 refactor)


# iter39/40 — classifier version. Bump whenever guess_category /
# classify_food_subcategory rules change so existing products get reclassified
# once at startup (marker doc in metric_rollup_meta, same pattern as the rollup
# schema version). v2 = bowl→accessories, treat-names→food parents, word-bounded
# ستيك/تريت/stick/treat, bundle markers stay generic. v3 = dog signals win the
# parent decision (wrong-parent flips within the food parents), treat-named
# products accepted into pet_food when no animal is named, empty categories
# assigned, jerky/dental/lickable treat forms.
CLASSIFIER_VERSION = 3


async def backfill_food_subcategories(db):
    """Version-gated reclassification pass. For every product with a name:
    recompute the category, but APPLY it only when the change crosses the food
    boundary (into or out of cat_food/dog_food — the scope of the v2 rule
    changes; hand-set non-food labels stay untouched); then recompute
    `subcategory` for food products (None = confidently generic) and clear it
    for products that left the food parents. Returns docs updated."""
    marker = await db.metric_rollup_meta.find_one({"_id": "classifier"})
    if marker and (marker.get("version") or 0) >= CLASSIFIER_VERSION:
        return 0
    n = 0
    parents = set(FOOD_SUBCATEGORY_PARENTS)
    from crawlers import _has_treat_signal, _BOWL_KEYWORDS
    async for p in db.products.find(
            {}, {"_id": 0, "sku": 1, "name_ar": 1, "name_en": 1, "category": 1, "subcategory": 1}):
        name = " ".join(str(x) for x in (p.get("name_ar"), p.get("name_en")) if x)
        lname = name.lower()
        if not lname.strip():
            continue
        old_cat = p.get("category") or ""
        # Category moves ONLY on signal-scoped rules — never a blind recompute,
        # which would clobber hand-set labels on keyword-less names:
        #   v2: bowls/feeders out of the food parents; treat-names into them.
        #   v3: wrong-parent flips WITHIN the food parents when the name's own
        #       animal signals disagree (Zolux "…للكلاب" stored as cat_food);
        #       treat-names with no clear animal go to pet_food (out of
        #       accessories); empty categories get assigned from the name.
        cat = old_cat
        guessed = guess_category(p.get("name_ar") or p.get("name_en") or "")
        if any(w in lname for w in _BOWL_KEYWORDS):
            cat = "accessories"
        elif not old_cat:
            cat = guessed                              # v3: 34 empty-category docs
        elif old_cat in parents:
            if guessed in parents and guessed != old_cat:
                cat = guessed                          # v3: cat↔dog parent flip
        elif _has_treat_signal(lname):
            if guessed in parents or guessed in ("pet_food", "bird_food", "fish_food"):
                cat = guessed                          # v2+v3: treat-name into food
        sub = classify_food_subcategory(cat, name) if cat in parents else None
        update = {}
        if cat != old_cat:
            update["category"] = cat
        if sub != p.get("subcategory") or "subcategory" not in p:
            update["subcategory"] = sub
        if update:
            await db.products.update_one({"sku": p["sku"]}, {"$set": update})
            n += 1
    await db.metric_rollup_meta.update_one(
        {"_id": "classifier"},
        {"$set": {"version": CLASSIFIER_VERSION, "updated_at": datetime.now(timezone.utc)}},
        upsert=True)
    return n


@router.post("/admin/own-store-vat-backfill")
async def own_store_vat_backfill(dry_run: bool = Query(True), sample: int = Query(10, ge=1, le=100),
                                 user=Depends(get_user)):
    """iter44 STEP 3 — one-off backfill of existing my_products rows onto the
    VAT-inclusive basis, using the SAME storefront source Step 2 now syncs from.

    dry_run=true (default) reports before/after with zero writes. Rows the
    storefront doesn't carry are left untouched and counted (they keep the
    merchant ex-VAT basis, tagged, exactly like the sync's fallback).
    super_admin only."""
    if (user or {}).get("role") != "super_admin" and not is_super_admin_email((user or {}).get("email", "")):
        raise HTTPException(403, "super_admin only")
    store = await db.stores.find_one({"is_own_store": True}, {"_id": 0})
    if not store:
        raise HTTPException(400, "no store flagged is_own_store=True")

    sf_rows, sf_meta = await fetch_own_storefront_catalog_raw(store)
    if not sf_meta.get("ok") or not sf_rows:
        raise HTTPException(502, f"storefront fetch failed — refusing to backfill: {sf_meta}")
    idx = _storefront_price_index(sf_rows)

    # iter46 — the storefront genuinely lists only part of the catalogue, so the
    # Merchant pull is needed both to PRICE the remainder and to tell a live
    # merchant-only product from a stale row no source touches any more.
    merchant_rows, merchant_status = await _fetch_zid_api_catalog(db, store)
    m_idx = merchant_index(merchant_rows)

    now = datetime.now(timezone.utc)

    def _age_days(ts):
        if not ts:
            return None
        try:
            d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (now - d).days

    def _bucket(days):
        if days is None:
            return "never_synced"
        for lim, label in ((7, "<7d"), (30, "7-30d"), (90, "30-90d")):
            if days < lim:
                return label
        return ">90d"

    changed, unchanged, no_source = [], 0, []
    match_methods, basis_counts = {}, {}
    stale = {"by_sync_source": {}, "by_age": {}, "samples": []}
    # iter47 D — the same rows resolved with the PREVIOUS key set, so the gain
    # from the new keys is measured rather than asserted.
    no_source_before = 0
    recovered = {"count": 0, "by_method": {}, "samples": []}
    async for p in db.my_products.find(
            {}, {"_id": 0, "sku": 1, "barcode": 1, "price": 1, "sale_price": 1,
                 "price_basis": 1, "sync_source": 1, "last_synced_at": 1,
                 "product_page_url": 1}):
        sku = str(p.get("sku") or "").strip()
        url = p.get("product_page_url")
        hit, method = storefront_price_lookup(idx, sku=sku, barcode=p.get("barcode"),
                                              product_url=url)
        m_row, m_method = (None, None)
        if not hit:
            m_row, m_method = storefront_price_lookup(m_idx, sku=sku, barcode=p.get("barcode"),
                                                      product_url=url)

        # what the pre-iter47 key set would have found for this same row
        legacy = storefront_price_lookup(idx, sku=sku, barcode=p.get("barcode"),
                                         canonical=False)[0]
        if not legacy:
            legacy = storefront_price_lookup(m_idx, sku=sku, barcode=p.get("barcode"),
                                             canonical=False)[0]
        if not legacy:
            no_source_before += 1
            if hit or m_row:
                won = method or m_method
                recovered["count"] += 1
                recovered["by_method"][won] = recovered["by_method"].get(won, 0) + 1
                if len(recovered["samples"]) < 20:
                    recovered["samples"].append({"sku": sku, "barcode": p.get("barcode"),
                                                 "method": won})

        if not hit and not m_row:
            # in NEITHER live source — stale. Never VAT-inflated; reported so a
            # prune can be considered instead.
            no_source.append(sku)
            src = p.get("sync_source") or "(none)"
            stale["by_sync_source"][src] = stale["by_sync_source"].get(src, 0) + 1
            b = _bucket(_age_days(p.get("last_synced_at")))
            stale["by_age"][b] = stale["by_age"].get(b, 0) + 1
            if len(stale["samples"]) < 20:
                stale["samples"].append({"sku": sku, "sync_source": src,
                                         "last_synced_at": p.get("last_synced_at"),
                                         "price": p.get("price")})
            continue
        match_methods[method or m_method] = match_methods.get(method or m_method, 0) + 1
        new_price, new_sale, basis = resolve_own_price(
            hit,
            merchant_price=(m_row or {}).get("price"),
            merchant_sale_price=(m_row or {}).get("sale_price"),
            is_taxable=(m_row or {}).get("is_taxable"),
        )
        basis_counts[basis] = basis_counts.get(basis, 0) + 1
        old_price = p.get("price")
        old_eff = p.get("sale_price") or old_price          # what the UI shows today
        if (old_price is not None and abs(float(old_price) - new_price) <= 0.009
                and p.get("price_basis") == basis):
            unchanged += 1
            continue
        changed.append({
            "sku": sku,
            "before_price": old_price, "before_sale_price": p.get("sale_price"),
            "before_effective": round(float(old_eff), 2) if old_eff else None,
            "after_price": new_price, "after_sale_price": new_sale,
            "ratio": round(new_price / float(old_eff), 4) if old_eff else None,
            "before_basis": p.get("price_basis"), "after_basis": basis,
        })

    report = {
        "dry_run": dry_run,
        "storefront": {"endpoint": sf_meta.get("endpoint"), "rows": sf_meta.get("rows"),
                       "pages": sf_meta.get("pages"), "stop_reason": sf_meta.get("stop_reason"),
                       "truncated": sf_meta.get("truncated"),
                       "priced_skus": len(idx["by_sku"]),
                       "priced_barcode_keys": len(idx["by_barcode"])},
        "match_methods": match_methods,
        "merchant": {"status": merchant_status, "rows": len(merchant_rows),
                     "vat_rate": KSA_VAT_RATE},
        "my_products_total": await db.my_products.count_documents({}),
        "would_update" if dry_run else "updated": len(changed),
        "already_on_target_basis": unchanged,
        "price_basis_counts": basis_counts,
        # rows in NEITHER live source — candidates for pruning, never inflated
        "no_live_source_before_iter47_keys": no_source_before,
        "recovered_by_iter47_keys": recovered,
        "no_live_source": len(no_source),
        "no_live_source_sample": no_source[:20],
        "stale_breakdown": stale,
        "sample": changed[:sample],
    }
    if dry_run:
        return report

    for c in changed:
        await db.my_products.update_one({"sku": c["sku"]}, {"$set": {
            "price": c["after_price"],
            "sale_price": c["after_sale_price"],
            "price_basis": c["after_basis"],
            "vat_backfilled_at": datetime.now(timezone.utc).isoformat(),
        }})
    # rows no live source carries are left EXACTLY as they are — untouched and
    # unpriced-over, so a prune decision stays open
    if no_source:
        await db.my_products.update_many(
            {"sku": {"$in": no_source}, "price_basis": {"$exists": False}},
            {"$set": {"price_basis": "no_live_source"}})
    report["after_verification"] = [
        {"sku": c["sku"], **{k: v for k, v in (await db.my_products.find_one(
            {"sku": c["sku"]}, {"_id": 0, "price": 1, "sale_price": 1, "price_basis": 1})).items()}}
        for c in changed[:sample]
    ]
    return report


@router.get("/admin/own-store-price-audit")
async def own_store_price_audit(sample: int = Query(20, ge=1, le=200), user=Depends(get_user)):
    """iter44 STEP 1 — read-only validation of the own-store VAT-basis fix.

    Answers, against LIVE data, the four questions that must pass before the
    price source is switched from the Zid Merchant API (ex-VAT) to the public
    storefront (inc-VAT):
      1. SKU coverage in both directions (merchant-only / storefront-only)
      2. per-SKU price ratio distribution (expect ~1.15 taxable / ~1.00 not)
      3. storefront `price` vs `effective_price` divergence (sale items)
      4. storefront catalogue completeness (full catalogue, not a partial page)

    Writes NOTHING and changes NO behaviour — the sync still uses the Merchant
    price until Step 2 is explicitly approved. super_admin only.
    """
    if (user or {}).get("role") != "super_admin" and not is_super_admin_email((user or {}).get("email", "")):
        raise HTTPException(403, "super_admin only")
    store = await db.stores.find_one({"is_own_store": True}, {"_id": 0})
    if not store:
        raise HTTPException(400, "no store flagged is_own_store=True")

    merchant_rows, zid_status = await _fetch_zid_api_catalog(db, store)
    sf_rows, sf_meta = await fetch_own_storefront_catalog_raw(store)

    def _k(v):
        return str(v or "").strip()

    merchant, sf, sf_by_bc = {}, {}, {}
    for r in merchant_rows:
        if _k(r.get("sku")):
            merchant[_k(r["sku"])] = r
    for r in sf_rows:
        if _k(r.get("sku")):
            sf[_k(r["sku"])] = r
        if _k(r.get("barcode")):
            sf_by_bc[_k(r["barcode"])] = r

    # ── Q1: coverage both directions ──
    m_only = sorted(set(merchant) - set(sf))
    s_only = sorted(set(sf) - set(merchant))
    both = sorted(set(merchant) & set(sf))
    # the sync matches barcode-FIRST, so a merchant-only SKU may still be
    # recoverable from the storefront via barcode — that changes the true
    # fallback rate, so measure it rather than assuming.
    m_only_by_barcode = [s for s in m_only if _k(merchant[s].get("barcode")) in sf_by_bc]

    # ── Q2/Q3: ratios + price/effective_price divergence over the FULL overlap ──
    stored = {p["sku"]: p async for p in db.my_products.find(
        {"sku": {"$in": both}}, {"_id": 0, "sku": 1, "price": 1, "sale_price": 1, "sync_source": 1})}
    buckets = {"vat_15": 0, "parity": 0, "other": 0, "unusable": 0}
    detail, others, diverged = [], [], []
    for s in both:
        mp = _price_amount(merchant[s].get("price"))
        sp = _price_amount(sf[s].get("price"))
        se = _price_amount(sf[s].get("effective_price"))
        shelf = se if se > 0 else sp          # effective_price is the shelf price when present
        taxable = sf[s].get("is_taxable")
        ratio = round(shelf / mp, 4) if (mp > 0 and shelf > 0) else None
        if ratio is None:
            buckets["unusable"] += 1
        elif abs(ratio - 1.15) <= 0.005:
            buckets["vat_15"] += 1
        elif abs(ratio - 1.0) <= 0.005:
            buckets["parity"] += 1
        else:
            buckets["other"] += 1
        row = {"sku": s, "merchant_price": mp, "storefront_price": sp,
               "storefront_effective_price": se, "shelf_price": shelf,
               "ratio": ratio, "is_taxable": taxable,
               "stored_now": (stored.get(s) or {}).get("price"),
               "stored_sync_source": (stored.get(s) or {}).get("sync_source")}
        if ratio is not None and abs(ratio - 1.15) > 0.005 and abs(ratio - 1.0) > 0.005 and len(others) < 10:
            others.append(row)
        if sp > 0 and se > 0 and abs(sp - se) > 0.009 and len(diverged) < 10:
            diverged.append({**row, "lower_field": "effective_price" if se < sp else "price"})
        if len(detail) < sample:
            detail.append(row)

    # ── Q4: storefront catalogue completeness ──
    sf_priced = sum(1 for r in sf_rows
                    if _price_amount(r.get("effective_price")) > 0 or _price_amount(r.get("price")) > 0)
    completeness = {
        "storefront_fetch": sf_meta,
        "storefront_pages": sf_meta.get("pages"),
        "storefront_stop_reason": sf_meta.get("stop_reason"),
        "storefront_truncated": sf_meta.get("truncated"),
        "storefront_rows": len(sf_rows),
        "storefront_distinct_skus": len(sf),
        "storefront_rows_with_usable_price": sf_priced,
        "storefront_priced_pct": round(100 * sf_priced / len(sf_rows), 1) if sf_rows else 0,
        "merchant_rows": len(merchant_rows),
        "merchant_distinct_skus": len(merchant),
        "merchant_status": zid_status,
        "my_products_total": await db.my_products.count_documents({}),
    }

    n_both = len(both) or 1
    return {
        "store": {"name": store.get("name"), "domain": store.get("domain"), "platform": store.get("platform")},
        "q1_coverage": {
            "in_both": len(both),
            "merchant_only": len(m_only),
            "merchant_only_recoverable_by_barcode": len(m_only_by_barcode),
            "merchant_only_truly_absent": len(m_only) - len(m_only_by_barcode),
            "storefront_only": len(s_only),
            "merchant_only_sample": m_only[:20],
            "storefront_only_sample": s_only[:20],
        },
        "q2_ratio_distribution": {
            **buckets,
            "vat_15_pct": round(100 * buckets["vat_15"] / n_both, 1),
            "verdict": ("consistent_vat_15" if buckets["other"] == 0 and buckets["vat_15"] > 0
                        else "mixed_or_random — INSPECT q2_other_samples"),
        },
        "q2_sample": detail,
        "q2_other_samples": others,
        "q3_price_vs_effective": {
            "diverging_count": sum(1 for s in both
                                   if _price_amount(sf[s].get("price")) > 0
                                   and _price_amount(sf[s].get("effective_price")) > 0
                                   and abs(_price_amount(sf[s].get("price")) - _price_amount(sf[s].get("effective_price"))) > 0.009),
            "samples": diverged,
            "note": "effective_price is treated as the shelf price when > 0; price is the fallback",
        },
        "q4_completeness": completeness,
    }


def _demo_seed_skus():
    """iter39/41 — THE single source of truth for demo-seed detection: the
    literal SKU values of the synthetic seed templates. Used by the
    subcategory preview's demo flags and the demo-cleanup endpoint."""
    return {t[0] for t in PRODUCTS_SEED + EXTRA_PRODUCT_TEMPLATES}


# iter41 — every collection that stores a product reference, with the exact
# match predicate for a given (skus, product_ids) pair. Audited across
# server.py/crawlers.py/matcher.py: snapshots carry sku+product_id; matches and
# the blacklist carry my_sku/competitor_sku; alerts carry product_sku;
# alert_events carry both product_sku and sku; baseline stats/opportunities are
# barcode-keyed from the real MySkuWatch import (included for completeness —
# expected 0). dashboard_cache holds derived pages only (rebuilt by recompute).
def _demo_cascade_queries(skus, ids):
    sk = {"$in": sorted(skus)}
    return [
        ("product_snapshots", {"$or": [{"sku": sk}, {"product_id": {"$in": sorted(ids)}}]}),
        ("product_matches", {"$or": [{"my_sku": sk}, {"competitor_sku": sk}]}),
        ("match_blacklist", {"$or": [{"my_sku": sk}, {"competitor_sku": sk}]}),
        ("sku_store_coverage", {"sku": sk}),
        ("sku_sales_daily", {"sku": sk}),
        ("my_products", {"sku": sk}),
        ("alerts", {"product_sku": sk}),
        ("alert_events", {"$or": [{"sku": sk}, {"product_sku": sk}]}),
        ("product_baseline_stats", {"sku": sk}),
        ("market_opportunities", {"sku": sk}),
        ("products", {"sku": sk}),
    ]


_REAL_SKU_RE = re.compile(r"^\d{8,14}$")   # numeric GTIN — never a seed SKU


async def _demo_subcategory_counts(db):
    counts = {}
    async for p in db.products.find({}, {"_id": 0, "category": 1, "subcategory": 1}):
        key = p.get("subcategory") or p.get("category") or ""
        counts[key] = counts.get(key, 0) + 1
    return counts


@router.get("/admin/demo-cleanup")
async def demo_cleanup_get(dry_run: bool = Query(True), user=Depends(get_user)):
    """iter42 — browser-friendly DRY RUN ONLY. GET can never delete: the
    destructive path stays POST-only, so a prefetched/crawled/retried URL is
    harmless by construction."""
    if not dry_run:
        raise HTTPException(405, "GET is dry-run only — use POST /api/admin/demo-cleanup?dry_run=false for the real run")
    return await demo_cleanup(dry_run=True, user=user)


@router.post("/admin/demo-cleanup")
async def demo_cleanup(dry_run: bool = Query(True), confirm_count: Optional[int] = Query(None), user=Depends(get_user)):
    """iter41/43 — remove the synthetic seed catalog from production.

    dry_run=true (default): full report, zero writes. Real run
    (dry_run=false): REQUIRES confirm_count to exactly equal the live demo
    count computed at run time — you delete exactly the set you reviewed, or
    nothing. The real-SKU guard is ALWAYS ON and never overridable; a
    catastrophe cap (1000) protects against detector drift regardless of
    confirm_count. Backs up every affected document into
    demo_cleanup_backup_<ts>_<collection> BEFORE any delete, cascades across
    every referencing collection, then triggers the rollup/cache recomputes so
    totals update immediately. super_admin only."""
    if (user or {}).get("role") != "super_admin" and not is_super_admin_email((user or {}).get("email", "")):
        raise HTTPException(403, "super_admin only")

    demo_skus = _demo_seed_skus()
    matched = await db.products.find(
        {"sku": {"$in": sorted(demo_skus)}},
        {"_id": 0, "sku": 1, "id": 1, "category": 1, "subcategory": 1},
    ).to_list(length=None)
    skus = {p["sku"] for p in matched}
    ids = {p.get("id") for p in matched if p.get("id")}

    # ── safety guard (iter43 contract) ──
    guard_reasons = []
    real_looking = sorted(s for s in skus if s.startswith("Z.") or s.startswith("S-PE-") or _REAL_SKU_RE.match(s))
    if real_looking:
        guard_reasons.append(f"detector matched real-crawl-shaped SKUs: {real_looking[:10]}")
    if len(skus) > 1000:
        guard_reasons.append(f"demo count {len(skus)} exceeds the 1000 catastrophe cap (detector drift?)")
    if not dry_run:
        # never overridable: real-SKU match and the catastrophe cap block the run
        if guard_reasons:
            raise HTTPException(409, f"demo-cleanup refused: {'; '.join(guard_reasons)}")
        # confirm-count contract: the caller must confirm the EXACT live count
        if confirm_count != len(skus):
            raise HTTPException(
                409,
                f"demo-cleanup refused: confirm_count={confirm_count} does not match the "
                f"live demo count {len(skus)} — re-run the dry run, review, and confirm the exact number")

    # ── report material: breakdowns + cascade counts ──
    by_category = {}
    for p in matched:
        key = p.get("subcategory") or p.get("category") or ""
        by_category[key] = by_category.get(key, 0) + 1
    by_store_rows = await db.product_snapshots.aggregate([
        {"$match": {"sku": {"$in": sorted(skus)}}},
        {"$group": {"_id": "$store_id", "n": {"$sum": 1}}},
    ], allowDiskUse=True).to_list(length=None) if skus else []
    by_store = {r["_id"]: r["n"] for r in by_store_rows}

    cascade = _demo_cascade_queries(skus, ids) if skus else []
    cascade_counts = {}
    for coll, q in cascade:
        cascade_counts[coll] = await db[coll].count_documents(q)

    before = {
        "my_products_total": await db.my_products.count_documents({}),
        "total_matches": await db.product_matches.count_documents({}),
        "subcategory_counts": await _demo_subcategory_counts(db),
    }
    report = {
        "dry_run": dry_run,
        "guard": {"ok": not guard_reasons, "reasons": guard_reasons,
                  # iter43 — frontend contract: the button must disable on a
                  # real-SKU match, and the POST must confirm this exact count.
                  "real_sku_match": bool(real_looking),
                  "confirm_count_required": len(skus)},
        "demo_products": len(skus),
        "by_category": by_category,
        "by_store_snapshots": by_store,
        "cascade_counts": cascade_counts,
        "before": before,
    }
    if dry_run or not skus:
        return report

    # ── real run: backup FIRST, then delete, per collection ──
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backups = {}
    for coll, q in cascade:
        docs = await db[coll].find(q).to_list(length=None)
        bname = f"demo_cleanup_backup_{ts}_{coll}"
        if docs:
            await db[bname].insert_many(docs)     # backup written before any delete
        backups[coll] = {"backup_collection": bname, "docs": len(docs)}
    await db[f"demo_cleanup_backup_{ts}_manifest"].insert_one({
        "_id": "manifest", "created_at": datetime.now(timezone.utc),
        "skus": sorted(skus), "collections": {k: v["docs"] for k, v in backups.items()},
    })
    for coll, q in cascade:
        await db[coll].delete_many(q)

    # ── recompute so dashboards reflect the new totals immediately ──
    recompute = {}
    try:
        recompute["store_metrics"] = await recompute_all_store_metrics(db)
    except Exception as e:
        recompute["store_metrics"] = f"ERROR: {str(e)[:80]}"
    recompute["dashboard_cache"] = "recomputed" if await maybe_recompute_dashboard_cache(db, force=True) else "skipped"
    recompute["page_caches"] = "recomputed" if await maybe_recompute_page_caches(db, force=True) else "skipped"

    report["after"] = {
        "my_products_total": await db.my_products.count_documents({}),
        "total_matches": await db.product_matches.count_documents({}),
        "subcategory_counts": await _demo_subcategory_counts(db),
    }
    report["backups"] = backups
    report["backup_timestamp"] = ts
    report["recompute"] = recompute
    return report


# ── iter48: store cleanup ────────────────────────────────────────────────────
# Trim the registry down to the 11 stores we actually track. Same safety
# contract as demo-cleanup: dry-run GET, destructive POST behind confirm_count,
# backup-before-delete, full cascade, recompute.
#
# (display name, bare domain). Domains are the PRIMARY key; the name is only a
# secondary signal, because a store can be renamed in the UI but its domain is
# what every crawl and snapshot is keyed to.
STORE_CLEANUP_KEEP_LIST = [
    ("aleef", "aleef.com"),
    ("Petsy", "petsysa.com"),
    ("Zarafa", "zarafaksa.com"),
    ("Caty Store", "caty-store.com"),
    ("CutePets", "cutepets.com.sa"),
    ("Hamtaro", "hamtaro.sa"),
    ("Hobba", "hobbapet.com"),
    ("Lana Pets", "lanapets.com"),
    ("Mowkly", "mowkly.com"),
    ("Panda Store", "matjarpanda.com"),
    ("Pets houses", "pets-houses.com"),
]
STORE_CLEANUP_EXPECTED_KEEP = 11
STORE_CLEANUP_MAX_DELETE = 50          # catastrophe cap


def normalize_store_domain(value):
    """Bare comparable domain: no scheme, no www., no trailing slash or path."""
    d = str(value or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].strip()


def _normalize_store_name(value):
    return " ".join(str(value or "").strip().lower().split())


# Every collection that carries a reference to a store, with the exact match
# predicate for a given delete set. Audited across server.py / crawlers.py /
# matcher.py / zid_orders.py / store_registry.py:
#   store_id      snapshots, coverage, sales, rollups, crawl_logs, otp_requests,
#                 alerts, proxy_usage
#   competitor_store_id  product_matches, match_blacklist
#   store_name    alert_events (no id is persisted on the event)
#   store_domain  proxy_usage, market_leaderboard, market_intelligence_baseline
# `stores` itself is last so the store row outlives its own cascade if a delete
# fails part-way through.
#
# Deliberately NOT cascaded, with reasons reported to the caller:
#   products / my_products  keyed by SKU, no store reference at all
#   market_digests          one doc per WEEK; a store name appears only inside
#                           content.market_summary.most_active_store, so
#                           deleting by it would destroy unrelated history
#   dashboard_cache         derived only — rebuilt by the recompute below
#   sync_runs, users, saved_filters, matching_jobs, metric_rollup_meta,
#   own_store_orders, product_baseline_stats, market_opportunities
#                           no store reference (barcode-, user- or global-keyed)
def _store_cascade_queries(store_ids, domains, names):
    sid = {"$in": sorted(store_ids)}
    dom = {"$in": sorted(domains)}
    return [
        ("product_snapshots", {"store_id": sid}),
        ("product_matches", {"competitor_store_id": sid}),
        ("match_blacklist", {"competitor_store_id": sid}),
        ("sku_store_coverage", {"store_id": sid}),
        ("sku_sales_daily", {"store_id": sid}),
        ("metric_daily_rollups", {"store_id": sid}),
        ("crawl_logs", {"store_id": sid}),
        ("otp_requests", {"store_id": sid}),
        ("alerts", {"store_id": sid}),
        ("alert_events", {"store_name": {"$in": sorted(names)}}),
        ("proxy_usage", {"$or": [{"store_id": sid}, {"store_domain": dom}]}),
        ("market_leaderboard", {"store_domain": dom}),
        ("market_intelligence_baseline", {"store_domain": dom}),
        ("stores", {"id": sid}),
    ]

_STORE_CASCADE_SKIPPED = {
    "products": "SKU-keyed global catalog — no store reference",
    "my_products": "own-store catalog, SKU-keyed — own store is never deletable",
    "market_digests": "one doc per week; store appears only inside content.market_summary — deleting by it would destroy unrelated history",
    "dashboard_cache": "derived only — rebuilt by the recompute step",
    "sync_runs": "no store reference",
    "matching_jobs": "no store reference (singleton job doc)",
    "metric_rollup_meta": "no store reference (schema marker)",
    "own_store_orders": "own-store orders — own store is never deletable",
    "product_baseline_stats": "barcode-keyed",
    "market_opportunities": "barcode-keyed",
    "users": "no store reference",
    "saved_filters": "user-keyed",
}


# iter49 — the destructive path used to read a whole collection with
# `find(q).to_list(length=None)` and hand the entire result to one insert_many.
# On production that meant ~63k CuteCat snapshots in a single round trip, which
# blows the client's socketTimeoutMS=45000 cap and surfaced as a bare 500 with
# nothing deleted. Everything below moves in bounded batches instead, and every
# step reports which collection failed and why.
_STORE_CLEANUP_BATCH = 1000


class StoreCleanupError(Exception):
    """Carries the structured detail returned to the caller on a 500."""

    def __init__(self, detail):
        super().__init__(detail.get("error", "store-cleanup failed"))
        self.detail = detail


async def _copy_in_batches(db, src, dst, q, batch=_STORE_CLEANUP_BATCH,
                           tolerate_duplicates=False):
    """Copy every doc matching `q` from `src` into `dst`, `batch` docs at a time.

    Ids are fetched first and the documents are then pulled by id chunk, so no
    cursor is held open across a write and no single operation is unbounded.
    `tolerate_duplicates` is for the restore path, where some documents may have
    survived a partially-applied delete_many. Returns the number copied."""
    ids = [d["_id"] async for d in db[src].find(q, {"_id": 1}).batch_size(5000)]
    copied = 0
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        docs = await db[src].find({"_id": {"$in": chunk}}).to_list(length=len(chunk))
        if not docs:
            continue
        try:
            res = await db[dst].insert_many(docs, ordered=False)
            copied += len(res.inserted_ids)
        except BulkWriteError as e:
            if not tolerate_duplicates:
                raise
            # every non-duplicate error is still fatal
            errs = e.details.get("writeErrors") or []
            if any(w.get("code") != 11000 for w in errs):
                raise
            copied += len(docs) - len(errs)
    return copied


async def _store_cleanup_backup(db, cascade, ts):
    """Back every cascaded collection up BEFORE anything is deleted.

    Any failure here aborts with nothing deleted — the safe outcome — and names
    the collection and the underlying error."""
    backups = {}
    for coll, q in cascade:
        bname = f"store_cleanup_backup_{ts}_{coll}"
        try:
            expected = await db[coll].count_documents(q)
            # a same-second re-run would merge two backups into one collection
            if await db[bname].estimated_document_count():
                raise RuntimeError(f"backup collection {bname} already exists and is non-empty")
            copied = await _copy_in_batches(db, coll, bname, q)
            verified = await db[bname].count_documents({})
            if verified != expected:
                raise RuntimeError(
                    f"backup verification failed: {coll} has {expected} matching docs "
                    f"but {bname} holds {verified}")
        except Exception as e:
            logger.exception("[StoreCleanup] backup failed for %s", coll)
            raise StoreCleanupError({
                "error": "store-cleanup aborted during BACKUP — nothing was deleted",
                "phase": "backup",
                "collection": coll,
                "backup_collection": bname,
                "exception": type(e).__name__,
                "message": str(e)[:400],
                "completed_backups": {k: v["docs"] for k, v in backups.items()},
                "hint": ("large collections are copied in batches of "
                         f"{_STORE_CLEANUP_BATCH}; a timeout here points at the database, "
                         "not at the batch size"),
            })
        backups[coll] = {"backup_collection": bname, "docs": copied, "verified": True}
    return backups


async def _store_cleanup_delete(db, cascade, backups, ts):
    """Delete each cascaded collection, restoring from the backups already taken
    if any single delete fails, so a half-cascade never leaves orphans."""
    deleted, done = {}, []
    for coll, q in cascade:
        try:
            res = await db[coll].delete_many(q)
            deleted[coll] = res.deleted_count
            done.append(coll)
        except Exception as e:
            logger.exception("[StoreCleanup] delete failed for %s — restoring", coll)
            restored, restore_errors = {}, {}
            # `coll` itself is included: delete_many is not atomic across
            # documents, so the failing collection may be partially deleted too.
            for prev in done + [coll]:
                bname = backups[prev]["backup_collection"]
                try:
                    # the backup is the pre-delete truth; re-insert what is
                    # missing and skip anything that survived as a duplicate.
                    restored[prev] = await _copy_in_batches(
                        db, bname, prev, {}, tolerate_duplicates=True)
                except Exception as re_err:
                    restore_errors[prev] = f"{type(re_err).__name__}: {str(re_err)[:200]}"
                    logger.exception("[StoreCleanup] restore failed for %s", prev)
            raise StoreCleanupError({
                "error": "store-cleanup failed mid-cascade — earlier deletes were rolled back",
                "phase": "delete",
                "collection": coll,
                "exception": type(e).__name__,
                "message": str(e)[:400],
                "deleted_before_failure": deleted,
                "restored": restored,
                "restore_errors": restore_errors,
                "backup_timestamp": ts,
                "hint": ("every affected document is still in "
                         f"store_cleanup_backup_{ts}_* — restore from there if the "
                         "automatic rollback above reports errors"),
            })
    return deleted


async def _resolve_store_cleanup(db):
    """Resolve the keep-list against live stores and compute the delete set.

    Returns (keep_rows, delete_rows, unresolved, live_total). Pure read."""
    live = await db.stores.find({}, {"_id": 0}).to_list(length=None)
    by_domain = {}
    for s in live:
        by_domain.setdefault(normalize_store_domain(s.get("domain")), []).append(s)
    by_name = {}
    for s in live:
        by_name.setdefault(_normalize_store_name(s.get("name")), []).append(s)

    keep_rows, unresolved, kept_ids = [], [], set()
    for name, domain in STORE_CLEANUP_KEEP_LIST:
        nd = normalize_store_domain(domain)
        hits = by_domain.get(nd) or []
        matched_on = "domain"
        if not hits:
            # secondary signal only — a renamed store keeps its domain, but a
            # re-pointed domain keeps its name
            hits = by_name.get(_normalize_store_name(name)) or []
            matched_on = "name" if hits else None
        if not hits:
            unresolved.append({"keep_name": name, "keep_domain": domain,
                               "normalized_domain": nd, "matched": 0})
            continue
        for s in hits:
            kept_ids.add(s["id"])
        keep_rows.append({
            "keep_name": name, "keep_domain": domain, "normalized_domain": nd,
            "matched_on": matched_on, "matched": len(hits),
            "store_ids": [s["id"] for s in hits],
            "store_names": [s.get("name") for s in hits],
            "is_own_store": any(bool(s.get("is_own_store")) for s in hits),
        })

    delete_rows = [s for s in live if s["id"] not in kept_ids]
    return keep_rows, delete_rows, unresolved, len(live)


@router.get("/admin/store-cleanup")
async def store_cleanup_get(dry_run: bool = Query(True), user=Depends(get_user)):
    """iter48 — browser-friendly DRY RUN ONLY. GET can never delete: the
    destructive path stays POST-only, so a prefetched / crawled / retried URL is
    harmless by construction."""
    if not dry_run:
        raise HTTPException(405, "GET is dry-run only — use POST /api/admin/store-cleanup?dry_run=false&confirm_count=N for the real run")
    return await store_cleanup(dry_run=True, user=user)


@router.post("/admin/store-cleanup")
async def store_cleanup(dry_run: bool = Query(True), confirm_count: Optional[int] = Query(None),
                        user=Depends(get_user)):
    """iter48 — delete every competitor store that is NOT in the 11-store
    keep-list, cascading across every collection that references a store.

    dry_run=true (default): full report, zero writes. Real run
    (dry_run=false): REQUIRES confirm_count to exactly equal the delete-set size
    computed at run time — you delete exactly the set you reviewed, or nothing.

    Three guards abort with 409 and are NEVER overridable by confirm_count:
      1. an own-store (is_own_store=true) landed in the delete set
      2. the keep-list did not resolve to exactly 11 live stores — each
         zero-match keep-domain is named, so a domain-format mismatch can never
         silently delete a store we meant to keep
      3. the delete set exceeds 50 stores

    Backs every affected document up into store_cleanup_backup_<ts>_<collection>
    BEFORE any delete, then recomputes rollups, ranking and dashboard caches.
    super_admin only."""
    if (user or {}).get("role") != "super_admin" and not is_super_admin_email((user or {}).get("email", "")):
        raise HTTPException(403, "super_admin only")

    keep_rows, delete_rows, unresolved, live_total = await _resolve_store_cleanup(db)
    resolved_keep_stores = sum(r["matched"] for r in keep_rows)
    delete_ids = {s["id"] for s in delete_rows}
    delete_domains = {normalize_store_domain(s.get("domain")) for s in delete_rows if s.get("domain")}
    delete_names = {s.get("name") for s in delete_rows if s.get("name")}

    # ── hard guards — never overridable ──
    guard_reasons = []
    own_in_delete = [{"id": s["id"], "name": s.get("name"), "domain": s.get("domain")}
                     for s in delete_rows if s.get("is_own_store")]
    if own_in_delete:
        guard_reasons.append(
            "delete set contains is_own_store=true store(s): "
            + ", ".join(f"{s['name']} ({s['domain']})" for s in own_in_delete))
    if unresolved:
        guard_reasons.append(
            "keep-list domain(s) matched ZERO live stores — refusing so a domain-format "
            "mismatch cannot delete a store we meant to keep: "
            + ", ".join(f"{u['keep_name']} <{u['keep_domain']}>" for u in unresolved))
    if resolved_keep_stores != STORE_CLEANUP_EXPECTED_KEEP:
        guard_reasons.append(
            f"keep-list resolved to {resolved_keep_stores} live stores, expected "
            f"{STORE_CLEANUP_EXPECTED_KEEP}")
    if len(delete_ids) > STORE_CLEANUP_MAX_DELETE:
        guard_reasons.append(
            f"delete set {len(delete_ids)} exceeds the {STORE_CLEANUP_MAX_DELETE} "
            "catastrophe cap")

    if not dry_run:
        if guard_reasons:
            raise HTTPException(409, f"store-cleanup refused: {'; '.join(guard_reasons)}")
        if confirm_count != len(delete_ids):
            raise HTTPException(
                409,
                f"store-cleanup refused: confirm_count={confirm_count} does not match the "
                f"live delete-set size {len(delete_ids)} — re-run the dry run, review, and "
                "confirm the exact number")

    # ── report material ──
    cascade = _store_cascade_queries(delete_ids, delete_domains, delete_names) if delete_ids else []
    cascade_counts = {}
    for coll, q in cascade:
        cascade_counts[coll] = await db[coll].count_documents(q)

    snap_rows = await db.product_snapshots.aggregate([
        {"$match": {"store_id": {"$in": sorted(delete_ids)}}},
        {"$group": {"_id": "$store_id", "n": {"$sum": 1}}},
    ], allowDiskUse=True).to_list(length=None) if delete_ids else []
    snaps_by_store = {r["_id"]: r["n"] for r in snap_rows}
    prod_rows = await db.sku_store_coverage.aggregate([
        {"$match": {"store_id": {"$in": sorted(delete_ids)}}},
        {"$group": {"_id": "$store_id", "n": {"$sum": 1}}},
    ], allowDiskUse=True).to_list(length=None) if delete_ids else []
    products_by_store = {r["_id"]: r["n"] for r in prod_rows}

    delete_detail = sorted(
        ({"store_id": s["id"], "name": s.get("name"), "domain": s.get("domain"),
          "platform": s.get("platform"), "is_active": s.get("is_active"),
          "last_crawled_at": s.get("last_crawled_at") or "",
          "products": products_by_store.get(s["id"], 0),
          "snapshots": snaps_by_store.get(s["id"], 0)}
         for s in delete_rows),
        key=lambda r: (-r["snapshots"], r["name"] or ""))

    # store_registry.REQUIRED_STORES is re-applied by ensure_stores() on every
    # boot, so any deleted domain still listed there comes BACK (empty, without
    # its history) at the next restart. We must not edit that module here, so
    # the caller is told exactly which ones will reappear.
    from store_registry import REQUIRED_STORES as _REQUIRED_STORES
    required_domains = {normalize_store_domain(s["domain"]) for s in _REQUIRED_STORES}
    will_reappear = sorted(d for d in delete_domains if d in required_domains)

    report = {
        "dry_run": dry_run,
        "guard": {"ok": not guard_reasons, "reasons": guard_reasons,
                  "own_store_in_delete_set": own_in_delete,
                  "keep_list_unresolved": unresolved,
                  "keep_list_resolved_stores": resolved_keep_stores,
                  "keep_list_expected": STORE_CLEANUP_EXPECTED_KEEP,
                  "max_delete": STORE_CLEANUP_MAX_DELETE,
                  "confirm_count_required": len(delete_ids)},
        "live_stores_total": live_total,
        "keep_list": keep_rows,
        "delete_count": len(delete_ids),
        "delete_set": delete_detail,
        "cascade_counts": cascade_counts,
        "cascade_skipped": _STORE_CASCADE_SKIPPED,
        "warnings": ([] if not will_reappear else [
            "these deleted domains are still in store_registry.REQUIRED_STORES and "
            "ensure_stores() will re-create them (empty) on the next backend restart: "
            + ", ".join(will_reappear)]),
        "before": {
            "stores": live_total,
            "product_snapshots": await db.product_snapshots.count_documents({}),
            "product_matches": await db.product_matches.count_documents({}),
            "products": await db.products.count_documents({}),
        },
    }
    if dry_run or not delete_ids:
        return report

    # ── real run: backup FIRST (all of it), then delete ──
    # Both phases raise StoreCleanupError carrying structured detail, so a
    # failure names the collection and the reason instead of surfacing a bare
    # 500 with no way to tell how far the cascade got.
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    try:
        backups = await _store_cleanup_backup(db, cascade, ts)
        await db[f"store_cleanup_backup_{ts}_manifest"].insert_one({
            "_id": "manifest", "created_at": datetime.now(timezone.utc),
            "store_ids": sorted(delete_ids), "domains": sorted(delete_domains),
            "stores": delete_detail,
            "collections": {k: v["docs"] for k, v in backups.items()},
        })
        deleted = await _store_cleanup_delete(db, cascade, backups, ts)
    except StoreCleanupError as e:
        raise HTTPException(500, {**e.detail, "backup_timestamp": ts,
                                  "delete_count": len(delete_ids)})
    except Exception as e:
        logger.exception("[StoreCleanup] unexpected failure in the destructive path")
        raise HTTPException(500, {
            "error": "store-cleanup failed", "phase": "manifest_or_unknown",
            "exception": type(e).__name__, "message": str(e)[:400],
            "backup_timestamp": ts,
            "hint": f"check for store_cleanup_backup_{ts}_* collections before retrying",
        })

    # stop the per-store crawl jobs so the scheduler doesn't keep firing at
    # stores that no longer exist
    unregistered = 0
    for sid in delete_ids:
        try:
            unregister_crawl_job(sid)
            unregistered += 1
        except Exception:
            logger.exception("[StoreCleanup] failed to unregister crawl job %s", sid)

    # ── recompute so dashboards, rollups and the ranking drop the dead stores ──
    # The data is already gone and backed up at this point, so a recompute
    # failure must NOT 500 the whole call — it would hide a successful delete
    # and make the operator re-run a cleanup that already happened.
    recompute = {"crawl_jobs_unregistered": unregistered}
    for label, fn in (("store_metrics", lambda: recompute_all_store_metrics(db)),
                      ("dashboard_cache", lambda: maybe_recompute_dashboard_cache(db, force=True)),
                      # page caches include price-intel/store-ranking (iter38)
                      ("page_caches", lambda: maybe_recompute_page_caches(db, force=True))):
        try:
            res = await fn()
            recompute[label] = res if label == "store_metrics" else ("recomputed" if res else "skipped")
        except Exception as e:
            logger.exception("[StoreCleanup] recompute step %s failed", label)
            recompute[label] = f"ERROR: {type(e).__name__}: {str(e)[:160]}"

    # ── orphan audit: nothing may still point at a deleted store ──
    orphans, orphan_products = {}, None
    try:
        for coll, q in cascade:
            orphans[coll] = await db[coll].count_documents(q)
        # products is SKU-keyed and intentionally not cascaded; report what is
        # now unreferenced so a follow-up prune can be decided separately
        remaining_skus = set(await db.product_snapshots.distinct("sku"))
        orphan_products = 0
        async for p in db.products.find({}, {"_id": 0, "sku": 1}):
            if p.get("sku") not in remaining_skus:
                orphan_products += 1
    except Exception as e:
        logger.exception("[StoreCleanup] orphan audit failed")
        orphans["_error"] = f"{type(e).__name__}: {str(e)[:160]}"
    report["deleted_counts"] = deleted

    report["after"] = {
        "stores": await db.stores.count_documents({}),
        "product_snapshots": await db.product_snapshots.count_documents({}),
        "product_matches": await db.product_matches.count_documents({}),
        "products": await db.products.count_documents({}),
    }
    report["orphan_store_references"] = orphans
    report["orphan_products_not_deleted"] = orphan_products
    report["backups"] = backups
    report["backup_timestamp"] = ts
    report["recompute"] = recompute
    return report



@router.get("/admin/subcategory-preview")
async def subcategory_preview(samples: int = Query(20, ge=1, le=100), user=Depends(get_user)):
    """iter36 — read-only classifier audit over the LIVE catalog: distribution of
    food products across subcategories plus N sample names per bucket, so the
    classifier can be sanity-checked against real data. super_admin only."""
    if (user or {}).get("role") != "super_admin" and not is_super_admin_email((user or {}).get("email", "")):
        raise HTTPException(403, "super_admin only")
    from crawlers import _has_treat_signal
    demo_skus = _demo_seed_skus()
    dist = {k: 0 for k in FOOD_SUBCATEGORIES}
    generic = {p: 0 for p in FOOD_SUBCATEGORY_PARENTS}
    real_dist = {k: 0 for k in FOOD_SUBCATEGORIES}
    real_generic = {p: 0 for p in FOOD_SUBCATEGORY_PARENTS}
    sample_map = {k: [] for k in [*FOOD_SUBCATEGORIES, *FOOD_SUBCATEGORY_PARENTS]}
    treat_name_parents = {}
    total = demo_total = 0
    async for p in db.products.find(
        {},
        {"_id": 0, "sku": 1, "name_ar": 1, "name_en": 1, "category": 1, "subcategory": 1},
    ):
        is_demo = p.get("sku") in demo_skus
        name = " ".join(str(x) for x in (p.get("name_ar"), p.get("name_en")) if x)
        # issue-4 diagnostic: where do treat-NAMED products live today?
        if name and _has_treat_signal(name.lower()):
            treat_name_parents[p.get("category") or ""] = treat_name_parents.get(p.get("category") or "", 0) + 1
        if (p.get("category") or "") not in FOOD_SUBCATEGORY_PARENTS:
            continue
        total += 1
        if is_demo:
            demo_total += 1
        # use the stored assignment when present (post-backfill), else classify live
        sub = p.get("subcategory") if "subcategory" in p else classify_food_subcategory(
            p.get("category"), name)
        key = sub or p["category"]
        if sub:
            dist[sub] += 1
            if not is_demo:
                real_dist[sub] += 1
        else:
            generic[p["category"]] += 1
            if not is_demo:
                real_generic[p["category"]] += 1
        if len(sample_map[key]) < samples:
            sample_map[key].append({"sku": p.get("sku"), "name": p.get("name_ar") or p.get("name_en"),
                                    "assigned": key, "demo": is_demo})
    pct = {k: round(100 * v / total, 1) if total else 0 for k, v in {**dist, **generic}.items()}
    real_total = total - demo_total
    pct_real = {k: round(100 * v / real_total, 1) if real_total else 0
                for k, v in {**real_dist, **real_generic}.items()}
    return {"total_food_products": total, "demo_food_products": demo_total,
            "subcategory_counts": dist, "generic_counts": generic, "pct": pct,
            "pct_real_catalog_only": pct_real,
            "treat_name_parent_distribution": treat_name_parents,
            "classifier_version": CLASSIFIER_VERSION,
            "samples": sample_map}


@router.get("/admin/recent-snapshots")
async def admin_recent_snapshots(limit: int = Query(200, ge=1, le=1000), user=Depends(get_user)):
    """Read-only admin helper: latest N snapshots joined with store platform.

    Used for spot-checking the impact of the Feb 2026 stock-normalize micro-fixes.
    """
    stores = {s["id"]: s async for s in db.stores.find({}, {"_id": 0, "id": 1, "platform": 1, "name": 1, "is_own_store": 1})}

    snaps = await db.product_snapshots.find(
        {},
        {
            "_id": 0,
            "sku": 1, "store_id": 1, "store_name": 1,
            "price": 1, "qty_available": 1, "in_stock": 1,
            "product_url": 1, "crawled_at": 1, "source_tier": 1,
        },
    ).sort("crawled_at", -1).limit(limit).to_list(limit)

    for s in snaps:
        meta = stores.get(s.get("store_id")) or {}
        s["platform"] = meta.get("platform", "")
        s["is_own_store"] = bool(meta.get("is_own_store", False))
        ca = s.get("crawled_at")
        if hasattr(ca, "isoformat"):
            s["crawled_at"] = ca.isoformat()

    return {"count": len(snaps), "snapshots": snaps}


@router.get("/admin/snapshot-horizon")
async def snapshot_horizon(days: int = Query(90), user=Depends(get_user)):
    """Read-only diagnostic for the '30D and 90D look identical' symptom.

    Answers two questions:
      1. Does snapshot history genuinely stop N days back? → per-day counts.
      2. Are older snapshots invisible because crawled_at was stored as an ISO
         STRING in an earlier era? (A BSON string never matches a `$gte:
         <datetime>` filter, silently excluding those rows from every window.)
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # BSON type split — the smoking gun if strings exist.
    date_typed = await db.product_snapshots.count_documents({"crawled_at": {"$type": "date"}})
    string_typed = await db.product_snapshots.count_documents({"crawled_at": {"$type": "string"}})
    oldest_date = await db.product_snapshots.find_one(
        {"crawled_at": {"$type": "date"}}, {"_id": 0, "crawled_at": 1}, sort=[("crawled_at", 1)])
    newest_date = await db.product_snapshots.find_one(
        {"crawled_at": {"$type": "date"}}, {"_id": 0, "crawled_at": 1}, sort=[("crawled_at", -1)])
    string_sample = await db.product_snapshots.find_one(
        {"crawled_at": {"$type": "string"}}, {"_id": 0, "crawled_at": 1, "store_name": 1, "sku": 1})

    # Per-day histogram over date-typed snapshots, split own vs competitors.
    own_store_doc = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_id = own_store_doc.get("id") if own_store_doc else None
    per_day = {}
    try:
        pipeline = [
            {"$match": {"crawled_at": {"$gte": since, "$type": "date"}}},
            {"$group": {
                "_id": {"day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$crawled_at"}},
                        "own": {"$eq": ["$store_id", own_id]}},
                "n": {"$sum": 1},
            }},
        ]
        async for g in db.product_snapshots.aggregate(pipeline, allowDiskUse=True):
            day = g["_id"]["day"]
            bucket = per_day.setdefault(day, {"own": 0, "competitors": 0})
            bucket["own" if g["_id"]["own"] else "competitors"] += g["n"]
    except Exception as e:
        # Reduced-aggregation backends (FerretDB) may not support $dateToString;
        # the type-split above still answers the headline question.
        per_day = {"error": f"histogram unavailable on this backend: {str(e)[:200]}"}

    return {
        "checked_at": now.isoformat(),
        "window_days": days,
        "crawled_at_type_split": {
            "date_typed": date_typed,
            "string_typed": string_typed,
            "verdict": (
                "STRING-TYPED SNAPSHOTS EXIST — these are permanently invisible to every "
                "dashboard window filter and explain a hard history horizon."
                if string_typed > 0 else
                "All crawled_at values are proper dates — identical 30D/90D numbers mean "
                "history genuinely contains no qualifying deltas beyond the horizon."
            ),
        },
        "oldest_date_typed": (oldest_date or {}).get("crawled_at"),
        "newest_date_typed": (newest_date or {}).get("crawled_at"),
        "string_typed_sample": string_sample,
        "per_day_counts": per_day,
    }


@router.post("/admin/cleanup-own-snapshots")
async def cleanup_own_snapshots(dry_run: bool = Query(False, description="If true, only count without deleting"), user=Depends(get_user)):
    """One-time cleanup of legacy product_snapshots from the user's own store.

    These snapshots accumulated before `is_own_store` was set on the store and don't
    leak into competitor views (filters block them) but bloat the collection. This
    endpoint lets the admin purge them safely.

    Usage:
        POST /api/admin/cleanup-own-snapshots             → delete and return counts
        POST /api/admin/cleanup-own-snapshots?dry_run=true → just count
    """
    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1, "name": 1, "domain": 1})
    if not own_store:
        raise HTTPException(400, "No store is flagged as is_own_store=True. Aborting cleanup.")

    own_store_id = own_store["id"]
    count = await db.product_snapshots.count_documents({"store_id": own_store_id})

    if dry_run or count == 0:
        return {
            "dry_run": dry_run,
            "own_store": {"id": own_store_id, "name": own_store["name"], "domain": own_store.get("domain")},
            "snapshots_found": count,
            "deleted": 0,
            "message": "Dry run — no rows deleted" if dry_run else "Nothing to clean up",
        }

    result = await db.product_snapshots.delete_many({"store_id": own_store_id})
    logger.info(f"[Admin] Cleaned up {result.deleted_count} own-store snapshots from {own_store['name']}")
    return {
        "dry_run": False,
        "own_store": {"id": own_store_id, "name": own_store["name"], "domain": own_store.get("domain")},
        "snapshots_found": count,
        "deleted": result.deleted_count,
        "message": f"Removed {result.deleted_count} legacy own-store snapshots from {own_store['name']}",
    }


@router.post("/crawler/ingest")
async def crawler_ingest(request: Request, payload: IngestPayload):
    """Secure bulk ingest endpoint for external crawler running on Saudi IP."""
    # Bearer token auth
    auth_header = request.headers.get("authorization", "")
    if not CRAWLER_TOKEN:
        raise HTTPException(500, "CRAWLER_TOKEN not configured")
    if not auth_header.startswith("Bearer ") or auth_header[7:] != CRAWLER_TOKEN:
        raise HTTPException(401, "Invalid or missing crawler token")

    try:
        # Upsert by domain (unique index). Handles both:
        #  - Brand-new store: insert full record
        #  - Existing store (possibly with different id): leave as-is, do NOT overwrite
        await db.stores.update_one(
            {"domain": payload.domain},
            {"$setOnInsert": {
                "id": payload.store_id,
                "name": payload.store_name,
                "domain": payload.domain,
                "platform": payload.platform,
                "base_url": f"https://{payload.domain}",
                "is_active": True,
                "priority": 1,
                "crawl_frequency_hrs": 12,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        # Re-read canonical store_id from DB (source of truth after upsert)
        store_doc = await db.stores.find_one({"domain": payload.domain}, {"_id": 0, "id": 1})
        canonical_store_id = store_doc["id"] if store_doc else payload.store_id

        now = datetime.now(timezone.utc)
        inserted = 0
        updated = 0
        skipped = 0
        errors = []  # keep first 5 row-level error samples for debugging

        for idx, raw in enumerate(payload.products):
            try:
                if not isinstance(raw, dict):
                    skipped += 1
                    if len(errors) < 5:
                        errors.append({"index": idx, "error": f"row is {type(raw).__name__}, expected object"})
                    continue

                sku = str(raw.get("sku") or "").strip()
                if not sku:
                    skipped += 1
                    continue

                name_ar = str(raw.get("name_ar") or "").strip()
                name_en = str(raw.get("name_en") or "").strip()
                barcode = str(raw.get("barcode") or "").strip()
                price = _coerce_num(raw.get("price"), 0)
                sale_price = _coerce_num(raw.get("sale_price"), 0)
                quantity = _coerce_int(raw.get("quantity"), 0)
                sold_count = _coerce_int(raw.get("sold_count"), 0)
                in_stock_raw = raw.get("in_stock")
                in_stock = bool(in_stock_raw) if in_stock_raw is not None else (quantity > 0)

                # Storefront product URL — accept full URL, path, or slug
                raw_url = str(raw.get("product_url") or raw.get("url") or raw.get("permalink") or "").strip()
                product_url = ""
                if raw_url:
                    if raw_url.startswith("http://") or raw_url.startswith("https://"):
                        product_url = raw_url
                    elif raw_url.startswith("/"):
                        product_url = f"https://{payload.domain}{raw_url}"
                    else:
                        product_url = f"https://{payload.domain}/products/{raw_url}"

                if price <= 0:
                    skipped += 1
                    continue

                original_price = price
                effective_price = price
                if 0 < sale_price < price:
                    effective_price = sale_price

                disc_pct = round((1 - effective_price / original_price) * 100) if original_price > effective_price > 0 else 0

                existing = await db.products.find_one({"sku": sku}, {"_id": 0})
                if not existing:
                    pid = str(uuid.uuid4())
                    # iter40 — classify at insert (this path used to write empty
                    # category/animal/brand: the source of the 34 ""-category docs)
                    _cls_name = name_ar or name_en or ""
                    _cat = guess_category(_cls_name) if _cls_name else ""
                    await db.products.insert_one({
                        "id": pid, "sku": sku,
                        "name_ar": name_ar, "name_en": name_en,
                        "barcode": barcode,
                        "brand": extract_brand(_cls_name) if _cls_name else "",
                        "category": _cat,
                        "subcategory": classify_food_subcategory(_cat, name_ar, name_en),
                        "animal_type": guess_animal(_cls_name) if _cls_name else "",
                        "weight_kg": extract_weight(_cls_name) if _cls_name else 0,
                        "image_url": "",
                        "product_url": product_url,
                        "first_seen_at": now.isoformat(),
                    })
                    inserted += 1
                else:
                    pid = existing["id"]
                    update_fields = {}
                    if name_ar and not existing.get("name_ar"):
                        update_fields["name_ar"] = name_ar
                    if name_en and not existing.get("name_en"):
                        update_fields["name_en"] = name_en
                    if barcode and not existing.get("barcode"):
                        update_fields["barcode"] = barcode
                    if product_url and not existing.get("product_url"):
                        update_fields["product_url"] = product_url
                    if update_fields:
                        await db.products.update_one({"id": pid}, {"$set": update_fields})
                    updated += 1

                await db.product_snapshots.insert_one({
                    "id": str(uuid.uuid4()),
                    "product_id": pid,
                    "store_id": canonical_store_id,
                    "store_name": payload.store_name,
                    "sku": sku,
                    "price": round(effective_price, 2),
                    "original_price": round(original_price, 2),
                    # iter35 — persist the sale price for capture observability
                    "sale_price": round(sale_price, 2) if 0 < sale_price < price else None,
                    "discount_pct": max(0, disc_pct),
                    "in_stock": in_stock,
                    "product_url": product_url,
                    "qty_available": max(0, quantity),
                    "sold_count": sold_count,
                    "source_tier": 0,
                    "confidence_score": 99,
                    "crawled_at": now,
                })
            except Exception as row_err:
                skipped += 1
                logger.exception("ingest row %s failed: %s", idx, row_err)
                if len(errors) < 5:
                    errors.append({"index": idx, "sku": str(raw.get("sku"))[:50] if isinstance(raw, dict) else None, "error": f"{type(row_err).__name__}: {row_err}"})

        await db.stores.update_one({"id": canonical_store_id}, {"$set": {
            "last_crawled_at": now.isoformat(),
            "last_crawl_tier": 0,
            "last_crawl_status": "success",
            "last_crawl_products": inserted + updated,
            "last_crawl_endpoint": "external_ingest",
        }})

        # ── Own-store sync (Feb 2026) ───────────────────────
        # If the ingested domain is flagged as the user's own store, also mirror
        # prices/qty into db.my_products (barcode → SKU match, never overwrite catalog metadata).
        own_store_synced = 0
        own_store_not_found = 0
        own_check = await db.stores.find_one(
            {"domain": payload.domain, "is_own_store": True},
            {"_id": 0, "id": 1},
        )
        if own_check:
            # Build quick lookup tables from my_products
            my_by_sku, my_by_barcode = {}, {}
            async for mp in db.my_products.find({}, {"_id": 0, "sku": 1, "barcode": 1}):
                s = str(mp.get("sku") or "").strip()
                b = str(mp.get("barcode") or "").strip()
                if s:
                    my_by_sku[s] = mp["sku"]
                if b and b.isdigit() and 8 <= len(b) <= 14:
                    my_by_barcode[b] = mp["sku"]

            sync_ts = now.isoformat()
            for raw in payload.products:
                if not isinstance(raw, dict):
                    continue
                c_sku = str(raw.get("sku") or "").strip()
                c_barcode = str(raw.get("barcode") or "").strip()
                # Level 1: barcode (8-14 digit EAN)
                target_sku = None
                if c_barcode and c_barcode.isdigit() and 8 <= len(c_barcode) <= 14 and c_barcode in my_by_barcode:
                    target_sku = my_by_barcode[c_barcode]
                # Level 2: exact SKU
                elif c_sku and c_sku in my_by_sku:
                    target_sku = my_by_sku[c_sku]
                # Numeric-SKU-as-barcode fallback
                elif c_sku and c_sku.isdigit() and 8 <= len(c_sku) <= 14 and c_sku in my_by_barcode:
                    target_sku = my_by_barcode[c_sku]

                if not target_sku:
                    own_store_not_found += 1
                    continue

                price_v = _coerce_num(raw.get("price"), 0)
                sale_v = _coerce_num(raw.get("sale_price"), 0)
                qty_v = _coerce_int(raw.get("quantity"), 0)
                in_stock_raw = raw.get("in_stock")
                in_stock_v = bool(in_stock_raw) if in_stock_raw is not None else (qty_v > 0)
                await db.my_products.update_one(
                    {"sku": target_sku},
                    {"$set": {
                        "price": round(price_v, 2),
                        "sale_price": round(sale_v, 2) if 0 < sale_v < price_v else None,
                        "quantity": qty_v,
                        "in_stock": in_stock_v,
                        "last_synced_at": sync_ts,
                        "sync_source": "crawler_ingest",
                    }},
                )
                own_store_synced += 1

        # iter30 — rebuild this store's precomputed metric rollups + coverage from
        # the just-ingested snapshots so the summary KPIs stay fresh. Bounded
        # per-store pass; never fails the ingest.
        try:
            await _recompute_store_metrics(db, canonical_store_id)
        except Exception:
            logger.exception("[Metrics] per-store rebuild failed after ingest of %s", canonical_store_id)

        return {
            "received": len(payload.products),
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "token_valid": True,
            "store_id": canonical_store_id,
            "crawled_at": now.isoformat(),
            "own_store_synced": own_store_synced,
            "own_store_not_found": own_store_not_found,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("crawler_ingest failed for store=%s: %s", payload.store_id, e)
        raise HTTPException(500, f"ingest_failed: {type(e).__name__}: {e}")


@router.get("/stores/{store_id}/raw-products")
async def get_raw_products(store_id: str, page: int = 1, limit: int = 50, user=Depends(get_user)):
    """Show raw crawled products for a store — for data quality verification."""
    store = await db.stores.find_one({"id": store_id}, {"_id": 0, "id": 1, "name": 1})
    if not store:
        raise HTTPException(404, "Store not found")
    pipeline = [
        {"$match": {"store_id": store_id}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {
            "_id": "$sku",
            "sku": {"$first": "$sku"},
            "price": {"$first": "$price"},
            "original_price": {"$first": "$original_price"},
            "in_stock": {"$first": "$in_stock"},
            "qty_available": {"$first": "$qty_available"},
            "crawled_at": {"$first": "$crawled_at"},
            "source_tier": {"$first": "$source_tier"},
        }},
        {"$sort": {"price": 1}},
        {"$skip": (page - 1) * limit},
        {"$limit": limit},
    ]
    items = await db.product_snapshots.aggregate(pipeline).to_list(limit)
    # Enrich with product names
    for item in items:
        prod = await db.products.find_one({"sku": item["sku"]}, {"_id": 0, "name_ar": 1, "name_en": 1, "barcode": 1})
        if prod:
            item["name_ar"] = prod.get("name_ar", "")
            item["name_en"] = prod.get("name_en", "")
            item["barcode"] = prod.get("barcode", "")
        item.pop("_id", None)
        if hasattr(item.get("crawled_at"), "isoformat"):
            item["crawled_at"] = item["crawled_at"].isoformat()

    total_pipeline = [
        {"$match": {"store_id": store_id}},
        {"$group": {"_id": "$sku"}},
        {"$count": "total"},
    ]
    total_result = await db.product_snapshots.aggregate(total_pipeline).to_list(1)
    total = total_result[0]["total"] if total_result else 0

    return {"store": store, "items": items, "total": total, "page": page}


# ── MySKUwatch Baseline Import ───────────────────────────────
@router.post("/baseline/import")
async def import_baseline(user=Depends(get_user)):
    """Import MySKUwatch baseline data from pre-downloaded Excel file."""
    import openpyxl

    filepath = "/tmp/daleel_baseline.xlsx"
    try:
        wb = openpyxl.load_workbook(filepath, read_only=True)
    except Exception as exc:
        raise HTTPException(400, f"Cannot open baseline file: {exc}")

    TAGS = {
        "data_source": "myskuwatch_baseline",
        "baseline_period": "last_14_days",
        "import_date": "2026-04-17",
        "expires": "2026-05-17",
    }
    now = datetime.now(timezone.utc)
    results = {}

    # ── Step 2A: My_Store_Baseline Section A → market_intelligence_baseline ──
    ws = wb['My_Store_Baseline']
    rows = list(ws.iter_rows(values_only=True))
    baseline_doc = {
        "store_domain": "pets-houses.com",
        "total_products": 1292,
        "est_units_sold": 1458,
        "est_revenue_sar": 42489,
        "on_discount": 272,
        "market_rank": 12,
        "market_total_stores": 13,
        "median_price_spread_pct": 41.9,
        "market_price_drops": 442,
        "imported_at": now.isoformat(),
        **TAGS,
    }
    await db.market_intelligence_baseline.update_one(
        {"store_domain": "pets-houses.com", "data_source": "myskuwatch_baseline"},
        {"$set": baseline_doc}, upsert=True
    )
    results["baseline_stats"] = 1

    # ── Step 2B: My_Store_Baseline Section B → product_baseline_stats ──
    product_stats = []
    for r in rows[14:]:  # Data rows after Section B header
        if not r[0] or not str(r[0]).strip().isdigit():
            continue
        vs_lowest = r[8]
        if isinstance(vs_lowest, str):
            vs_lowest = float(vs_lowest.replace('%', '').replace('+', '')) if vs_lowest.replace('%','').replace('+','').replace('-','').replace('.','').isdigit() else 0
        vs_median = r[9]
        if isinstance(vs_median, str):
            vs_median = float(vs_median.replace('%', '').replace('+', '')) if vs_median.replace('%','').replace('+','').replace('-','').replace('.','').isdigit() else 0
        market_share = r[7]
        if isinstance(market_share, str):
            market_share = float(market_share.replace('%', '')) if market_share.replace('%','').replace('.','').isdigit() else 0

        doc = {
            "barcode": str(r[1] or "").strip(),
            "name_ar": str(r[2] or "").strip(),
            "my_price_sar": float(r[3] or 0),
            "est_units_sold": int(r[4] or 0),
            "est_revenue_sar": float(r[5] or 0),
            "est_market_size_sar": float(r[6] or 0),
            "est_market_share_pct": float(market_share) if isinstance(market_share, (int, float)) else market_share,
            "vs_lowest_pct": float(vs_lowest) if isinstance(vs_lowest, (int, float)) else vs_lowest,
            "vs_median_pct": float(vs_median) if isinstance(vs_median, (int, float)) else vs_median,
            "sellers_count": int(r[10] or 0),
            "rank": int(r[0]),
            "imported_at": now.isoformat(),
            **TAGS,
        }
        await db.product_baseline_stats.update_one(
            {"barcode": doc["barcode"], "data_source": "myskuwatch_baseline"},
            {"$set": doc}, upsert=True
        )
        product_stats.append(doc)
    results["product_stats"] = len(product_stats)

    # ── Step 3: Market_Leaderboard → market_leaderboard ──
    ws = wb['Market_Leaderboard']
    rows = list(ws.iter_rows(values_only=True))
    leaderboard = []
    for r in rows[2:]:
        if not r[0] or not (isinstance(r[0], (int, float)) or str(r[0]).strip().isdigit()):
            continue
        entry = {
            "rank": int(r[0]),
            "store_domain": str(r[1] or "").strip(),
            "relative_size": str(r[2] or "").strip(),
            "notes": str(r[3] or "").strip(),
            "is_my_store": str(r[4] or "").strip().upper() == "YES",
            "snapshot_date": "2026-04-17",
            "imported_at": now.isoformat(),
            **TAGS,
        }
        leaderboard.append(entry)
    await db.market_leaderboard.delete_many({"data_source": "myskuwatch_baseline"})
    if leaderboard:
        await db.market_leaderboard.insert_many(leaderboard)
    results["leaderboard_entries"] = len(leaderboard)

    # ── Step 4: Catalog_Gaps → market_opportunities ──
    ws = wb['Catalog_Gaps']
    rows = list(ws.iter_rows(values_only=True))
    gaps = []
    for r in rows[2:]:
        if not r[0] or not r[1]:
            continue
        doc = {
            "priority": str(r[0] or "").strip(),
            "barcode": str(r[1] or "").strip(),
            "product_name": str(r[2] or "").strip(),
            "est_units_sold": int(r[3] or 0),
            "est_revenue_sar": float(r[4] or 0),
            "sellers_count": int(r[5] or 0),
            "avg_price_sar": float(r[6] or 0),
            "action": str(r[7] or "").strip(),
            "imported_at": now.isoformat(),
            **TAGS,
        }
        gaps.append(doc)
    await db.market_opportunities.delete_many({"data_source": "myskuwatch_baseline"})
    if gaps:
        await db.market_opportunities.insert_many(gaps)
    results["catalog_gaps"] = len(gaps)

    # ── Step 5: Price_Comparisons → product_snapshots (source_tier=5, confidence=80) ──
    ws = wb['Price_Comparisons']
    rows = list(ws.iter_rows(values_only=True))
    comp_count = 0
    for r in rows[2:]:
        if not r[0]:
            continue
        barcode = str(r[0] or "").strip()
        product_name = str(r[1] or "").strip()
        my_store = str(r[2] or "").strip()
        my_price = float(r[3] or 0) if r[3] else 0
        my_status = str(r[4] or "").strip()
        comp_store = str(r[5] or "").strip()
        comp_price = float(r[6] or 0) if r[6] else 0
        comp_status = str(r[7] or "").strip()
        diff_pct_str = str(r[8] or "0%").replace('%', '').replace('+', '').strip()
        position = str(r[9] or "").strip()

        if not comp_store or comp_price <= 0:
            continue

        # Find store_id from domain
        comp_domain = comp_store
        store_doc = await db.stores.find_one({"$or": [{"domain": comp_domain}, {"name": comp_domain}]}, {"_id": 0, "id": 1, "name": 1})
        store_id = store_doc["id"] if store_doc else comp_store
        store_name = store_doc["name"] if store_doc else comp_store

        await db.product_snapshots.insert_one({
            "id": str(uuid.uuid4()),
            "product_id": "",
            "store_id": store_id,
            "store_name": store_name,
            "sku": barcode,
            "price": round(comp_price, 2),
            "original_price": round(comp_price, 2),
            "discount_pct": 0,
            "in_stock": comp_status.lower() == "in stock",
            "qty_available": 0,
            "source_tier": 5,
            "confidence_score": 80,
            "crawled_at": now,
            **TAGS,
        })
        comp_count += 1
    results["price_comparisons"] = comp_count

    wb.close()
    results["status"] = "complete"
    results["tags"] = TAGS
    # iter30 — this manual baseline import writes competitor snapshots across many
    # stores; rebuild all metric rollups + coverage and refresh caches so the
    # summary KPIs reflect the import. Rare/manual path, so a full rebuild is fine.
    try:
        await recompute_all_store_metrics(db)
        await maybe_recompute_page_caches(db, force=True)
    except Exception:
        logger.exception("[Metrics] rebuild after baseline import failed")
    return results


@router.get("/baseline/leaderboard")
async def get_leaderboard(user=Depends(get_user)):
    items = await db.market_leaderboard.find({}, {"_id": 0}).sort("rank", 1).to_list(20)
    baseline = await db.market_intelligence_baseline.find_one(
        {"store_domain": "pets-houses.com"}, {"_id": 0}
    )
    return {"leaderboard": items, "my_store_baseline": baseline}


@router.get("/baseline/catalog-gaps")
async def get_catalog_gaps(user=Depends(get_user)):
    items = await db.market_opportunities.find({}, {"_id": 0}).sort("est_revenue_sar", -1).to_list(50)
    return items


@router.get("/baseline/product-stats")
async def get_product_stats(user=Depends(get_user)):
    items = await db.product_baseline_stats.find({}, {"_id": 0}).sort("est_revenue_sar", -1).to_list(50)
    return items


# ── Root ────────────────────────────────────────────────────
@router.get("/")
async def root():
    return {"message": "Daleel API — دليل"}

# ── App Setup ───────────────────────────────────────────────

# ── iter26 cache-serving endpoints (Insights + Price Intel) ─────────────────
# Bodies are byte-identical to the pre-cache endpoints; cache metadata rides in
# X-Cache-* response headers (see _apply_cache_headers). The default window
# views (7/14/30/90D, unfiltered) are served from db.dashboard_cache; anything
# narrower (store_id filter, date range, search, non-default sort, non-standard
# window) stays live via the same compute helper.
_INSIGHTS_STD = DASHBOARD_CACHE_STD_WINDOWS


@router.get("/insights/summary")
async def insights_summary(days: int = Query(30), response: Response = None, user=Depends(get_user)):
    body, meta = await _serve_page_cache(db, "insights/summary", days,
                                         lambda: _insights_summary_compute(db, days), days in _INSIGHTS_STD)
    _apply_cache_headers(response, meta)
    return body


@router.get("/insights/leaderboard")
async def insights_leaderboard(days: int = Query(30), response: Response = None, user=Depends(get_user)):
    body, meta = await _serve_page_cache(db, "insights/leaderboard", days,
                                         lambda: _insights_leaderboard_compute(db, days), days in _INSIGHTS_STD)
    _apply_cache_headers(response, meta)
    return body


@router.get("/insights/top-sellers")
async def insights_top_sellers(days: int = Query(30), store_id: Optional[str] = Query(None), response: Response = None, user=Depends(get_user)):
    body, meta = await _serve_page_cache(db, "insights/top-sellers", days,
                                         lambda: _insights_top_sellers_compute(db, days, store_id),
                                         store_id is None and days in _INSIGHTS_STD)
    _apply_cache_headers(response, meta)
    return body


@router.get("/insights/trending")
async def insights_trending(days: int = Query(30), response: Response = None, user=Depends(get_user)):
    body, meta = await _serve_page_cache(db, "insights/trending", days,
                                         lambda: _insights_trending_compute(db, days), days in _INSIGHTS_STD)
    _apply_cache_headers(response, meta)
    return body


@router.get("/insights/gaps")
async def insights_gaps(days: int = Query(30), response: Response = None, user=Depends(get_user)):
    body, meta = await _serve_page_cache(db, "insights/gaps", days,
                                         lambda: _insights_gaps_compute(db, days), days in _INSIGHTS_STD)
    _apply_cache_headers(response, meta)
    return body


@router.get("/insights/price-wars")
async def insights_price_wars(days: int = Query(30), response: Response = None, user=Depends(get_user)):
    body, meta = await _serve_page_cache(db, "insights/price-wars", days,
                                         lambda: _insights_price_wars_compute(db, days), days in _INSIGHTS_STD)
    _apply_cache_headers(response, meta)
    return body


@router.get("/insights/restock-opportunities")
async def insights_restock(days: int = Query(30), response: Response = None, user=Depends(get_user)):
    body, meta = await _serve_page_cache(db, "insights/restock-opportunities", days,
                                         lambda: _insights_restock_compute(db, days), days in _INSIGHTS_STD)
    _apply_cache_headers(response, meta)
    return body


@router.get("/insights/sales")
async def insights_sales(days: int = Query(30),
                         date_from: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
                         date_to: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
                         search: Optional[str] = Query(None, description="Filter by product name, SKU or brand"),
                         sort: str = Query("revenue_desc", description="sales_desc|sales_asc|revenue_desc|revenue_asc"),
                         response: Response = None, user=Depends(get_user)):
    # Normalize unset params to plain values. Over HTTP FastAPI already resolves
    # these; this makes in-process calls (tests, internal callers) robust — when
    # called without these kwargs the defaults are Query FieldInfo objects
    # (truthy), which would wrongly flip `cacheable` off and then reach
    # my_products' fromisoformat(). Same class as the iter25 export_csv fix.
    date_from = date_from if isinstance(date_from, str) else None
    date_to = date_to if isinstance(date_to, str) else None
    search = search if isinstance(search, str) else None
    sort = sort if isinstance(sort, str) else "revenue_desc"
    cacheable = (not date_from and not date_to and not search and sort == "revenue_desc" and days in _INSIGHTS_STD)
    body, meta = await _serve_page_cache(db, "insights/sales", days,
                                         lambda: _insights_sales_compute(db, days, date_from, date_to, search, sort, user),
                                         cacheable)
    _apply_cache_headers(response, meta)
    return body


@router.get("/price-intel/dashboard")
async def price_intel_dashboard(response: Response = None, user=Depends(get_user)):
    body, meta = await _serve_page_cache(db, "price-intel/dashboard", None,
                                         lambda: _price_intel_dashboard_compute(db), True)
    _apply_cache_headers(response, meta)
    return body


@router.get("/price-intel/store-ranking")
async def price_intel_store_ranking(response: Response = None, user=Depends(get_user)):
    """iter38 — live Market Strength ranking (fixed 30d). Served from the page
    cache; recomputed on the same post-crawl/sync hooks as every other spec."""
    body, meta = await _serve_page_cache(db, "price-intel/store-ranking", None,
                                         lambda: _store_ranking_compute(db), True)
    _apply_cache_headers(response, meta)
    return body


@router.get("/admin/store-ranking-preview")
async def store_ranking_preview(user=Depends(get_user)):
    """iter38/40 — read-only, cache-bypassing preview of the live ranking plus
    validation diagnostics: per-store platform audit (tag vs the data signals it
    actually produces), own-orders ledger debug, and per-store shared-product
    percentile histograms (the Caty-#1 sanity check). super_admin only."""
    if (user or {}).get("role") != "super_admin" and not is_super_admin_email((user or {}).get("email", "")):
        raise HTTPException(403, "super_admin only")
    out = await _store_ranking_compute(db)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=_RANKING_WINDOW_DAYS)

    # ── platform audit: tag vs crawler behaviour vs data signals ──
    stores_docs = {s["id"]: s async for s in db.stores.find(
        {}, {"_id": 0, "id": 1, "platform": 1, "last_crawl_endpoint": 1,
             "last_crawl_tier": 1, "last_crawl_status": 1, "last_crawled_at": 1})}
    audit = []
    for r in out["stores"]:
        sd = stores_docs.get(r["store_id"], {})
        has_signals = r["revenue_status"] in ("computed", "ledger", "accumulating")
        audit.append({
            "store_id": r["store_id"], "name": r["name"],
            "platform_tag": r["platform"],
            "last_crawl_endpoint": sd.get("last_crawl_endpoint"),
            "last_crawl_tier": sd.get("last_crawl_tier"),
            "last_crawl_status": sd.get("last_crawl_status"),
            "last_crawled_at": sd.get("last_crawled_at"),
            "produces_sales_signals": has_signals,
            # a "salla" tag with computed revenue means qty-depletion signals
            # exist — possible (Salla exposes quantity) but worth eyeballing;
            # flag so tag/data mismatches like Mowkly can't hide.
            "flag": "salla_tag_with_computed_revenue"
                    if (r["platform"] == "salla" and r["revenue_status"] == "computed") else None,
        })

    # ── own-orders ledger debug (issue: ranking said accumulating while
    # my-products showed SAR — both now read _own_orders_aggregate; this shows
    # exactly what that helper sees) ──
    own_docs_n = await db.own_store_orders.count_documents({"created_at": {"$gte": since}})
    newest = await db.own_store_orders.find_one({}, {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
    own_agg = await _own_orders_aggregate(db, since)
    orders_debug = {
        "docs_in_window": own_docs_n,
        "newest_order_at": (newest or {}).get("created_at"),
        "helper_result": {"revenue": round(own_agg["revenue"], 2), "orders": own_agg["orders_count"]} if own_agg else None,
    }

    # ── per-store shared-product percentile histograms + price ratio ──
    prices_by_sku = {}
    async for c in db.sku_store_coverage.find(
            {"last_priced_at": {"$gte": since}},
            {"_id": 0, "sku": 1, "store_id": 1, "last_priced_price": 1}).batch_size(2000):
        prices_by_sku.setdefault(c["sku"], []).append((c["last_priced_price"], c["store_id"]))
    hist = {}
    ratios = {}
    for sku, sellers in prices_by_sku.items():
        if len(sellers) < 2:
            continue
        prices = sorted(p for p, _s in sellers)
        n = len(sellers)
        med = statistics.median(prices)
        for p, sid in sellers:
            frac = sum(1 for q in prices if q < p) / (n - 1)
            b = hist.setdefault(sid, [0, 0, 0, 0])
            b[min(3, int(frac * 4))] += 1
            if med > 0:
                ratios.setdefault(sid, []).append(p / med)
    percentile_histograms = {
        sid: {"buckets_0_25_50_75": b, "shared": sum(b),
              "median_price_ratio_vs_market": round(statistics.median(ratios[sid]), 3) if ratios.get(sid) else None}
        for sid, b in hist.items()
    }
    out["diagnostics"] = {"platform_audit": audit, "own_orders": orders_debug,
                         "percentile_histograms": percentile_histograms}
    return out


# Register cache specs for background recompute. insights/sales gets a synthetic
# super_admin user (my_products only uses it for the auth dependency, which is
# bypassed for in-process calls).
_CACHE_USER = {"id": "cache", "email": "cache@internal", "role": "super_admin"}
_WINDOW_CACHE_SPECS.extend([
    ("insights/summary", lambda db, d: _insights_summary_compute(db, d)),
    ("insights/leaderboard", lambda db, d: _insights_leaderboard_compute(db, d)),
    ("insights/top-sellers", lambda db, d: _insights_top_sellers_compute(db, d, None)),
    ("insights/trending", lambda db, d: _insights_trending_compute(db, d)),
    ("insights/gaps", lambda db, d: _insights_gaps_compute(db, d)),
    ("insights/price-wars", lambda db, d: _insights_price_wars_compute(db, d)),
    ("insights/restock-opportunities", lambda db, d: _insights_restock_compute(db, d)),
    ("insights/sales", lambda db, d: _insights_sales_compute(db, d, None, None, None, "revenue_desc", _CACHE_USER)),
])
_SINGLE_CACHE_SPECS.extend([
    ("price-intel/dashboard", lambda db: _price_intel_dashboard_compute(db)),
    # iter38 — live store ranking, recomputed on the same post-crawl hooks
    ("price-intel/store-ranking", lambda db: _store_ranking_compute(db)),
])


app.include_router(router)

cors_origins = os.environ.get('CORS_ORIGINS', '*')
if cors_origins == '*':
    cors_origins_list = ["*"]
    allow_creds = False
else:
    cors_origins_list = [o.strip() for o in cors_origins.split(',')]
    allow_creds = True

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=allow_creds,
    allow_origins=cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await seed_database()
    await seed_super_admin()
    await ensure_stores()
    # Idempotent indexes (safe to run on every startup; no-op if already present)
    try:
        await db.product_snapshots.create_index("crawled_at")
        await db.product_snapshots.create_index([("sku", 1), ("crawled_at", -1)])
        await db.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)])
        # Perf sprint Feb 2026 — leading-by-date for time-range aggregations
        await db.product_snapshots.create_index([("crawled_at", -1), ("store_id", 1)])
        await db.product_snapshots.create_index([("crawled_at", -1), ("sku", 1)])
        await db.product_snapshots.create_index([("crawled_at", -1), ("confidence_score", 1)])
        # iter22 (Jul 2026) — matcher lookup fix: index-backed sort for
        # _build_competitor_lookups at production scale.
        await db.product_snapshots.create_index([("store_id", 1), ("sku", 1), ("crawled_at", -1)])
        await db.proxy_usage.create_index("crawled_at")
        await db.products.create_index("sku", unique=True)
        await db.products.create_index("category")
        # Real orders ledger (Feb 2026 My Revenue rework)
        await db.own_store_orders.create_index("order_id", unique=True)
        await db.own_store_orders.create_index([("created_at", -1)])
        # Dashboard cache (iter25) — one doc per standard window, keyed uniquely.
        await db.dashboard_cache.create_index("key", unique=True)
        # iter30 — write-time metric rollups. Tiny collections read on the summary
        # path instead of scanning product_snapshots.
        await db.metric_daily_rollups.create_index("date")
        await db.metric_daily_rollups.create_index("store_id")
        await db.sku_store_coverage.create_index("last_seen_at")
        await db.sku_store_coverage.create_index("store_id")
        await db.sku_store_coverage.create_index("sku")
        # iter33 — gaps / price-wars filter on the latest price>0 crawl
        await db.sku_store_coverage.create_index("last_priced_at")
        # iter34 — daily sales facts (leaderboard / top-sellers / trending)
        await db.sku_sales_daily.create_index("date")
        await db.sku_sales_daily.create_index([("store_id", 1), ("date", 1)])
        await db.sku_store_coverage.create_index("last_sold_pos_at")
        await db.sku_store_coverage.create_index("last_usable_qty_at")
    except Exception as e:
        logger.warning(f"Index creation skipped: {e}")
    # Safety net (Feb 2026): ensure pets-houses.com is always flagged as the user's own store.
    try:
        own_check = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
        if not own_check:
            res = await db.stores.update_one(
                {"domain": "pets-houses.com"},
                {"$set": {"is_own_store": True}},
            )
            if res.modified_count:
                logger.info("Auto-set is_own_store=True on pets-houses.com (no own store was flagged)")
    except Exception as e:
        logger.warning(f"Own-store flag check skipped: {e}")
    # One-time purge of legacy name-based matches (Feb 2026: matcher v4 dropped name matching).
    # Idempotent — after the first run nothing matches the predicate.
    try:
        purged = await db.product_matches.delete_many({
            "manually_confirmed": {"$ne": True},
            "$or": [
                {"match_method": {"$regex": "^name_"}},
                {"confidence": {"$lt": 95}},
            ],
        })
        if purged.deleted_count:
            logger.info(f"Purged {purged.deleted_count} legacy name-based matches at startup")
    except Exception as e:
        logger.warning(f"Legacy match cleanup skipped: {e}")
    # Register crawl jobs for all active stores using the daily cron schedule
    stores = await db.stores.find({"is_active": True}, {"_id": 0}).to_list(100)
    for s in stores:
        register_crawl_job(s["id"], s["name"], s.get("domain", ""))
    logger.info(f"[Scheduler] Daily crawl schedule loaded — {len(stores)} stores, 04:00–04:55 KSA window.")
    if not scheduler.running:
        scheduler.start()
    scheduler.add_job(generate_market_digest, "cron", day_of_week="sun", hour=5, minute=0, id="weekly_digest", replace_existing=True)
    # Own-store price sync every 6h (Feb 2026)
    # Uses the shared _run_sync_and_match helper so the scheduled and manual
    # paths share identical error handling + sync_runs logging.
    async def _scheduled_own_sync():
        await _run_sync_and_match("scheduled")
    scheduler.add_job(_scheduled_own_sync, "interval", hours=6, id="own_store_sync", replace_existing=True)
    logger.info(f"Scheduler started with {len(stores)} crawl jobs + weekly digest + 6h own-store sync")

    # iter25 — warm the my-products dashboard cache in the background so the first
    # request after a deploy/restart is fast instead of paying the live-compute
    # cost. Fire-and-forget: never blocks startup, failures fall back to live.
    async def _warm_dashboard_cache():
        # iter36 — one-time food-subcategory backfill for pre-existing products
        # (new/recrawled products are classified in process_crawled_products).
        # Runs BEFORE the page-cache warm-up so trending caches see subcategories.
        try:
            n = await backfill_food_subcategories(db)
            if n:
                logger.info(f"[Subcat] backfilled {n} food products (field set even when generic → idempotent)")
        except Exception:
            logger.exception("[Subcat] backfill failed (new crawls will classify incrementally)")
        # iter30 — backfill the metric rollup/coverage collections FIRST so the
        # page-cache warm-up below reads populated metrics (drops/gaps/spread).
        await _maybe_backfill_store_metrics(db)
        try:
            await recompute_dashboard_cache(db)
        except Exception:
            logger.exception("[DashboardCache] startup warm-up failed (will populate on first request)")
        # iter26 — warm the Insights / Price-Intel caches too.
        try:
            await recompute_page_caches(db)
        except Exception:
            logger.exception("[PageCache] startup warm-up failed (will populate on first request)")
    asyncio.create_task(_warm_dashboard_cache())

    # ── Playwright Chromium AGGRESSIVE self-heal (Feb 2026 production deploy fix v2) ─
    # The previous probe-based version checked `chromium.executable_path` and skipped
    # install if the full chromium binary was present. That was a bug: in Playwright
    # >= 1.49, `chromium.launch(headless=True)` actually uses a SEPARATE binary
    # called `chrome-headless-shell` (different path from full chromium). Production
    # had full chromium but was missing chrome-headless-shell, so the probe said
    # "all good" yet every Tier-3 crawl still failed.
    #
    # New strategy:
    #   1. Detect if PLAYWRIGHT_BROWSERS_PATH is writable; if not, unset it so
    #      Playwright falls back to ~/.cache/ms-playwright.
    #   2. ALWAYS run `playwright install chromium chromium-headless-shell` —
    #      no probe, no skip. (Idempotent: noop if already up to date.)
    #   3. Smoke test by actually launching headless Chromium against about:blank.
    #      Log success or the exact failure with stack-trace.
    # Runs in a background daemon thread so it never blocks app startup. Crawl jobs
    # have 15-180 min offsets from startup so there is plenty of time for the install.
    import threading
    import subprocess
    import sys
    def _aggressive_playwright_self_heal():
        # 1. Writability probe on PLAYWRIGHT_BROWSERS_PATH
        browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
        install_env = os.environ.copy()
        if browsers_path:
            try:
                p = Path(browsers_path)
                p.mkdir(parents=True, exist_ok=True)
                probe = p / ".daleel_writeprobe"
                probe.write_text("ok")
                probe.unlink()
                logger.info(f"[Playwright] PLAYWRIGHT_BROWSERS_PATH={browsers_path!r} is WRITABLE")
            except Exception as write_err:
                logger.warning(
                    f"[Playwright] PLAYWRIGHT_BROWSERS_PATH={browsers_path!r} is NOT writable "
                    f"({write_err.__class__.__name__}: {write_err}). Falling back to default "
                    f"~/.cache/ms-playwright by unsetting the env var for this process."
                )
                # Unset for both the install subprocess AND the parent (so subsequent
                # Playwright launches use the default location).
                install_env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
                browsers_path = ""

        effective_path = install_env.get("PLAYWRIGHT_BROWSERS_PATH", "<default ~/.cache/ms-playwright>")
        # 2. ALWAYS install chromium + chromium-headless-shell
        cmd = [sys.executable, "-m", "playwright", "install", "chromium", "chromium-headless-shell"]
        logger.info(f"[Playwright] Aggressive install starting (browsers_path={effective_path!r}); cmd={' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, env=install_env, capture_output=True, text=True, timeout=900)
            if result.returncode == 0:
                logger.info(f"[Playwright] Install completed successfully (rc=0)")
                if result.stdout:
                    logger.info(f"[Playwright] install stdout (last 800): {result.stdout[-800:]}")
            else:
                logger.error(f"[Playwright] Install FAILED (rc={result.returncode})")
                logger.error(f"[Playwright] install stdout (last 1500): {result.stdout[-1500:] if result.stdout else '<empty>'}")
                logger.error(f"[Playwright] install stderr (last 1500): {result.stderr[-1500:] if result.stderr else '<empty>'}")
        except subprocess.TimeoutExpired:
            logger.error("[Playwright] Install TIMED OUT after 15 minutes — Tier-3 crawls will continue to fail")
            return
        except Exception as e:
            logger.error(f"[Playwright] Install raised exception: {e.__class__.__name__}: {e}")
            return

        # 3. Smoke test: actually launch headless Chromium and navigate to about:blank.
        # This exercises BOTH chromium and chromium-headless-shell binaries.
        try:
            from playwright.sync_api import sync_playwright
            logger.info("[Playwright] Smoke test: launching headless Chromium against about:blank...")
            with sync_playwright() as pw:
                exe = pw.chromium.executable_path
                logger.info(f"[Playwright] chromium.executable_path resolves to: {exe!r}")
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = browser.new_page()
                page.goto("about:blank", timeout=10000)
                title = page.title()
                browser.close()
                logger.info(
                    f"[Playwright] Smoke test PASSED — headless Chromium launched, "
                    f"navigated to about:blank, title={title!r}. Tier-3 crawls should now work."
                )
        except Exception as smoke_err:
            logger.error(
                f"[Playwright] Smoke test FAILED: {smoke_err.__class__.__name__}: {smoke_err}"
            )
            # Last-resort diagnostic: dump what's actually on disk so we can see why
            try:
                root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache" / "ms-playwright")))
                if root.exists():
                    contents = sorted(d.name for d in root.iterdir())
                    logger.error(f"[Playwright] Contents of {root}: {contents}")
                else:
                    logger.error(f"[Playwright] Browsers root {root} does not exist")
            except Exception as diag_err:
                logger.error(f"[Playwright] Could not dump browsers dir: {diag_err}")

    threading.Thread(
        target=_aggressive_playwright_self_heal,
        name="playwright-selfheal",
        daemon=True,
    ).start()

    # ── Proxy smoke test (Saudi residential, Webshare) ─────────
    # Verifies the proxy is reachable + identifies the exit IP. Only runs if
    # PROXY_USERNAMES is configured. Non-fatal: a failure is logged but never
    # crashes the backend.
    def _proxy_smoke_test():
        import httpx as _httpx
        proxy_users = os.getenv("PROXY_USERNAMES", "").split(",")
        proxy_users = [u.strip() for u in proxy_users if u.strip()]
        if not proxy_users:
            logger.info("[Proxy] Smoke test skipped: PROXY_USERNAMES env not set")
            return
        user = proxy_users[0]
        host = os.getenv("PROXY_HOST", "p.webshare.io")
        port = os.getenv("PROXY_PORT", "80")
        pwd = os.getenv("PROXY_PASSWORD", "")
        proxy_url = f"http://{user}:{pwd}@{host}:{port}"
        try:
            with _httpx.Client(proxy=proxy_url, timeout=30.0) as cli:
                r = cli.get("https://api.ipify.org?format=json")
                if r.status_code == 200:
                    exit_ip = r.json().get("ip", "?")
                    logger.info(f"[Proxy] Smoke test: connected via SA proxy, exit IP = {exit_ip}")
                else:
                    logger.error(f"[Proxy] Smoke test FAILED: HTTP {r.status_code} body={r.text[:200]}")
        except Exception as e:
            logger.error(f"[Proxy] Smoke test FAILED: {e.__class__.__name__}: {e}")
    threading.Thread(target=_proxy_smoke_test, name="proxy-smoketest", daemon=True).start()

@app.on_event("shutdown")
async def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    client.close()
