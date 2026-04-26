from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, Query, HTTPException, Request, Depends, Response, UploadFile, File
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, random, uuid, bcrypt, jwt as pyjwt, secrets, statistics, csv, io, re, time, shutil, asyncio
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from typing import Optional, List
from bson import ObjectId
from starlette.responses import StreamingResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from crawlers import (
    crawl_store_waterfall, process_crawled_products,
    extract_brand, guess_category, guess_animal, extract_weight,
)
from cryptography.fernet import Fernet, InvalidToken

SERVER_START_TIME = time.time()

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
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALG = "HS256"
CRAWLER_TOKEN = "zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO"
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
        return {"id": str(u["_id"]), "email": u["email"], "name": u.get("name", ""), "role": u.get("role", "user")}
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid token")

# ── Health Endpoint ──────────────────────────────────────────
@router.get("/health")
async def health_check():
    # MongoDB connection state
    mongo_ok = False
    try:
        await client.admin.command("ping")
        mongo_ok = True
    except Exception:
        pass

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

    # Last successful crawl timestamp
    last_crawl = None
    try:
        log = await db.crawl_logs.find_one(
            {"tier_used": {"$exists": True}},
            {"_id": 0, "completed_at": 1},
            sort=[("completed_at", -1)],
        )
        if log and log.get("completed_at"):
            last_crawl = log["completed_at"] if isinstance(log["completed_at"], str) else log["completed_at"].isoformat()
        else:
            store = await db.stores.find_one(
                {"last_crawled_at": {"$ne": "", "$exists": True}},
                {"_id": 0, "last_crawled_at": 1},
                sort=[("last_crawled_at", -1)],
            )
            if store and store.get("last_crawled_at"):
                last_crawl = store["last_crawled_at"]
    except Exception:
        pass

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

class Tier4CredentialsIn(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str] = None

class OtpSubmitIn(BaseModel):
    store_id: str
    otp_code: str

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
    "cat_food": "Cat Food", "cat_food_wet": "Wet Cat Food", "dog_food": "Dog Food",
    "dog_food_wet": "Wet Dog Food", "bird_food": "Bird Food",
    "fish_food": "Fish Food", "equipment": "Equipment", "accessories": "Accessories",
    "litter": "Litter", "toys": "Toys", "grooming": "Grooming",
    "healthcare": "Healthcare", "small_food": "Small Animal Food",
    "reptile": "Reptile", "vet_supplies": "Vet Supplies", "pet_food": "Pet Food",
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

def get_stock_signal(qty, in_stock=None):
    """Return a stock label.
    Many Salla/Zid stores set quantity=0 for products with `unlimited_quantity=true` or
    untracked inventory while still being available for purchase. Use the explicit
    `in_stock` flag (when present) as the source of truth and only fall back to qty.
    """
    if in_stock is False:
        return "OOS"
    if in_stock is True and (qty is None or qty == 0):
        return "AVAIL"  # In-stock but quantity not tracked
    if qty is None or qty == 0:
        return "OOS"
    if qty < 10:
        return "LOW"
    if qty <= 30:
        return "MEDIUM"
    return "HIGH"

async def seed_database():
    if await db.stores.count_documents({}) > 0:
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

    # Seed admin user
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@daleelpets.com")
    admin_pw = os.environ.get("ADMIN_PASSWORD", "BGv8ZcRYrBTPlJFHHhZQ3Q")
    existing_admin = await db.users.find_one({"email": admin_email})
    if not existing_admin:
        await db.users.insert_one({
            "email": admin_email, "password_hash": hash_pw(admin_pw),
            "name": "Admin", "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })
    else:
        # Always update password to match current ADMIN_PASSWORD
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_pw(admin_pw)}},
        )

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
    creds_path.write_text(f"# Daleel Test Credentials\n\n## Admin\n- Email: {admin_email}\n- Password: {admin_pw}\n- Role: admin\n\n## Auth Endpoints\n- POST /api/auth/login\n- POST /api/auth/register\n- GET /api/auth/me\n")

    logger.info(f"Seeded {len(STORES_SEED)} stores, {len(all_products_data)} products, {len(all_snapshots)} snapshots")


