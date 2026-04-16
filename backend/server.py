from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, Query, HTTPException, Request, Depends, Response
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, random, uuid, bcrypt, jwt as pyjwt, secrets, statistics, csv, io, re
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from typing import Optional, List
from bson import ObjectId
from starlette.responses import StreamingResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from crawlers import (
    crawl_store_waterfall, process_crawled_products,
    extract_brand, guess_category, guess_animal, extract_weight,
)

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALG = "HS256"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Daleel Pets API")
router = APIRouter(prefix="/api")
scheduler = AsyncIOScheduler()
crawl_paused = False

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

    logger.info(f"Seeded {len(STORES_SEED)} stores, {len(all_products_data)} products, {len(all_snapshots)} snapshots")

# ── Auth Routes ─────────────────────────────────────────────
@router.post("/auth/register")
async def register(data: AuthIn, response: Response):
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
async def login(data: AuthIn, response: Response):
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

    # Revenue estimation from depletion over 90 days
    snaps_90d = await db.product_snapshots.find({"store_id": store_id, "crawled_at": {"$gte": since_90d}}, {"_id": 0}).sort("crawled_at", 1).to_list(50000)
    by_sku = {}
    for s in snaps_90d:
        by_sku.setdefault(s["sku"], []).append(s)

    total_rev = 0
    total_sold = 0
    weekly_rev = {}
    sku_sales = {}

    for sku, slist in by_sku.items():
        for i in range(1, len(slist)):
            delta = slist[i-1].get("qty_available", 0) - slist[i].get("qty_available", 0)
            if delta > 0:
                rev = delta * slist[i]["price"]
                total_sold += delta
                total_rev += rev
                sku_sales[sku] = sku_sales.get(sku, 0) + delta
                ca = slist[i]["crawled_at"]
                week_key = ca.strftime("%Y-W%W") if isinstance(ca, datetime) else ca[:10]
                weekly_rev[week_key] = weekly_rev.get(week_key, 0) + rev

    # Revenue trend (weekly)
    revenue_trend = [{"week": k, "revenue": round(v, 2)} for k, v in sorted(weekly_rev.items())]

    # Also compute daily for toggle
    daily_rev = {}
    for sku, slist in by_sku.items():
        for i in range(1, len(slist)):
            delta = slist[i-1].get("qty_available", 0) - slist[i].get("qty_available", 0)
            if delta > 0:
                ca = slist[i]["crawled_at"]
                day_key = ca.strftime("%Y-%m-%d") if isinstance(ca, datetime) else ca[:10]
                daily_rev[day_key] = daily_rev.get(day_key, 0) + delta * slist[i]["price"]
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

    return {
        "store": store,
        "kpis": {
            "catalog_size": len(skus), "active_skus": len(active_skus),
            "est_monthly_revenue": round(total_rev / 3, 2),
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

# ── Root ────────────────────────────────────────────────────
@router.get("/")
async def root():
    return {"message": "Daleel Pets API - دليل بيتس"}

# ── App Setup ───────────────────────────────────────────────
app.include_router(router)

cors_origins = os.environ.get('CORS_ORIGINS', '*')
if cors_origins == '*':
    cors_origins_list = ["*"]
    allow_creds = False
else:
    cors_origins_list = [o.strip() for o in cors_origins.split(',')]
    allow_creds = True

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
    # Register crawl jobs for all active stores
    stores = await db.stores.find({"is_active": True}, {"_id": 0}).to_list(100)
    for idx, s in enumerate(stores):
        register_crawl_job(s["id"], s["name"], s.get("priority", 3), idx * 15)
    if not scheduler.running:
        scheduler.start()
    # Register weekly digest job — Sunday 05:00 UTC (08:00 Riyadh)
    scheduler.add_job(generate_market_digest, "cron", day_of_week="sun", hour=5, minute=0, id="weekly_digest", replace_existing=True)
    logger.info(f"Scheduler started with {len(stores)} crawl jobs + weekly digest")

@app.on_event("shutdown")
async def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    client.close()
