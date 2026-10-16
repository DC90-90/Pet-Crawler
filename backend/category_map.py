"""One shared category taxonomy across stores.

Every store names its categories differently ("القطط", "Cat Food", "طعام قطط
جاف"). A share per category is only meaningful on one taxonomy, so:

* the canonical taxonomy is the own store's categories (pets-houses.com),
  refreshed from `my_products` on every load;
* each (store, store category) pair is mapped to a canonical name by, in
  order: a reviewed human decision, an exact match after Arabic
  normalisation, a shared synonym group (cats/dogs/dry food/...), or a token
  overlap. Anything else stays unmapped and is reported as such, never
  dropped and never filed under a real category.

Rows live in `db.category_map`: {_id, store_id, store_category, canonical,
method: reviewed|exact|synonym|overlap|unmapped, products_count, updated_at}.
"""
import re
import unicodedata
from datetime import datetime, timezone, timedelta

_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_STOP = {"ال", "و", "من", "في", "the", "and", "for", "of", "&"}

# Synonym groups: a store category that mentions any term of a group is
# tagged with that group; two names agree when their tag sets intersect and
# do not contradict on the animal axis.
_GROUPS = {
    "cat": ("قطط", "قطه", "قطة", "القطط", "cat", "cats", "kitten", "feline"),
    "dog": ("كلاب", "كلب", "الكلاب", "dog", "dogs", "puppy", "canine"),
    "bird": ("طيور", "طير", "عصافير", "bird", "birds", "parrot"),
    "fish": ("اسماك", "سمك", "احواض", "fish", "aquarium"),
    "small_pet": ("هامستر", "ارانب", "ارنب", "قوارض", "hamster", "rabbit", "rodent", "small pet"),
    "dry_food": ("جاف", "دراي", "dry", "kibble"),
    "wet_food": ("رطب", "معلبات", "معلب", "باوتش", "wet", "can", "cans", "pouch", "pate"),
    "treats": ("مكافات", "مكافآت", "سناك", "treat", "treats", "snack", "snacks"),
    "litter": ("رمل", "رمال", "litter", "sand"),
    "health": ("صحة", "فيتامين", "فيتامينات", "علاج", "مكملات", "health", "vitamin", "vitamins", "supplement", "medicine"),
    "grooming": ("عناية", "نظافة", "شامبو", "grooming", "shampoo", "hygiene", "care"),
    "toys": ("العاب", "لعب", "toy", "toys"),
    "accessories": ("اكسسوارات", "مستلزمات", "ادوات", "accessories", "accessory", "supplies", "gear"),
    "housing": ("اقفاص", "قفص", "بيوت", "حامل", "cage", "cages", "house", "carrier", "crate", "bed", "beds"),
    "bowls": ("اوعية", "اواني", "bowl", "bowls", "feeder", "fountain"),
    "collars": ("اطواق", "طوق", "سلاسل", "collar", "leash", "harness"),
}
_ANIMALS = {"cat", "dog", "bird", "fish", "small_pet"}


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = _AR_DIACRITICS.sub("", text)
    text = (text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                .replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي"))
    text = _NON_WORD.sub(" ", text).lower()
    return " ".join(text.split())


def tokens(text):
    out = set()
    for t in normalize(text).split():
        if t in _STOP:
            continue
        out.add(t[2:] if t.startswith("ال") and len(t) > 4 else t)
    return out


def groups(text):
    norm = " " + normalize(text) + " "
    toks = tokens(text)
    found = set()
    for name, terms in _GROUPS.items():
        for term in terms:
            nt = normalize(term)
            if (" " in nt and f" {nt} " in norm) or nt in toks or any(t.startswith(nt) and len(nt) >= 3 for t in toks):
                found.add(name)
                break
    return found


def _score(store_category, canonical):
    """(method, score) for one candidate canonical; None when they disagree."""
    a, b = normalize(store_category), normalize(canonical)
    if not a or not b:
        return None
    if a == b:
        return "exact", 3.0
    ga, gb = groups(a), groups(b)
    if ga and gb:
        if (ga & _ANIMALS) and (gb & _ANIMALS) and not (ga & gb & _ANIMALS):
            return None  # different animals never map onto each other
        shared = ga & gb
        if shared:
            return "synonym", 2.0 + len(shared) / 10 + (0.05 if ga == gb else 0)
    ta, tb = tokens(a), tokens(b)
    if ta and tb:
        j = len(ta & tb) / len(ta | tb)
        if j >= 0.5:
            return "overlap", 1.0 + j
    return None


def best_match(store_category, canonicals):
    best = None
    for c in canonicals:
        s = _score(store_category, c)
        if s and (best is None or s[1] > best[1]):
            best = (s[0], s[1], c)
    return (best[0], best[2]) if best else ("unmapped", None)


class CategoryMap:
    def __init__(self, canonicals, rows, own_store_id):
        self.canonicals = list(canonicals)
        self.own_store_id = own_store_id
        self.rows = {(r["store_id"], normalize(r["store_category"])): r for r in rows}
        self.unmapped_seen = {}

    def resolve(self, store_id, store_categories):
        """(canonical, method, store_category_used). Own-store categories are
        canonical by definition; other stores go through the map."""
        names = [c.get("name") if isinstance(c, dict) else c for c in (store_categories or [])]
        names = [n for n in names if n]
        if not names:
            return "", "none", None
        if store_id == self.own_store_id:
            return names[0], "canonical", names[0]
        for name in names:
            row = self.rows.get((store_id, normalize(name)))
            if row and row.get("canonical"):
                return row["canonical"], row.get("method") or "mapped", name
        for name in names:
            method, canonical = best_match(name, self.canonicals)
            if canonical:
                return canonical, method, name
        self.unmapped_seen[(store_id, names[0])] = self.unmapped_seen.get((store_id, names[0]), 0) + 1
        return "", "unmapped", names[0]

    def label(self, store_id, store_categories):
        canonical, method, used = self.resolve(store_id, store_categories)
        if canonical:
            return canonical, method
        return (f"unmapped: {used}" if used else ""), method


async def canonical_taxonomy(db):
    own = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_id = own["id"] if own else None
    names = await db.my_products.distinct("category", {"category_source": {"$in": ["store_supplied", "reviewed", "import_file"]},
                                                       "category": {"$nin": [None, ""]}})
    return own_id, sorted(n for n in names if isinstance(n, str) and n.strip())


async def load(db, max_age_hours=6):
    """CategoryMap for this request. Rebuilds the persisted rows when they are
    missing or older than `max_age_hours`; reviewed rows are never touched."""
    own_id, canonicals = await canonical_taxonomy(db)
    # The build marker, not the newest row: with no categorised products yet
    # (production before its first new-format crawl) there were no rows, so
    # every load rebuilt and every rebuild bumped the observation revision,
    # which invalidated the page caches being built around it (11 Oct 2026).
    meta = await db.data_versions.find_one({"_id": "category_map"}, {"_id": 0, "built_at": 1})
    built_at = (meta or {}).get("built_at")
    stale = (built_at is None or
             datetime.now(timezone.utc) - built_at.replace(tzinfo=timezone.utc) > timedelta(hours=max_age_hours))
    if stale:
        await rebuild(db, canonicals=canonicals, own_store_id=own_id)
    rows = await db.category_map.find({}, {"_id": 0}).to_list(20000)
    return CategoryMap(canonicals, rows, own_id)


async def rebuild(db, canonicals=None, own_store_id=None):
    if canonicals is None:
        own_store_id, canonicals = await canonical_taxonomy(db)
    now = datetime.now(timezone.utc)
    counts = {}
    pipeline = [{"$match": {"store_categories.0": {"$exists": True}}},
                {"$unwind": "$store_categories"},
                {"$group": {"_id": {"store_id": "$store_id", "name": "$store_categories.name"}, "n": {"$sum": 1}}}]
    async for g in db.products.aggregate(pipeline):
        sid, name = g["_id"].get("store_id"), g["_id"].get("name")
        if sid and name and sid != own_store_id:
            counts[(sid, name)] = counts.get((sid, name), 0) + g["n"]
    reviewed = {(r["store_id"], normalize(r["store_category"])): r async for r in db.category_map.find({"method": "reviewed"}, {"_id": 0})}
    written = 0
    for (sid, name), n in counts.items():
        key = (sid, normalize(name))
        if key in reviewed:
            await db.category_map.update_one({"_id": f"{sid}|{key[1]}"}, {"$set": {"products_count": n, "updated_at": now}})
            continue
        method, canonical = best_match(name, canonicals)
        await db.category_map.update_one({"_id": f"{sid}|{key[1]}"}, {"$set": {
            "store_id": sid, "store_category": name, "canonical": canonical, "method": method,
            "products_count": n, "updated_at": now}}, upsert=True)
        written += 1
    # An automatic refresh records when it ran and never bumps the observation
    # revision: only a human mapping (set_mapping) changes what the pages say.
    await db.data_versions.update_one({"_id": "category_map"}, {"$set": {"built_at": now, "pairs": len(counts), "written": written}}, upsert=True)
    return {"pairs": len(counts), "written": written, "reviewed_kept": len(reviewed), "canonicals": len(canonicals)}


async def set_mapping(db, store_id, store_category, canonical, actor):
    key = normalize(store_category)
    if not key:
        raise ValueError("store_category is required")
    await db.category_map.update_one({"_id": f"{store_id}|{key}"}, {"$set": {
        "store_id": store_id, "store_category": store_category, "canonical": (canonical or "").strip() or None,
        "method": "reviewed", "reviewed_by": actor, "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    await db.data_versions.update_one({"_id": "observations"}, {"$inc": {"revision": 1}}, upsert=True)


async def listing(db, store_id=None):
    q = {"store_id": store_id} if store_id else {}
    rows = await db.category_map.find(q, {"_id": 0}).sort([("store_id", 1), ("products_count", -1)]).to_list(20000)
    _, canonicals = await canonical_taxonomy(db)
    return {"canonicals": canonicals, "rows": rows,
            "unmapped": sum(1 for r in rows if not r.get("canonical")),
            "unmapped_products": sum(r.get("products_count") or 0 for r in rows if not r.get("canonical"))}


# Tabs on the market lists (16 Oct 2026): one animal and one product type per
# offer, from its store category and its name. Exact words only (the prefix
# match above files "canary" under cans); an Arabic word may carry up to two
# leading particles (للقطط, بالدجاج). An offer naming two animals has none.
# Singular forms after a particle (للقط, القط) — "قط" alone is too short for
# the suffix rule ("فقط" means "only"), so they are listed whole.
_FACET_EXTRA = {"bird": ("كناري", "بادجي", "كوكتيل", "canary", "budgie"),
                "cat": ("للقط", "القط", "بالقط", "قط", "كات", "kitty"),
                "dog": ("للكلب", "الكلب", "دوق", "دوج"),
                "small_pet": ("سلحفاه", "turtle"), "toys": ("لعبه",),
                "wet_food": ("شوربه", "ستيك", "جيلي", "مرق", "soup", "gravy", "jelly"),
                "dry_food": ("كيبل", "حبوب")}
FACET_TYPES = ("litter", "dry_food", "wet_food", "treats", "health", "grooming", "toys",
               "housing", "bowls", "collars", "accessories")


def _has(words, term):
    nt = normalize(term)
    if " " in nt:
        return f" {nt} " in f" {' '.join(words)} "
    arabic = not nt.isascii()
    for w in words:
        if w == nt or (not arabic and w == nt + "s"):
            return True
        if arabic and len(nt) >= 3 and (w.endswith(nt) and len(w) - len(nt) <= 3
                                        or w.startswith(nt) and len(w) - len(nt) == 1):   # لعب → لعبه
            return True
    return False


def facets(*texts):
    words = normalize(" ".join(str(t or "") for t in texts)).split()
    tags = {name for name, terms in _GROUPS.items() if any(_has(words, t) for t in terms + _FACET_EXTRA.get(name, ()))}
    animals = tags & _ANIMALS
    # "Cat food with tuna and white fish": fish/bird words in a cat or dog
    # product are flavours, not the animal.
    if animals & {"cat", "dog"}:
        animals &= {"cat", "dog"}
    return {"facet_animal": next(iter(animals)) if len(animals) == 1 else None,
            "facet_type": next((t for t in FACET_TYPES if t in tags), None)}


def facet_counts(rows):
    """{"animal": {cat: n, ...}, "type": {...}} over rows, for the tab badges."""
    out = {"animal": {}, "type": {}}
    for r in rows:
        for axis in ("animal", "type"):
            v = r.get(f"facet_{axis}") or "other"
            out[axis][v] = out[axis].get(v, 0) + 1
    return out


def facet_filter(rows, animal=None, ptype=None):
    if animal not in (None, "", "all"):
        rows = [r for r in rows if (r.get("facet_animal") or "other") == animal]
    if ptype not in (None, "", "all"):
        rows = [r for r in rows if (r.get("facet_type") or "other") == ptype]
    return rows