async def ensure_stores():
    """Ensure all required stores exist and have correct configuration."""
    required_stores = [
        {"name": "CuteCat", "domain": "cutecat.com.sa", "platform": "salla", "priority": 1, "working_endpoint": "/api/v1/products", "tier1_only": True},
        {"name": "CutePets", "domain": "cutepets.com.sa", "platform": "salla", "priority": 1, "working_endpoint": "/api/v1/products", "tier1_only": True},
        {"name": "Hamtaro", "domain": "hamtaro.sa", "platform": "salla", "priority": 2, "working_endpoint": "/api/v1/products", "tier1_only": True},
        {"name": "Mowkly", "domain": "mowkly.com", "platform": "salla", "priority": 1, "working_endpoint": "/api/v1/products", "tier1_only": True},
        {"name": "Aleef", "domain": "aleef.com", "platform": "zid", "priority": 1, "working_endpoint": "/api/v1/products"},
        {"name": "Hobba", "domain": "hobbapet.com", "platform": "zid", "priority": 1, "working_endpoint": "/api/v1/products"},
        {"name": "Caty", "domain": "caty-store.com", "platform": "salla", "priority": 2, "working_endpoint": "/en/api/v1/products"},
        {"name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla", "priority": 1, "use_storefront_categories": True},
    ]
    now = datetime.now(timezone.utc)
    added = 0
    for s in required_stores:
        existing = await db.stores.find_one({"domain": s["domain"]})
        if not existing:
            await db.stores.insert_one({
                "id": str(uuid.uuid4()), "name": s["name"], "domain": s["domain"],
                "platform": s["platform"], "base_url": f"https://{s['domain']}",
                "crawl_frequency_hrs": 12 if s["priority"] == 1 else 24,
                "buyer_account_enc": "", "is_active": True, "priority": s["priority"],
                "working_endpoint": s.get("working_endpoint", ""),
                "tier1_only": bool(s.get("tier1_only", False)),
                "use_storefront_categories": bool(s.get("use_storefront_categories", False)),
                "last_crawled_at": "", "created_at": now.isoformat(),
            })
            added += 1
            logger.info(f"[Stores] Added: {s['name']} ({s['domain']})")
        else:
            # Update platform/working_endpoint/tier1_only/use_storefront_categories if store exists but has wrong config
            updates = {}
            if existing.get("platform") != s["platform"]:
                updates["platform"] = s["platform"]
            if s.get("working_endpoint") and existing.get("working_endpoint") != s["working_endpoint"]:
                updates["working_endpoint"] = s["working_endpoint"]
            desired_tier1_only = bool(s.get("tier1_only", False))
            if bool(existing.get("tier1_only", False)) != desired_tier1_only:
                updates["tier1_only"] = desired_tier1_only
            desired_storefront = bool(s.get("use_storefront_categories", False))
            if bool(existing.get("use_storefront_categories", False)) != desired_storefront:
                updates["use_storefront_categories"] = desired_storefront
            if updates:
                await db.stores.update_one({"domain": s["domain"]}, {"$set": updates})
                logger.info(f"[Stores] Updated config for {s['name']}: {updates}")

    # Mark pets-houses.com as own store
    await db.stores.update_one(
        {"domain": "pets-houses.com"},
        {"$set": {"is_own_store": True}},
    )

    # Fix Cute Pets domain (cutepets.com → cutepets.com.sa) if old entry exists
    old_cute = await db.stores.find_one({"domain": "cutepets.com"})
    new_cute = await db.stores.find_one({"domain": "cutepets.com.sa"})
    if old_cute and new_cute:
        # Delete old entry if new one exists
        await db.stores.delete_one({"domain": "cutepets.com"})
        logger.info("[Stores] Removed old cutepets.com entry (replaced by cutepets.com.sa)")
    elif old_cute and not new_cute:
        await db.stores.update_one({"domain": "cutepets.com"}, {"$set": {"domain": "cutepets.com.sa", "platform": "salla", "base_url": "https://cutepets.com.sa", "working_endpoint": "/en/api/v1/products"}})
        logger.info("[Stores] Updated cutepets.com → cutepets.com.sa")

    if added:
        logger.info(f"[Stores] Added {added} new stores")

# ── Auth Routes ─────────────────────────────────────────────
@router.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, data: AuthIn, response: Response):
    email = data.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    doc = {"email": email, "password_hash": hash_pw(data.password), "name": data.name or email.split("@")[0], "role": "user", "created_at": datetime.now(timezone.utc)}
    result = await db.users.insert_one(doc)
    uid = str(result.inserted_id)
    token = make_token(uid, email)
    response.set_cookie("daleel_token", token, httponly=True, samesite="lax", max_age=86400, path="/")
    return {"token": token, "user": {"id": uid, "email": email, "name": doc["name"], "role": "user"}}

