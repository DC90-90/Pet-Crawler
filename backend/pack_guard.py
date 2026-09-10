"""iter78 — PACK SIZE GUARD.

The client's report: their 45g toothpaste showed a +445% gap because one store
listed 4.30 SAR against their 23.45, while a second store agreed with them at
23.00. Same shape on Kit Cat 15g treat sticks: two stores were selling the
**3.5g** single (their URL slugs say so), and one store sat 3.2x below the
10 SAR cluster six other sellers agreed on.

`product_snapshots` carries no product NAME, which is why every earlier guard
had to fall back to comparing our descriptor against the ONE shared catalogue
row (server.py's `_pack_compatible` call) or to a raw price ratio
(`barcode_price_sane`, 6x). But snapshots DO carry `product_url`, and a
storefront slug is the seller's OWN descriptor:

    petsysa.com/products/Sticks-Atlantic-Salmon-3-5-g-Treats-For-Cats-Kit-Cat
    aleef.com/products/...-3-5-جرام-kit-cat-sticks-atlantic-salmon...
    caty-store.com/products/كتكات-اعواد-للقطط-15غ-1

So this module adds two independent guards:

1. `slug_pack_reject` — EXPLICIT evidence only. A seller is dropped when its own
   slug states a weight or pack count that contradicts ours. Silence is never
   treated as evidence: a slug with no pack info (or no slug at all) is left
   alone, unlike `_pack_compatible`, which reads "says nothing" as "single unit"
   and would wipe out every quiet seller of a multipack.

2. `cluster_outliers` — a price is dropped when it sits >=3x below the median of
   the cluster that CORROBORATES it (our own price plus the other sellers), and
   only when at least two such reference prices exist. `barcode_price_sane`
   already refuses at 6x pairwise; 3x with two corroborating sources is the
   in-between band that produced the 445%. A 3x cut is a 67% discount, which
   does happen — so nothing is silently deleted: every exclusion is returned
   with its reason and surfaced in the Scanner's summary.
"""
import re
from urllib.parse import unquote, urlparse

from matcher import (WEIGHT_RE, _extract_weight_grams,  # noqa: F401
                     _pack_qty_explicit, _weights_reject)

# A price this far below its corroborating cluster is a pack collision, not a sale.
CLUSTER_OUTLIER_RATIO = 3.0
# Fewer corroborating prices than this is not a cluster — leave the price alone.
CLUSTER_MIN_REFERENCES = 2
# With only two corroborating prices (often "one rival plus us") the evidence is
# thin, so the gap has to be far wider before we call it. This is what keeps a
# genuine clearance alive: Royal Canin cut 466 -> 118 with one rival at 431 is
# 3.8x on two references and stays, while the client's 45g toothpaste at 4.30
# against 23.00 and 23.45 is 5.4x and goes.
CLUSTER_STRONG_REFERENCES = 3
CLUSTER_THIN_RATIO = 5.0

# "3-5-g" / "1-5-kg": a slug spells decimals with the separator it uses for
# every other word, so the weight parser reads "5 g" — a 3.5g single then walks
# through the guard as a 5g product. Rebuild the decimal BEFORE separators
# become spaces.
_SLUG_DECIMAL_RE = re.compile(
    r'(?<!\d)(\d+)[-_](\d+)\s*[-_]?\s*'
    r'(kg|g|gm|gr|grams?|ml|l|liter|litre|كجم|كغ|جم|جرام|غ|مل|لتر)(?![\w\u0621-\u064A])',
    re.IGNORECASE)
# NOTE: `.` is deliberately NOT a separator here — this runs after
# _SLUG_DECIMAL_RE has rebuilt "3-5-g" into "3.5g", and stripping the dot would
# hand the weight parser "5 g" all over again.
_SLUG_SEPARATORS_RE = re.compile(r'[-_+]+')
# The shared WEIGHT_RE knows جم / جرام / كجم but not the bare غ / كغ forms Saudi
# storefronts use ("15غ"). Normalised here rather than in matcher.py so the
# product matcher's global behaviour is untouched.
_SLUG_AR_KILO_RE = re.compile(r'(?<=\d)\s*كغ(?![\w\u0621-\u064A])')
_SLUG_AR_GRAM_RE = re.compile(r'(?<=\d)\s*غ(?![\w\u0621-\u064A])')


def _slug_number_pair(m):
    """"3-5-g" is a decimal; "4-14g" is a count x unit weight.

    Slug generators drop the multiplier, so both shapes arrive identically.
    Saudi pet catalogues settle it: a decimal weight always has a ONE-digit
    fraction (3.5g, 1.5kg), while a multipack's second number is the unit weight
    (4x14g, 6x50g, 40x15g). Rewriting the multipack case as "4 x 14g" lets the
    shared parsers read a pack count of 4 AND a unit weight of 14g, instead of
    inventing a 4.14g product.
    """
    a, b, unit = m.group(1), m.group(2), m.group(3)
    return f"{a}.{b}{unit}" if len(b) == 1 else f"{a} x {b}{unit}"


