"""Daily brief and weekly report (17 Oct 2026), built from sealed facts and
kept in `reports` so the page and the email show the same thing.

daily(): what changed on the last sealed KSA day for the products I sell —
  competitor price cuts and rises (>= MOVE_PCT, from each offer's closing
  price on the day before and the day), competitors that ran out or came back,
  my products about to run out, the best price moves to make, new products.
weekly(): the last 7 sealed days against the 7 before — my revenue and rank,
  campaigns, what running out cost, pricing actions, data coverage.
render_html(): one self-contained HTML email (Arabic, right-to-left).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape

MOVE_PCT = 3.0
TOP = 10


def _day(dt):
    import ledger
    return ledger.ksa_day_str(dt)


def last_sealed_day(now=None):
    now = now or datetime.now(timezone.utc)
    return _day(now - timedelta(days=1))


async def _competitor_moves(db, price_fn, day):
    """Price and stock changes of my products' competitor offers between the
    day before `day` and `day` (closing ledger rows)."""
    from comparison_views import context
    own, products, cohorts = await context(db, price_fn)
    mine = {p["sku"]: p for p in products if p.get("sku")}
    watch = {}
    for sku, c in cohorts.items():
        for s in c.get("sellers", []) + c.get("excluded", []):
            if s.get("sku"):
                watch[(s["store_id"], s["sku"])] = (sku, s.get("store_name"))
    prev = (datetime.fromisoformat(day) - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = defaultdict(dict)
    stores = list({k[0] for k in watch})
    async for r in db.daily_ledger.find({"store_id": {"$in": stores}, "ksa_date": {"$in": [prev, day]}},
                                        {"_id": 0, "store_id": 1, "sku": 1, "ksa_date": 1, "close_price": 1,
                                         "in_stock": 1, "qty_available": 1}):
        key = (r["store_id"], r["sku"])
        if key in watch:
            rows[key][r["ksa_date"]] = r
    cuts, rises, out, back = [], [], [], []
    for key, by in rows.items():
        a, b = by.get(prev), by.get(day)
        if not a or not b:
            continue
        my_sku, store_name = watch[key]
        mp = mine.get(my_sku) or {}
        base = {"sku": my_sku, "name_ar": mp.get("name_ar") or mp.get("name_en") or my_sku, "name_en": mp.get("name_en"), "store_name": store_name,
                "my_price": price_fn(mp) or None}
        pa, pb = a.get("close_price"), b.get("close_price")
        if pa and pb and pa > 0 and abs(pb - pa) / pa * 100 >= MOVE_PCT and b.get("in_stock") is not False:
            row = {**base, "old_price": pa, "new_price": pb, "change_pct": round((pb - pa) / pa * 100, 1)}
            row["now_cheaper_than_me"] = bool(row["my_price"] and pb < row["my_price"])
            (cuts if pb < pa else rises).append(row)
        if a.get("in_stock") is True and b.get("in_stock") is False:
            out.append({**base, "my_quantity": mp.get("quantity")})
        elif a.get("in_stock") is False and b.get("in_stock") is True:
            back.append({**base, "price": pb})
    cuts.sort(key=lambda r: (not r["now_cheaper_than_me"], r["change_pct"]))
    rises.sort(key=lambda r: -r["change_pct"])
    out.sort(key=lambda r: -(r.get("my_quantity") or 0))
    return {"price_cuts": cuts, "price_rises": rises, "went_out": out, "came_back": back}


async def daily(db, price_fn, pricing_rows=None, planner=None, now=None):
    day = last_sealed_day(now)
    moves = await _competitor_moves(db, price_fn, day)
    start, end = (datetime.fromisoformat(day) - timedelta(hours=3)).replace(tzinfo=timezone.utc), None
    new_by_store = defaultdict(int)
    names = {s["id"]: s.get("name") async for s in db.stores.find({}, {"_id": 0, "id": 1, "name": 1})}
    async for p in db.products.find({"first_seen_at": {"$gte": start.isoformat(),
                                                       "$lt": (start + timedelta(days=1)).isoformat()}},
                                    {"_id": 0, "store_id": 1}):
        new_by_store[names.get(p.get("store_id"), "?")] += 1
    report = {"kind": "daily", "day": day, "generated_at": datetime.now(timezone.utc).isoformat(),
              "counts": {k: len(v) for k, v in moves.items()},
              **{k: v[:TOP] for k, v in moves.items()},
              "new_products": dict(sorted(new_by_store.items(), key=lambda kv: -kv[1]))}
    if planner:
        report["running_out"] = [r for r in planner["rows"] if r["status"] == "critical"][:TOP]
        report["missed_while_out"] = sorted([r for r in planner["rows"] if r["status"] == "out" and r["competitor_revenue_while_oos"]],
                                            key=lambda r: -r["competitor_revenue_while_oos"])[:TOP]
    if pricing_rows is not None:
        report["raise_now"] = [r for r in pricing_rows if r["action"] == "raise"][:TOP]
        report["lower_now"] = [r for r in pricing_rows if r["action"] == "lower" and (r.get("units_30d") or 0) > 0][:TOP]
    return report


async def weekly(db, price_fn, pricing_summary=None, planner_week=None, coverage=None, campaigns=None, now=None):
    import ledger
    from evidence_ledger import sales_map
    now = now or datetime.now(timezone.utc)
    start, end = ledger.sealed_ksa_window(7, now)
    prev_start, prev_end = start - timedelta(days=7), start
    names = {s["id"]: (s.get("name"), s.get("is_own_store")) async for s in db.stores.find({}, {"_id": 0, "id": 1, "name": 1, "is_own_store": 1})}

    async def by_store(a, b):
        out = defaultdict(float)
        for (sid, _), r in (await sales_map(db, a, b)).items():
            out[sid] += r.get("revenue") or 0
        return out
    this, before = await by_store(start, end), await by_store(prev_start, prev_end)
    ranking = sorted(({"store": names.get(sid, (sid, False))[0], "own": bool(names.get(sid, (0, False))[1]),
                       "revenue": round(v, 2), "previous": round(before.get(sid, 0), 2),
                       "change_pct": round((v - before[sid]) / before[sid] * 100, 1) if before.get(sid) else None}
                      for sid, v in this.items() if v > 0), key=lambda r: -r["revenue"])
    mine = next((r for r in ranking if r["own"]), None)
    total = sum(r["revenue"] for r in ranking)
    return {"kind": "weekly", "from": _day(start), "to": _day(end - timedelta(seconds=1)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "my_revenue": mine["revenue"] if mine else None, "my_revenue_previous": mine["previous"] if mine else None,
            "my_change_pct": mine["change_pct"] if mine else None,
            "my_rank": (ranking.index(mine) + 1) if mine else None, "stores_ranked": len(ranking),
            "my_share_of_measured_pct": round(mine["revenue"] / total * 100, 1) if mine and total else None,
            "ranking": ranking, "pricing": pricing_summary, "stock": planner_week and planner_week.get("summary"),
            "campaigns": campaigns or [], "coverage": coverage or []}


def _table(headers, rows):
    th = "".join(f'<th style="text-align:right;padding:6px;border-bottom:1px solid #ddd;font-size:12px;color:#555">{escape(str(h))}</th>' for h in headers)
    trs = "".join("<tr>" + "".join(f'<td style="padding:6px;border-bottom:1px solid #eee;font-size:13px">{escape(str(c if c is not None else "—"))}</td>' for c in r) + "</tr>" for r in rows)
    return f'<table style="border-collapse:collapse;width:100%;margin:6px 0 18px">{"<tr>" + th + "</tr>"}{trs}</table>'


def render_html(report, app_url="https://daleel.hrm-sa.com"):
    h = ['<div dir="rtl" style="font-family:Tahoma,Arial,sans-serif;max-width:720px;margin:auto;color:#111">',
         '<h2 style="color:#13625F;margin-bottom:2px">دليل — ' + ("الموجز اليومي" if report["kind"] == "daily" else "التقرير الأسبوعي") + "</h2>"]
    if report["kind"] == "daily":
        h.append(f'<p style="color:#555;margin-top:0">تغيّرات يوم {escape(report["day"])} على منتجاتك</p>')
        sections = [("خفّض منافسون أسعارهم", "price_cuts", ["المنتج", "المتجر", "قبل", "بعد", "%", "سعري"],
                     lambda r: [r["name_ar"], r["store_name"], r["old_price"], r["new_price"], r["change_pct"], r["my_price"]]),
                    ("رفع منافسون أسعارهم", "price_rises", ["المنتج", "المتجر", "قبل", "بعد", "%", "سعري"],
                     lambda r: [r["name_ar"], r["store_name"], r["old_price"], r["new_price"], r["change_pct"], r["my_price"]]),
                    ("نفد لدى منافس (فرصة)", "went_out", ["المنتج", "المتجر", "مخزوني"], lambda r: [r["name_ar"], r["store_name"], r.get("my_quantity")]),
                    ("منتجاتي التي ستنفد قبل التوريد", "running_out", ["المنتج", "المخزون", "يكفي (أيام)", "اطلب"],
                     lambda r: [r["name_ar"], r["quantity"], r["days_of_cover"], r["reorder_qty"]]),
                    ("نفد لديّ وباعه المنافسون", "missed_while_out", ["المنتج", "أيام النفاد", "مبيعات المنافسين (ريال)"],
                     lambda r: [r["name_ar"], r["oos_days"], r["competitor_revenue_while_oos"]]),
                    ("فرص رفع السعر مع بقائك الأرخص", "raise_now", ["المنتج", "سعري", "المقترح", "ربح 30 يوماً"],
                     lambda r: [r["name_ar"], r["price"], r["recommended_price"], r.get("profit_change_30d")])]
        for title, key, headers, fn in sections:
            rows = report.get(key) or []
            if rows:
                count = report.get("counts", {}).get(key)
                h.append(f'<h3 style="margin-bottom:0">{title}{f" ({count})" if count else ""}</h3>')
                h.append(_table(headers, [fn(r) for r in rows]))
        if report.get("new_products"):
            h.append("<h3>منتجات جديدة لدى المنافسين</h3><p>" + "، ".join(f"{escape(str(k))}: {v}" for k, v in report["new_products"].items()) + "</p>")
    else:
        h.append(f'<p style="color:#555;margin-top:0">من {escape(report["from"])} إلى {escape(report["to"])}</p>')
        if report.get("my_revenue") is not None:
            ch = report.get("my_change_pct")
            h.append(f'<p style="font-size:15px">إيراداتك التقديرية: <b>{report["my_revenue"]:,.0f} ريال</b>'
                     + (f" ({'+' if ch > 0 else ''}{ch}% عن الأسبوع السابق)" if ch is not None else "")
                     + f' — الترتيب {report["my_rank"]} من {report["stores_ranked"]} متاجر قابلة للقياس.</p>')
        h.append("<h3>ترتيب المتاجر (7 أيام)</h3>" + _table(["المتجر", "الإيرادات", "الأسبوع السابق", "%"],
                                                         [[r["store"], f'{r["revenue"]:,.0f}', f'{r["previous"]:,.0f}', r["change_pct"]] for r in report["ranking"]]))
        p = report.get("pricing") or {}
        if p:
            by = p.get("by_action", {})
            h.append(f'<h3>التسعير</h3><p>{by.get("lower", 0)} منتجاً يحتاج تخفيضاً للمنافسة، و{by.get("raise", 0)} يمكن رفعه مع بقائك الأرخص'
                     f' (نحو {p.get("raise_profit_30d", 0):,.0f} ريال ربحاً إضافياً خلال 30 يوماً).</p>')
        s = report.get("stock") or {}
        if s:
            h.append(f'<h3>المخزون</h3><p>باع المنافسون {s.get("competitor_revenue_while_oos", 0):,.0f} ريال من منتجات كانت نافدة لديك هذا الأسبوع؛ '
                     f'{s.get("critical", 0)} منتجاً سينفد قبل التوريد و{s.get("reorder_products", 0)} يحتاج طلباً.</p>')
        if report.get("campaigns"):
            h.append("<h3>حملات المنافسين</h3>" + _table(["المتجر", "من", "إلى", "ذروة %", "متوسط الخصم %"],
                                                        [[c["store"], c["start"], c["end"], c["peak_share_pct"], c["avg_discount_pct"]] for c in report["campaigns"]]))
    h.append(f'<p style="margin-top:24px"><a href="{escape(app_url)}/reports" style="color:#1E988E">افتح التقرير في دليل</a></p>')
    h.append('<p style="color:#999;font-size:11px">الإيرادات تقديرية من التغير اليومي في المخزون أو عدّاد المبيعات العام، وليست فواتير.</p></div>')
    return "".join(h)