@router.post("/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, data: AuthIn, response: Response):
    email = data.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not check_pw(data.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    uid = str(user["_id"])
    token = make_token(uid, email)
    response.set_cookie("daleel_token", token, httponly=True, samesite="lax", max_age=86400, path="/")
    return {"token": token, "user": {"id": uid, "email": email, "name": user.get("name", ""), "role": user.get("role", "user")}}

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
    await crawl_store_waterfall(db, store)

def register_crawl_job(store_id, store_name, priority, offset_minutes=0):
    """Register a crawl job for a store in the scheduler."""
    job_id = f"crawl_{store_id}"
    hours = 4 if priority <= 1 else 8
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    scheduler.add_job(
        scheduled_crawl_job, IntervalTrigger(hours=hours),
        id=job_id, args=[store_id],
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=offset_minutes + 2),
        replace_existing=True,
    )
    logger.info(f"Scheduler: Registered {store_name} every {hours}h (offset +{offset_minutes}min)")

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
        hrs = 4 if s.get("priority", 3) <= 1 else 8
        s["crawl_frequency_label"] = f"Every {hrs}h"
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
    register_crawl_job(doc["id"], doc["name"], doc.get("priority", 3), 0)
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


# Heuristic constants for sales estimation (defensive — avoid placeholder-stock-noise blowing up totals)
PLACEHOLDER_QTY_VALUES = {99, 100, 999, 1000, 9999, 10000, 99999, 100000}
MAX_QTY_DELTA_PER_INTERVAL = 30  # >30 units sold per single crawl interval per SKU is almost certainly a data error
MAX_DAILY_SALES_PER_SKU = 200    # absolute upper bound for sanity


def _estimate_sales_from_snapshots(snaps, days):
    """
    Estimate sales for a SKU at a single store from chronological snapshot list.
    Strategy:
      1. PREFER sold_count diff (Salla `sales_count` / Zid `sold_count`) — cumulative sales counter, most reliable.
      2. FALL BACK to qty depletion with sanity filters (drop placeholder values, cap deltas).
    Returns (units_sold, revenue, used_method).
    """
    if not snaps or len(snaps) < 2:
        return 0, 0.0, "insufficient_data"

    # ── Method 1: sold_count cumulative diff (most reliable) ──
    sold_counts = [s.get("sold_count", 0) or 0 for s in snaps]
    if max(sold_counts) > 0 and sold_counts[0] >= 0:
        # Find first non-zero and last; ensure monotonic non-decrease (resets shouldn't be counted)
        first_sc = next((sc for sc in sold_counts if sc > 0), 0)
        last_sc = sold_counts[-1] if sold_counts[-1] >= first_sc else max(sold_counts)
        units_from_counter = max(0, last_sc - first_sc)
        if units_from_counter > 0:
            avg_price = sum((s.get("price") or 0) for s in snaps) / max(1, len(snaps))
            # Cap at sane absolute upper bound
            units_capped = min(units_from_counter, MAX_DAILY_SALES_PER_SKU * max(1, days))
            return units_capped, round(units_capped * avg_price, 2), "sold_count_diff"

    # ── Method 2: qty depletion with sanity filters ──
    units = 0
    revenue = 0.0
    for i in range(1, len(snaps)):
        prev_qty = snaps[i - 1].get("qty_available", 0) or 0
        curr_qty = snaps[i].get("qty_available", 0) or 0
        # Skip placeholder stock values — these are "unlimited" markers, not real inventory
        if prev_qty in PLACEHOLDER_QTY_VALUES or curr_qty in PLACEHOLDER_QTY_VALUES:
            continue
        # Skip when previous qty was already absurdly high (likely placeholder)
        if prev_qty > 500:
            continue
        delta = prev_qty - curr_qty
        if delta <= 0:
            continue
        # Sanity cap per snapshot interval
        delta = min(delta, MAX_QTY_DELTA_PER_INTERVAL)
        units += delta
        revenue += delta * (snaps[i].get("price") or 0)

    # Final daily cap
    daily_cap = MAX_DAILY_SALES_PER_SKU * max(1, days)
    if units > daily_cap:
        scale = daily_cap / units
        units = int(units * scale)
        revenue *= scale

    return units, round(revenue, 2), "qty_depletion_capped"


# ── Update test-login to actually trigger login ─────────────
def compute_product_metrics(snapshots_by_store, days):
    """Given {store_id: [snapshots sorted by crawled_at asc]}, compute market metrics."""
    all_latest_prices = []
    total_sold = 0
    total_revenue = 0.0
    latest_qty = 0
    any_in_stock = False
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
        if latest.get("in_stock") is True:
            any_in_stock = True

        # Estimate sales using the new defensible algorithm
        units, revenue, _ = _estimate_sales_from_snapshots(snaps, days)
        total_sold += units
        total_revenue += revenue

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
        "stock_signal": get_stock_signal(latest_qty, in_stock=any_in_stock if any_in_stock else None),
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
    products = await db.products.find(prod_query, {"_id": 0}).to_list(5000)

    # Pull SKU → product_url from my_products (user's own store) and store domains for fallback search URLs
    my_url_by_sku = {p["sku"]: p.get("product_url") for p in await db.my_products.find({}, {"_id": 0, "sku": 1, "product_url": 1}).to_list(10000) if p.get("product_url")}
    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "domain": 1})
    own_domain = own_store.get("domain") if own_store else None
    store_domains = {s["id"]: s.get("domain") for s in await db.stores.find({}, {"_id": 0, "id": 1, "domain": 1}).to_list(200) if s.get("domain")}

    result = []
    total_sold = 0
    total_rev = 0.0
    for p in products:
        stores_data = by_sku.get(p["sku"], {})
        metrics = compute_product_metrics(stores_data, days)
        if not metrics:
            continue
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

    # Get store name lookup
    store_names = {}
    own_store_id = None
    async for s in db.stores.find({}, {"_id": 0, "id": 1, "name": 1, "is_own_store": 1}):
        store_names[s["id"]] = s["name"]
        if s.get("is_own_store"):
            own_store_id = s["id"]

    snapshots = await db.product_snapshots.find(
        {"crawled_at": {"$gte": since}, "price": {"$gt": 0}},
        {"_id": 0, "store_id": 1, "sku": 1, "price": 1, "qty_available": 1, "crawled_at": 1}
    ).sort("crawled_at", 1).to_list(100000)

    # Group by store_id → sku → chronological snapshots
    by_store = {}
    for s in snapshots:
        sid = s.get("store_id", "")
        if sid == own_store_id:
            continue
        by_store.setdefault(sid, {}).setdefault(s["sku"], []).append(s)

    leaderboard = []
    for store_id, sku_data in by_store.items():
        total_rev = 0.0
        total_units = 0
        total_products = len(sku_data)
        for sku, snap_list in sku_data.items():
            units, revenue, _ = _estimate_sales_from_snapshots(snap_list, days)
            total_units += units
            total_rev += revenue

        store_name = store_names.get(store_id, store_id)
        leaderboard.append({
            "store": store_name,
            "store_id": store_id,
            "revenue_est": round(total_rev, 2),
            "units_sold": total_units,
            "products": total_products,
        })

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
        total_rev = 0.0
        for sid, snaps in data["store_snaps"].items():
            units, revenue, _ = _estimate_sales_from_snapshots(snaps, days)
            total_sold += units
            total_rev += revenue
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
        {"$match": {"price": {"$gt": 0}}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": {"sku": "$sku", "store_id": "$store_id"}, "price": {"$first": "$price"}, "store_name": {"$first": "$store_name"}}},
        {"$group": {"_id": "$_id.sku", "prices": {"$push": {"store": "$store_name", "price": "$price"}}, "min_p": {"$min": "$price"}, "max_p": {"$max": "$price"}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 3}, "min_p": {"$gt": 0}}},
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