def slug_descriptor(url: str) -> str:
    """The seller's own descriptor, recovered from a product URL's last segment.

    Returns "" when there is nothing usable — callers must treat that as NO
    EVIDENCE, never as evidence of a single unit.
    """
    if not url:
        return ""
    try:
        path = urlparse(str(url)).path or str(url)
    except ValueError:
        path = str(url)
    seg = unquote(path.rstrip("/").split("/")[-1])
    if not seg:
        return ""
    seg = _SLUG_DECIMAL_RE.sub(_slug_number_pair, seg)
    seg = _SLUG_SEPARATORS_RE.sub(" ", seg)
    seg = _SLUG_AR_KILO_RE.sub(" كجم", seg)
    seg = _SLUG_AR_GRAM_RE.sub(" جم", seg)
    return re.sub(r'\s+', " ", seg).strip()


def _fmt(g):
    return f"{g:g}"


def stated_weight_grams(text):
    """The ONE weight a descriptor states, in grams, or None when it is silent
    OR ambiguous.

    Ambiguity is common on BOTH sides, so this is used for our catalogue name
    and for the seller's slug alike. Real examples from the client's data:
      ours  "…رمل قطط عالي التكتل برائحة زهرة الكرز 20كج /30لتر"  (mass AND volume)
      their "…Baby-Powder-Scent-23.6L-20-Kg-Beso"                  (Petsy, same bag)
    Taking the first token made two listings of the identical product look like
    different sizes.
    """
    ws = [w for w in (_extract_weight_grams(m.group(0))
                      for m in WEIGHT_RE.finditer(str(text or ""))) if w]
    if not ws:
        return None
    if max(ws) > min(ws) * 1.1:
        return None
    return min(ws)


def slug_pack_reject(my_name: str, my_weight_g, slug_text: str):
    """(reject, reason) for one seller, from EXPLICIT evidence on both sides."""
    if not slug_text:
        return False, None
    q_mine, q_theirs = _pack_qty_explicit(my_name), _pack_qty_explicit(slug_text)
    if q_mine and q_theirs and q_mine != q_theirs:
        return True, f"slug_pack_qty_{q_theirs}_vs_ours_{q_mine}"
    # The WEIGHT axis is only trustworthy between two SINGLE units. Once either
    # side is a multipack the slug's number could be the unit weight, the pack
    # total, or a concatenation the slug generator mangled — real examples from
    # the client's own catalogue, all of them the SAME product as ours:
    #   ours 4x15g  -> "…لكرات الشعر 415جرام"      (Hobba, 4x15 run together)
    #   ours 4x14g  -> "…للقطط 4-14جرام" / "…414 جم" (Mowkly, Hobba)
    #   ours 6x50g  -> "…In-Broth-6.50g…"            (Petsy)
    # Comparing those against our unit weight excluded legitimate sellers and
    # moved the market low the wrong way, so multipacks are left to the pack-qty
    # axis above and to the corroborated-cluster rule below.
    if q_mine or q_theirs:
        return False, None
    their_w = stated_weight_grams(slug_text)
    if my_weight_g and their_w:
        # Slug generators also DROP the decimal point outright: the client's
        # 7.5kg litter is "…-75كج" at Hobba (and in their own storefront slug),
        # their 1.2L fountain is "…-12-لتر" at Hobba and Caty, and their 1.2kg
        # KitCat dry food is "…-120-كجم" at Mowkly. So a stated weight only
        # counts as a contradiction when its dropped-decimal readings disagree
        # too — otherwise the guard hid sellers 45% cheaper than us on the exact
        # same product. Nothing plausible in a pet catalogue is 100x out, so the
        # escape costs no real detection.
        if all(_weights_reject(my_weight_g, their_w / d) for d in (1, 10, 100)):
            return True, f"slug_weight_{_fmt(their_w)}g_vs_ours_{_fmt(my_weight_g)}g"
    return False, None


def median(values):
    v = sorted(values)
    n = len(v)
    if not n:
        return 0.0
    mid = n // 2
    return v[mid] if n % 2 else (v[mid - 1] + v[mid]) / 2


def cluster_outliers(prices, own_price=None, ratio=CLUSTER_OUTLIER_RATIO):
    """Which of `prices` sit far enough below the cluster that corroborates them.

    `prices` is a list of (key, price). The reference cluster for a candidate is
    every OTHER price plus our own, so two sellers agreeing — or one seller
    agreeing with us — can call a third one out, but a two-price reference has to
    be `CLUSTER_THIN_RATIO` apart while three or more only needs `ratio`.
    Returns {key: {"price", "cluster_median", "ratio", "references", "needed"}}.
    """
    out = {}
    for key, p in prices:
        if not p or p <= 0:
            continue
        others = [q for k, q in prices if k != key and q and q > 0]
        if own_price and own_price > 0:
            others.append(float(own_price))
        if len(others) < CLUSTER_MIN_REFERENCES:
            continue
        med = median(others)
        if med <= 0:
            continue
        r = med / p
        needed = ratio if len(others) >= CLUSTER_STRONG_REFERENCES else CLUSTER_THIN_RATIO
        if r >= needed:
            out[key] = {"price": p, "cluster_median": round(med, 2),
                        "ratio": round(r, 2), "references": len(others),
                        "needed": needed}
    return out


def discount_escapes(outliers, history, near=0.75):
    """Outlier keys that are a PRICE CUT, not a different product.

    A store that used to sell at the market price and then dropped is running a
    clearance — exactly the competitor move the client wants to SEE. A store
    whose price has always been a fifth of everyone else's is selling something
    else. `history` is [(key, price)] of that SKU's earlier observations in the
    window.
    """
    keep = set()
    for key, price in history:
        info = outliers.get(key)
        if info and price and price >= info["cluster_median"] * near:
            keep.add(key)
    return keep