# ── Discounts ────────────────────────────────────────────────
@router.get("/discounts/top-pct")
async def top_discounts_pct(days: int = Query(90), store_id: Optional[str] = Query(None), category: Optional[str] = Query(None), limit: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    match = {"crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}}
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
async def top_discounts_amount(days: int = Query(90), store_id: Optional[str] = Query(None), category: Optional[str] = Query(None), limit: int = Query(30), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    match = {"crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}}
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
async def discount_timeline(user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=90)
    pipeline = [
        {"$match": {"crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}}},
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
async def discount_aggression(user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=90)
    stores = await db.stores.find({"is_active": True}, {"_id": 0, "id": 1, "name": 1}).to_list(20)
    leaderboard = []
    for store in stores:
        pipeline = [
            {"$match": {"store_id": store["id"], "crawled_at": {"$gte": since}, "discount_pct": {"$gt": 0}}},
            {"$group": {"_id": None, "avg_depth": {"$avg": "$discount_pct"}, "max_disc": {"$max": "$discount_pct"}, "total_discounted": {"$sum": 1}}},
        ]
        result = await db.product_snapshots.aggregate(pipeline).to_list(1)
        total_snaps = await db.product_snapshots.count_documents({"store_id": store["id"], "crawled_at": {"$gte": since}})
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
@router.get("/scanner/opportunities")
async def price_opportunities(days: int = Query(14), user=Depends(get_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    snaps = await db.product_snapshots.find({"crawled_at": {"$gte": since}}, {"_id": 0}).sort("crawled_at", -1).to_list(100000)
    # Group latest per sku per store
    latest = {}
    for s in snaps:
        key = (s["sku"], s["store_id"])
        if key not in latest:
            latest[key] = s
    # Group by sku
    by_sku = {}
    for (sku, sid), s in latest.items():
        by_sku.setdefault(sku, []).append(s)
    # Compute sales velocity per sku
    all_snaps_sorted = {}
    for s in snaps:
        all_snaps_sorted.setdefault((s["sku"], s["store_id"]), []).append(s)
    sku_sales = {}
    for (sku, sid), sl in all_snaps_sorted.items():
        sl.sort(key=lambda x: x["crawled_at"])
        sold = 0
        for i in range(1, len(sl)):
            d = sl[i-1].get("qty_available", 0) - sl[i].get("qty_available", 0)
            if d > 0: sold += d
        sku_sales[(sku, sid)] = sold
    # Build opportunities
    products = await db.products.find({}, {"_id": 0}).to_list(500)
    prod_map = {p["sku"]: p for p in products}
    opportunities = []
    total_overpriced = 0
    total_uplift = 0
    zero_sales_overpriced = 0
    for sku, store_snaps in by_sku.items():
        if len(store_snaps) < 2: continue
        prices = [s["price"] for s in store_snaps if s["price"] > 0]
        if not prices: continue
        min_price = min(prices)
        avg_price = statistics.mean(prices)
        max_price = max(prices)
        for s in store_snaps:
            if s["price"] <= 0: continue
            gap_pct = round((s["price"] - min_price) / min_price * 100, 1) if min_price > 0 else 0
            if gap_pct < 10: continue
            total_sold_market = sum(sku_sales.get((sku, st["store_id"]), 0) for st in store_snaps)
            my_sold = sku_sales.get((sku, s["store_id"]), 0)
            uplift = round((s["price"] - min_price) * total_sold_market / max(len(store_snaps), 1), 2)
            p = prod_map.get(sku, {})
            badge = "overpriced_risk" if gap_pct >= 25 and my_sold == 0 else "quick_win" if uplift >= 500 and s.get("qty_available", 0) > 0 else "overpriced"
            if badge == "overpriced_risk": zero_sales_overpriced += 1
            total_overpriced += 1
            total_uplift += uplift
            opportunities.append({
                "sku": sku, "name_ar": p.get("name_ar", sku), "name_en": p.get("name_en", ""), "category": p.get("category", ""),
                "image_url": p.get("image_url", ""), "store_name": s["store_name"], "store_id": s["store_id"],
                "my_price": s["price"], "market_lowest": min_price, "market_avg": round(avg_price, 2),
                "gap_pct": gap_pct, "units_sold": my_sold, "market_sold": total_sold_market,
                "revenue_uplift": uplift, "badge": badge, "num_sellers": len(store_snaps),
                "in_stock": s.get("in_stock", False), "qty": s.get("qty_available", 0),
            })
    opportunities.sort(key=lambda x: x["revenue_uplift"], reverse=True)
    # Also find well-positioned and undercut opportunities
    well_positioned = []
    undercut = []
    for sku, store_snaps in by_sku.items():
        prices = [s["price"] for s in store_snaps if s["price"] > 0]
        if len(prices) < 2: continue
        min_p, avg_p = min(prices), statistics.mean(prices)
        for s in store_snaps:
            gap = abs(s["price"] - avg_p) / avg_p * 100 if avg_p > 0 else 0
            if gap <= 5:
                p = prod_map.get(sku, {})
                well_positioned.append({"sku": sku, "name_ar": p.get("name_ar", ""), "price": s["price"], "market_avg": round(avg_p, 2), "store_name": s["store_name"]})
            if s["price"] == min_p and s["price"] < avg_p * 0.95:
                total_sold_market = sum(sku_sales.get((sku, st["store_id"]), 0) for st in store_snaps)
                p = prod_map.get(sku, {})
                undercut.append({"sku": sku, "name_ar": p.get("name_ar", ""), "price": s["price"], "market_avg": round(avg_p, 2), "store_name": s["store_name"], "market_sold": total_sold_market})
    return {
        "summary": {"overpriced_count": total_overpriced, "total_uplift_sar": round(total_uplift, 2), "zero_sales_overpriced": zero_sales_overpriced},
        "opportunities": opportunities[:50],
        "well_positioned": well_positioned[:20],
        "undercut": undercut[:20],
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
    data = await my_products(days=days, category=None, animal_type=None, search=None, sort_by="revenue_est", sort_order="desc", user=user)
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
from matcher import match_my_product, run_matching_for_all

class MatchActionIn(BaseModel):
    my_sku: str
    competitor_sku: str
    competitor_store_id: str

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
async def trigger_matching(user=Depends(get_user)):
    """Run the matching engine for all imported my_products (background)."""
    count = await db.my_products.count_documents({})
    if count == 0:
        raise HTTPException(400, "No products imported yet")
    # Run in background
    asyncio.create_task(_background_matching())
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
    return {
        "my_products": my_count,
        "total_matches": match_count,
        "confirmed_matches": confirmed_count,
        "blacklisted": blacklist_count,
        "matching_job": job,
    }


@router.get("/price-intel/dashboard")
async def price_intel_dashboard(user=Depends(get_user)):
    """Price Intelligence Dashboard — all sections."""
    matches = await db.product_matches.find({}, {"_id": 0}).to_list(50000)
    my_products = {p["sku"]: p async for p in db.my_products.find({}, {"_id": 0})}

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
    """Section D — drill-down for a single product."""
    mp = await db.my_products.find_one({"sku": sku}, {"_id": 0})
    if not mp:
        raise HTTPException(404, "Product not found")

    matches = await db.product_matches.find({"my_sku": sku}, {"_id": 0}).to_list(100)

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
            "price_history": [{"price": h["price"], "in_stock": h.get("in_stock"), "date": h["crawled_at"].isoformat() if hasattr(h["crawled_at"], 'isoformat') else str(h["crawled_at"])} for h in history[-60:]],
            "price_trend": trend,
        })

    all_prices = [c["competitor_price"] for c in competitors if c["competitor_price"] > 0]
    return {
        "my_product": mp,
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
        query["$or"] = [
            {"name_ar": {"$regex": search, "$options": "i"}},
            {"name_en": {"$regex": search, "$options": "i"}},
            {"sku": {"$regex": search, "$options": "i"}},
        ]
    total = await db.my_products.count_documents(query)
    items = await db.my_products.find(query, {"_id": 0}).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"items": items, "total": total, "page": page, "pages": (total + limit - 1) // limit}


# ── External Crawler Ingest API ──────────────────────────────
class IngestPayload(BaseModel):
    store_id: str
    store_name: str
    domain: str
    platform: str
    products: list

def _coerce_num(v, default=0.0):
    """Defensively coerce a value that may be None / int / float / str with currency or commas to float."""
    if v is None or v == "":
        return float(default)
    if isinstance(v, bool):
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        # Strip currency symbols, Arabic separators, commas, spaces
        s = re.sub(r"[^0-9.\-]", "", str(v))
        if s in ("", "-", ".", "-."):
            return float(default)
        return float(s)
    except (ValueError, TypeError):
        return float(default)


def _coerce_int(v, default=0):
    try:
        return int(_coerce_num(v, default))
    except (ValueError, TypeError):
        return int(default)


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
                    await db.products.insert_one({
                        "id": pid, "sku": sku,
                        "name_ar": name_ar, "name_en": name_en,
                        "barcode": barcode,
                        "brand": "", "category": "", "animal_type": "",
                        "weight_kg": 0, "image_url": "",
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

        return {
            "received": len(payload.products),
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "token_valid": True,
            "store_id": canonical_store_id,
            "crawled_at": now.isoformat(),
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
    await ensure_stores()
    # Register crawl jobs for all active stores (skip own store)
    stores = await db.stores.find({"is_active": True}, {"_id": 0}).to_list(100)
    for idx, s in enumerate(stores):
        register_crawl_job(s["id"], s["name"], s.get("priority", 3), idx * 15)
    if not scheduler.running:
        scheduler.start()
    scheduler.add_job(generate_market_digest, "cron", day_of_week="sun", hour=5, minute=0, id="weekly_digest", replace_existing=True)
    logger.info(f"Scheduler started with {len(stores)} crawl jobs + weekly digest")

@app.on_event("shutdown")
async def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    client.close()
